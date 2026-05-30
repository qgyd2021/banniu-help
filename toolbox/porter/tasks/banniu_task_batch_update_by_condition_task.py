#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from jinja2 import Environment, StrictUndefined

logger = logging.getLogger("toolbox")

from project_settings import environment, project_path
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.banniu.sdk.banniu_client import AsyncBanNiuClient
from toolbox.banniu.form.column_list import ColumnListForm


@BaseTask.register("banniu_task_batch_update_by_condition")
class BanNiuTaskBatchUpdateByConditionTask(BaseTask, TaskJsonUtils):

    # column_name_to_key 的 value 支持 Jinja2 模板（默认 {{ ... }} 占位符），
    # 例如 "{{ post_review_final.approved_in_str }}" 或
    # "当前审核状态：{{ post_review_final.approved_in_str }}"。
    _jinja_env = Environment(autoescape=False, undefined=StrictUndefined)

    # task.list 单页规模与分页兜底
    _LIST_PAGE_SIZE = 100
    _LIST_MAX_PAGES = 1000

    def __init__(
        self,
        project_id: str,
        app_id: str,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        column_name_to_key: Dict[str, str],
        condition_column: list = None,
        batch_size: int = 200,
        key_of_app_key: str = "BANNIU_APP_KEY",
        key_of_app_secret: str = "BANNIU_APP_SECRET",
        key_of_access_token: str = "BANNIU_ACCESS_TOKEN",
    ):
        super().__init__(
            flag=f"[{self.__class__.__name__}_ProjectId_{project_id}]",
            check_interval=check_interval,
        )
        self.project_id = str(project_id)
        self.app_id = str(app_id)
        self.column_name_to_key = column_name_to_key or dict()
        self.condition_column = condition_column or list()
        self.batch_size = max(1, min(200, int(batch_size)))

        self.platform_to_dir: List[Tuple[str, Path, Path]] = list()
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

    async def get_column_form(self) -> ColumnListForm:
        return await self.banniu_client.build_form(project_id=self.project_id)

    @staticmethod
    def parse_success_task_ids(batch_resp: dict) -> Set[str]:
        success_ids: Set[str] = set()
        items = batch_resp["response"]["map"]["result"]
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

    @staticmethod
    def _condition_with_task_ids(condition_column: List[dict], task_ids: List[str]) -> List[dict]:
        """在用户提供的中文 condition 前面叠加一条 taskId(int) 包含任一项 的过滤条件。"""
        extra = {
            "字段": "taskId(int)",
            "字段类型": "数值类型",
            "搜索类型": "包含任一项",
            "搜索内容": [str(t) for t in task_ids],
        }
        return [extra] + list(condition_column)

    async def _query_allowed_task_ids(self, condition_column: List[dict]) -> Optional[Set[str]]:
        matched: Set[str] = set()
        page_num = 1
        while page_num <= self._LIST_MAX_PAGES:
            try:
                resp = await self.banniu_client.task_list_pretty(
                    project_id=self.project_id,
                    page_size=self._LIST_PAGE_SIZE,
                    page_num=page_num,
                    condition_column=condition_column,
                )
            except Exception as e:
                logger.error(
                    f"{self.flag}task.list 查询失败 page_num={page_num}, "
                    f"condition={json.dumps(condition_column, ensure_ascii=False)}, err={e}"
                )
                return None
            raw = (resp.get("response") or {}).get("map", {}).get("result")
            rows = raw if isinstance(raw, list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                tid = row.get("-1") if row.get("-1") not in (None, "") else row.get("0")
                if tid not in (None, ""):
                    matched.add(str(tid))
            if len(rows) < self._LIST_PAGE_SIZE:
                break
            page_num += 1
        else:
            logger.warning(f"{self.flag}task.list 分页超出上限 {self._LIST_MAX_PAGES}，提前停止")
        return matched

    def build_contents(self, payload: dict, column_form: ColumnListForm) -> Dict[str, str]:
        contents: Dict[str, str] = {}
        for column_name, template in self.column_name_to_key.items():
            cn = str(column_name).strip()
            tpl = str(template).strip()
            if not cn or not tpl:
                raise AssertionError(f"{self.flag}invalid column_name; column_name: {column_name}, template: {template}")
            col_id = column_form.get_column_id_by_name(cn)
            if not col_id:
                raise AssertionError(f"{self.flag}invalid column_name; column_name: {column_name}, template: {template}")
            text = self._jinja_env.from_string(tpl).render(**payload)
            mapped = column_form.map_option_value_to_id(column_id=col_id, value=text)
            contents[col_id] = "" if mapped is None else str(mapped)
        return contents

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return
        if not self.column_name_to_key:
            logger.error(f"{self.flag}column_name_to_key 为空，跳过")
            return

        column_form: ColumnListForm = await self.get_column_form()
        if not column_form.name_to_id:
            logger.error(f"{self.flag}column_list 解析为空，project_id={self.project_id}")
            return

        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            files: List[Path] = self.pick_task_files(source_dir, recursive=False)

            candidates: List[Dict[str, object]] = []
            for fp in files:
                payload = await self.load_json_file(fp)
                if payload is None:
                    continue
                task_id = payload["task_id"]

                contents = self.build_contents(payload=payload, column_form=column_form)
                if not contents:
                    logger.warning(f"{self.flag}未生成任何可更新字段，跳过: {fp.name}, platform={platform}")
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

                # 每批将 task_id 注入 condition，向班牛验证；查不到的不允许更新
                if self.condition_column:
                    task_ids_in_chunk = [str(item["task_id"]) for item in chunk]
                    condition_column = self._condition_with_task_ids(
                        self.condition_column, task_ids_in_chunk
                    )
                    allowed: Set[str] = await self._query_allowed_task_ids(condition_column)
                    if allowed is None:
                        logger.error(f"{self.flag}班牛条件查询失败，本批跳过: platform={platform}, size={len(chunk)}")
                        continue
                    filtered_chunk: List[Dict[str, object]] = []
                    for item in chunk:
                        if str(item["task_id"]) in allowed:
                            filtered_chunk.append(item)
                        else:
                            logger.info(f"{self.flag}班牛条件未命中，跳过: task_id={item['task_id']}, platform={platform}")
                    if not filtered_chunk:
                        continue
                    chunk = filtered_chunk

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
                    continue

                success_task_ids = self.parse_success_task_ids(resp)

                for item in chunk:
                    task_id = str(item["task_id"])
                    fp: Path = item["fp"]
                    payload: dict = item["payload"]
                    contents: dict = item["contents"]
                    dst_dir: Path = item["target_dir"]
                    if task_id not in success_task_ids:
                        continue
                    final = self.safe_move(fp, dst_dir / fp.name)
                    logger.info(
                        f"{self.flag}批量回写成功并流转: task_id={task_id}, platform={item['platform']}, "
                        f"-> {final.as_posix()}, column_ids={list(contents.keys())}"
                    )


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = BanNiuTaskBatchUpdateByConditionTask(
        project_id="39369",
        app_id="41339",
        check_interval=60,
        platform_to_dirs=[
            # ("douyin", "temp/banniu_37728/step_13_banniu_task_duplicate_update/douyin", "temp/banniu_37728/step_14_finished/douyin"),
            ("xiaohongshu", "temp/banniu_37728/step_13_banniu_task_duplicate_update/xiaohongshu", "temp/banniu_37728/step_14_finished/xiaohongshu"),
        ],
        column_name_to_key={
            "审核状态": "{{ post_review_final.approved_in_str }}",
            "审核不通过原因": "{{ post_review_final.reply_to_user }}",
        },
        condition_column=[
            {
                "字段": "审核状态",
                "字段类型": "文本类型",
                "搜索类型": "包含任一项",
                "搜索内容": [
                    "待审核",
                    "未通过"
                ],
            }
        ],
        batch_size=200,
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
