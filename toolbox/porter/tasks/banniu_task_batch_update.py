#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from jinja2 import Environment, StrictUndefined

logger = logging.getLogger("toolbox")

from project_settings import environment, project_path
from toolbox.banniu.form.column_list import ColumnListForm
from toolbox.banniu.sdk.banniu_client import AsyncBanNiuClient
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils


@dataclass(frozen=True)
class ColumnUpdateSpec:
    template: str
    skip_if_empty: bool = False


class BanNiuColumnUpdateMixin(object):
    """
    列配置解析。

    column_name_to_key 的 value 支持：
    - 字符串：Jinja2 模板，等价于 skip_if_empty=False
    - 对象：{"template": "...", "skip_if_empty": true/false}
    """

    column_specs: Dict[str, ColumnUpdateSpec]

    def init_column_name_to_key(self, column_name_to_key: Dict[str, Any]) -> None:
        self.column_specs = self.parse_column_name_to_key(column_name_to_key or {})

    @classmethod
    def parse_column_name_to_key(cls, raw: Dict[str, Any]) -> Dict[str, ColumnUpdateSpec]:
        result: Dict[str, ColumnUpdateSpec] = {}
        for column_name, value in (raw or {}).items():
            cn = str(column_name).strip()
            if not cn:
                raise AssertionError(f"invalid column_name: {column_name!r}")

            if isinstance(value, str):
                template = value.strip()
                if not template:
                    raise AssertionError(f"invalid template for column {cn!r}")
                result[cn] = ColumnUpdateSpec(template=template, skip_if_empty=False)
                continue

            if isinstance(value, dict):
                template = str(value.get("template") or "").strip()
                if not template:
                    raise AssertionError(f"invalid template for column {cn!r}: {value!r}")
                skip_if_empty = bool(value.get("skip_if_empty", False))
                result[cn] = ColumnUpdateSpec(template=template, skip_if_empty=skip_if_empty)
                continue

            raise AssertionError(f"invalid column_name_to_key value for {cn!r}: {value!r}")
        return result


class BanNiuTaskBatchUpdateTaskBase(BanNiuColumnUpdateMixin, BaseTask, TaskJsonUtils):
    """班牛 batch update 公共流程（不注册为 Porter 任务）。"""

    _jinja_env = Environment(autoescape=False, undefined=StrictUndefined)

    def build_contents(self, payload: dict, column_form: ColumnListForm) -> Dict[str, str]:
        contents: Dict[str, str] = {}
        for column_name, spec in self.column_specs.items():
            text = self._jinja_env.from_string(spec.template).render(**payload).strip()
            if spec.skip_if_empty and not text:
                logger.info(
                    f"{self.flag}skip_if_empty: column={column_name!r}, template={spec.template!r}"
                )
                continue

            col_id = column_form.get_column_id_by_name(column_name)
            if not col_id:
                raise AssertionError(
                    f"{self.flag}invalid column_name; column_name: {column_name}, template: {spec.template}"
                )

            mapped = column_form.map_option_value_to_id(column_id=col_id, value=text)
            value = "" if mapped is None else str(mapped).strip()
            if spec.skip_if_empty and not value:
                logger.info(
                    f"{self.flag}skip_if_empty after map: column={column_name!r}, template={spec.template!r}"
                )
                continue

            contents[col_id] = value
        return contents

    def __init__(
        self,
        project_id: str,
        app_id: str,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        column_name_to_key: Dict[str, Any],
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
        self.init_column_name_to_key(column_name_to_key)
        self.batch_size = max(1, min(200, int(batch_size)))
        self.platform_to_dir = self._parse_platform_to_dirs(platform_to_dirs)

        app_key = environment.get(key_of_app_key)
        app_secret = environment.get(key_of_app_secret)
        access_token = environment.get(key_of_access_token)
        self.banniu_client = AsyncBanNiuClient(
            app_key=app_key, app_secret=app_secret, access_token=access_token
        )

    @staticmethod
    def _parse_platform_to_dirs(
        platform_to_dirs: List[Tuple[str, str, str]],
    ) -> List[Tuple[str, Path, Path]]:
        result: List[Tuple[str, Path, Path]] = []
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            if not os.path.isabs(src):
                src_path = project_path / src
            else:
                src_path = Path(src)
            if not os.path.isabs(dst):
                dst_path = project_path / dst
            else:
                dst_path = Path(dst)
            result.append((p, src_path, dst_path))
        return result

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

    async def prepare_chunk(
        self, chunk: List[Dict[str, object]], platform: str
    ) -> Tuple[List[Dict[str, object]], int, int]:
        """
        分批更新前的钩子。返回 (待更新 chunk, skip 增量, fail 增量)。
        默认不做过滤。
        """
        return chunk, 0, 0

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return
        if not self.column_specs:
            logger.error(f"{self.flag}column_name_to_key 为空，跳过")
            return

        column_form: ColumnListForm = await self.get_column_form()
        if not column_form.name_to_id:
            logger.error(f"{self.flag}column_list 解析为空，project_id={self.project_id}")
            return

        ok, skip, fail, scanned = 0, 0, 0, 0
        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(
                    f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}"
                )
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
                task_id = payload["task_id"]

                contents = self.build_contents(payload=payload, column_form=column_form)
                if not contents:
                    final = self.safe_move(fp, target_dir / fp.name)
                    skip += 1
                    logger.warning(
                        f"{self.flag}未生成任何可更新字段，直接流转: task_id={task_id}, platform={platform}, "
                        f"-> {final.as_posix()}"
                    )
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
                chunk, chunk_skip, chunk_fail = await self.prepare_chunk(chunk, platform)
                skip += chunk_skip
                fail += chunk_fail
                if not chunk:
                    continue

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
                    logger.error(
                        f"{self.flag}task_batch_update 异常: platform={platform}, size={len(chunk)}, err={e}"
                    )
                    fail += len(chunk)
                    continue

                success_task_ids = self.parse_success_task_ids(resp)

                for item in chunk:
                    task_id = str(item["task_id"])
                    fp: Path = item["fp"]
                    contents: dict = item["contents"]
                    dst_dir: Path = item["target_dir"]
                    if task_id not in success_task_ids:
                        fail += 1
                        continue
                    final = self.safe_move(fp, dst_dir / fp.name)
                    ok += 1
                    logger.info(
                        f"{self.flag}批量回写成功并流转: task_id={task_id}, platform={item['platform']}, "
                        f"-> {final.as_posix()}, column_ids={list(contents.keys())}"
                    )

        logger.info(f"{self.flag}本轮扫描 {scanned} 个文件，完成 ok={ok}, skip={skip}, fail={fail}")


@BaseTask.register("banniu_task_batch_update")
class BanNiuTaskBatchUpdateTask(BanNiuTaskBatchUpdateTaskBase):
    pass


@BaseTask.register("banniu_task_batch_update_by_condition")
class BanNiuTaskBatchUpdateByConditionTask(BanNiuTaskBatchUpdateTaskBase):
    _LIST_PAGE_SIZE = 100
    _LIST_MAX_PAGES = 1000

    def __init__(
        self,
        project_id: str,
        app_id: str,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        column_name_to_key: Dict[str, Any],
        condition_column: list = None,
        batch_size: int = 200,
        key_of_app_key: str = "BANNIU_APP_KEY",
        key_of_app_secret: str = "BANNIU_APP_SECRET",
        key_of_access_token: str = "BANNIU_ACCESS_TOKEN",
    ):
        super().__init__(
            project_id=project_id,
            app_id=app_id,
            check_interval=check_interval,
            platform_to_dirs=platform_to_dirs,
            column_name_to_key=column_name_to_key,
            batch_size=batch_size,
            key_of_app_key=key_of_app_key,
            key_of_app_secret=key_of_app_secret,
            key_of_access_token=key_of_access_token,
        )
        self.condition_column = condition_column or list()

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

    async def prepare_chunk(
        self, chunk: List[Dict[str, object]], platform: str
    ) -> Tuple[List[Dict[str, object]], int, int]:
        if not self.condition_column:
            return chunk, 0, 0

        task_ids_in_chunk = [str(item["task_id"]) for item in chunk]
        condition_column = self._condition_with_task_ids(self.condition_column, task_ids_in_chunk)
        allowed = await self._query_allowed_task_ids(condition_column)
        if allowed is None:
            logger.error(
                f"{self.flag}班牛条件查询失败，本批跳过: platform={platform}, size={len(chunk)}"
            )
            return [], 0, 0

        filtered_chunk: List[Dict[str, object]] = []
        for item in chunk:
            if str(item["task_id"]) in allowed:
                filtered_chunk.append(item)
            else:
                logger.info(
                    f"{self.flag}班牛条件未命中，跳过: task_id={item['task_id']}, platform={platform}"
                )

        skip = len(chunk) - len(filtered_chunk)
        return filtered_chunk, skip, 0


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = BanNiuTaskBatchUpdateByConditionTask(
        project_id="39369",
        app_id="41339",
        check_interval=60,
        platform_to_dirs=[
            (
                "xiaohongshu",
                "temp/banniu_37728/step_13_banniu_task_duplicate_update/xiaohongshu",
                "temp/banniu_37728/step_14_finished/xiaohongshu",
            ),
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
                "搜索内容": ["待审核", "未通过"],
            }
        ],
        batch_size=200,
    )
    asyncio.run(task.do_task())


def main2():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = BanNiuTaskBatchUpdateTask(
        project_id="39369",
        app_id="41339",
        check_interval=60,
        platform_to_dirs=[
            (
                "douyin",
                "temp/banniu_39369/step_3_douyin_share_media_download/tasks",
                "temp/banniu_39369/step_3_douyin_share_media_download/tasks_2",
            ),
            (
                "xiaohongshu",
                "temp/banniu_39369/step_3_xiaohongshu_share_media_download/tasks",
                "temp/banniu_39369/step_3_xiaohongshu_share_media_download/tasks_2",
            ),
        ],
        column_name_to_key={
            "抖音号或小红书号": {
                "template": "{{ post_meta.user_id }}",
                "skip_if_empty": True,
            },
        },
        batch_size=200,
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
