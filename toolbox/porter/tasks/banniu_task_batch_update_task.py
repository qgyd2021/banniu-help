#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("toolbox")

from project_settings import environment, project_path
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.banniu.banniu_client import AsyncBanNiuClient
from toolbox.banniu.form.column_list import ColumnListForm
from toolbox.banniu.form.task_list import TaskListForm


@BaseTask.register("banniu_task_batch_update")
class BanNiuTaskBatchUpdateTask(BaseTask, TaskJsonUtils):
    """
    班牛批量回写任务：按批（最多 200）调用 task_batch_update。

    - 成功项：写回结果并流转到目标目录。
    - 失败项：不流转，不写 done，等待下轮轮询自然重试。
    """

    def __init__(
        self,
        project_id: str,
        app_id: str,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        column_name_to_score_key: Dict[str, str],
        score_payload_key: str,
        result_field_prefix: str = "post_review_banniu_batch_update",
        batch_size: int = 200,
        key_of_app_key: str = "BANNIU_APP_KEY",
        key_of_app_secret: str = "BANNIU_APP_SECRET",
        key_of_access_token: str = "BANNIU_ACCESS_TOKEN",
        **kwargs,
    ):
        super().__init__(
            flag=f"[{self.__class__.__name__}_ProjectId_{project_id}]",
            check_interval=check_interval,
        )
        self.project_id = str(project_id)
        self.app_id = str(app_id)
        self.column_name_to_score_key = dict(column_name_to_score_key or {})
        self.score_payload_key = str(score_payload_key or "").strip()
        self.result_field_prefix = str(result_field_prefix or "post_review_banniu_batch_update").strip()
        self.batch_size = max(1, min(200, int(batch_size)))

        self.platform_to_dir: List[Tuple[str, Path, Path]] = []
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            if not os.path.isabs(src):
                src = project_path / src
            else:
                src = Path(src)
            if not os.path.isabs(dst):
                dst = project_path / dst
            else:
                dst = Path(dst)
            self.platform_to_dir.append((p, src, dst))

        app_key = environment.get(key_of_app_key)
        app_secret = environment.get(key_of_app_secret)
        access_token = environment.get(key_of_access_token)
        self.banniu_client = AsyncBanNiuClient(app_key=app_key, app_secret=app_secret, access_token=access_token)
        self._column_form: Optional[ColumnListForm] = None

    async def _get_column_form(self) -> ColumnListForm:
        if self._column_form is not None:
            return self._column_form
        js = await self.banniu_client.column_list(project_id=self.project_id)
        rows = (((js or {}).get("response") or {}).get("map") or {}).get("result") or []
        self._column_form = ColumnListForm(rows=rows if isinstance(rows, list) else [])
        _ = self._column_form.name_to_id
        return self._column_form

    @staticmethod
    def _get_nested(obj: object, dotted_key: str) -> object:
        cur: object = obj
        for part in str(dotted_key).split("."):
            part = part.strip()
            if not part:
                continue
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def _build_contents(self, score_payload: dict, column_form: ColumnListForm) -> Dict[str, str]:
        contents: Dict[str, str] = {}
        for column_name, score_key in self.column_name_to_score_key.items():
            cn = str(column_name).strip()
            sk = str(score_key).strip()
            if not cn or not sk:
                continue
            col_id = column_form.get_column_id_by_name(cn)
            if not col_id:
                logger.error(f"{self.flag}列名在 column_list 中未找到: {cn!r}")
                continue
            value = self._get_nested(score_payload, sk)
            if value is None:
                text = ""
            elif isinstance(value, (dict, list)):
                text = json.dumps(value, ensure_ascii=False)
            else:
                text = str(value)
            contents[col_id] = text
        return contents

    @staticmethod
    def parse_success_task_ids(batch_resp: dict) -> Set[str]:
        success_ids: Set[str] = set()
        items = batch_resp["response"]["map"]["result"]
        print(items)
        for msg in items:
            text = str(msg or "")
            match = re.search(r"工单id:(\d+)", text)
            if match is None:
                continue
            for keyword in ["成功, 但是没有数据", "没有发现需要更新的数据"]:
                if keyword in text:
                    success_ids.add(match.group(1))
                    break
        return success_ids

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return
        if not self.score_payload_key:
            logger.error(f"{self.flag}score_payload_key 为空，跳过")
            return

        column_form = await self._get_column_form()
        if not column_form.name_to_id:
            logger.error(f"{self.flag}column_list 解析为空，project_id={self.project_id}")
            return

        status_key = f"{self.result_field_prefix}_status"
        reason_key = f"{self.result_field_prefix}_reason"

        ok, skip, fail, scanned = 0, 0, 0, 0
        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            files: List[Path] = self.pick_task_files(source_dir, recursive=False)

            candidates: List[Dict[str, object]] = []
            for fp in files:
                scanned += 1
                payload = await self.load_json_file(fp)
                if payload is None:
                    fail += 1
                    continue
                if payload.get(status_key) == "done":
                    skip += 1
                    continue
                task_id = str(payload.get("task_id") or "").strip()
                if not task_id:
                    task_id = TaskListForm.get_task_id(payload.get("task_raw") or {}) or ""
                if not task_id:
                    logger.warning(f"{self.flag}缺少 task_id，跳过: {fp.name}, platform={platform}")
                    skip += 1
                    continue
                score_payload = payload.get(self.score_payload_key)
                if not isinstance(score_payload, dict):
                    logger.info(f"{self.flag}无 {self.score_payload_key}，跳过: {fp.name}, platform={platform}")
                    skip += 1
                    continue
                contents = self._build_contents(score_payload=score_payload, column_form=column_form)
                if not contents:
                    logger.warning(f"{self.flag}未生成任何可更新字段，跳过: {fp.name}, platform={platform}")
                    skip += 1
                    continue
                candidates.append(
                    {
                        "fp": fp,
                        "payload": payload,
                        "task_id": task_id,
                        "contents": contents,
                        "platform": platform,
                        "target_dir": target_dir,
                    }
                )

            if not candidates:
                continue

            for i in range(0, len(candidates), self.batch_size):
                chunk = candidates[i : i + self.batch_size]
                data = [
                    {
                        "project_id": self.project_id,
                        "app_id": self.app_id,
                        "task_id": str(item["task_id"]),
                        "contents": item["contents"],
                        "header": None,
                    }
                    for item in chunk
                ]
                try:
                    resp = await self.banniu_client.task_batch_update(data=data)
                except Exception as e:
                    logger.error(f"{self.flag}task_batch_update 异常: platform={platform}, size={len(chunk)}, err={e}")
                    fail += len(chunk)
                    continue

                success_task_ids = self.parse_success_task_ids(resp)

                for item in chunk:
                    task_id = str(item["task_id"])
                    fp: Path = item["fp"]  # type: ignore[assignment]
                    payload: dict = item["payload"]  # type: ignore[assignment]
                    contents: dict = item["contents"]  # type: ignore[assignment]
                    dst_dir: Path = item["target_dir"]  # type: ignore[assignment]
                    if task_id not in success_task_ids:
                        fail += 1
                        continue
                    payload[self.result_field_prefix] = {
                        "platform": item["platform"],
                        "score_payload_key": self.score_payload_key,
                        "contents": contents,
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    payload[status_key] = "done"
                    payload[reason_key] = "task_batch_update_called"
                    final = self.safe_move(fp, dst_dir / fp.name)
                    await self.write_json(final, payload)
                    ok += 1
                    logger.info(
                        f"{self.flag}批量回写成功并流转: task_id={task_id}, platform={item['platform']}, "
                        f"-> {final.as_posix()}, column_ids={list(contents.keys())}"
                    )

        logger.info(f"{self.flag}本轮扫描 {scanned} 个文件，完成 ok={ok}, skip={skip}, fail={fail}")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = BanNiuTaskBatchUpdateTask(
        project_id="37728",
        app_id="41339",
        check_interval=60,
        platform_to_dirs=[
            # ("douyin", "temp/banniu_37728/step_13_banniu_task_duplicate_update/douyin", "temp/banniu_37728/step_14_finished/douyin"),
            ("xiaohongshu", "temp/banniu_37728/step_13_banniu_task_duplicate_update/xiaohongshu", "temp/banniu_37728/step_14_finished/xiaohongshu"),
        ],
        score_payload_key="post_review_duplicate_review",
        column_name_to_score_key={
            "重复发贴（自动）": "score",
            "重复发贴原因（自动）": "desc"
        },
        result_field_prefix="post_review_banniu_duplicate_update",
        batch_size=200,
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
