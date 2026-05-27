#!/usr/bin/python3
# -*- coding: utf-8 -*-
import aiofiles
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import logging
import os
from pathlib import Path
from typing import List, Set, Tuple

logger = logging.getLogger("toolbox")

from project_settings import environment, project_path, time_zone_info
from toolbox.porter.tasks.base_task import BaseTask, global_file_lock_dict
from toolbox.banniu.sdk.banniu_client import AsyncBanNiuClient
from toolbox.banniu.form.column_list import ColumnListForm
from toolbox.banniu.form.task_list import TaskListForm
from toolbox.asyncio.cacheout import async_cache_decorator


@BaseTask.register("banniu_task_download")
class BanNiuTaskDownloadTask(BaseTask):
    def __init__(self,
                 project_id: str,
                 check_interval: int,
                 fetch_delay_seconds: int = 0,
                 key_of_app_key: str = "BANNIU_APP_KEY",
                 key_of_app_secret: str = "BANNIU_APP_SECRET",
                 key_of_access_token: str = "BANNIU_ACCESS_TOKEN",
                 output_dir: str = "banniu_task_download/tasks",
                 last_fetch_tasks: str = "banniu_task_download/last_fetch_tasks.json",
                 last_fetch_time_txt: str = "banniu_task_download/last_fetch_time.txt",
                 **kwargs
                 ):
        super().__init__(
            flag=f"[{self.__class__.__name__}_ProjectId_{project_id}]",
            check_interval=check_interval
        )
        self.project_id = str(project_id)
        # 班牛工单创建后通常需要一段时间字段才会被同步/补齐完整；
        # 配置 fetch_delay_seconds > 0 后，拉取窗口的 end 不会超过 "当前时间 - 延迟"，
        # 等价于「工单创建至少满该秒数后才会被本任务拉取」。默认 0 表示不延迟。
        self.fetch_delay_seconds = max(0, int(fetch_delay_seconds or 0))
        self.time_zone_info = ZoneInfo(time_zone_info)

        if not os.path.isabs(output_dir):
            self.output_dir = project_path / output_dir
        else:
            self.output_dir = Path(output_dir)
        if not os.path.isabs(last_fetch_tasks):
            self.last_fetch_tasks = project_path / last_fetch_tasks
        else:
            self.last_fetch_tasks = Path(last_fetch_tasks)
        if not os.path.isabs(last_fetch_time_txt):
            self.last_fetch_time_txt = project_path / last_fetch_time_txt
        else:
            self.last_fetch_time_txt = Path(last_fetch_time_txt)

        app_key = environment.get(key_of_app_key)
        app_secret = environment.get(key_of_app_secret)
        access_token = environment.get(key_of_access_token)
        self.banniu_client = AsyncBanNiuClient(
            app_key=app_key,
            app_secret=app_secret,
            access_token=access_token,
        )

    async def load_last_fetch_start_time(self) -> str:
        fmt = "%Y-%m-%d %H:%M:%S"
        delayed_now_dt = datetime.now(self.time_zone_info) - timedelta(seconds=self.fetch_delay_seconds)
        delayed_now_str = delayed_now_dt.strftime(fmt)
        if not self.last_fetch_time_txt.exists():
            return delayed_now_str
        async with aiofiles.open(self.last_fetch_time_txt.as_posix(), "r", encoding="utf-8") as f:
            raw = await f.read()
            raw = raw.strip()
        if not raw:
            return delayed_now_str
        try:
            _ = datetime.strptime(raw, fmt)
            return raw
        except ValueError:
            return delayed_now_str

    async def save_last_fetch_end_time(self, end_created: str) -> str:
        file_lock = global_file_lock_dict[self.last_fetch_time_txt.as_posix()]
        async with file_lock:
            self.last_fetch_time_txt.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(self.last_fetch_time_txt.as_posix(), "w", encoding="utf-8") as f:
                await f.write(end_created.strip() + "\n")
        return self.last_fetch_time_txt.as_posix()

    async def get_time_window(self) -> Tuple[str, str]:
        start_str: str = await self.load_last_fetch_start_time()
        delayed_now_dt = datetime.now(self.time_zone_info) - timedelta(seconds=self.fetch_delay_seconds)
        fmt = "%Y-%m-%d %H:%M:%S"
        try:
            start_dt = datetime.strptime(start_str, fmt).replace(tzinfo=self.time_zone_info)
        except ValueError:
            start_dt = delayed_now_dt

        # banniu 限制查询区间最大 1 天：end_created - star_created <= 1 day
        max_end_dt = start_dt + timedelta(days=1)
        if delayed_now_dt <= start_dt:
            end_dt = start_dt
        elif delayed_now_dt > max_end_dt:
            end_dt = max_end_dt
        else:
            end_dt = delayed_now_dt

        start_str = start_dt.strftime(fmt)
        end_str = end_dt.strftime(fmt)
        return start_str, end_str

    @async_cache_decorator(10)
    async def load_dedupe_task_id_set(self) -> Set[str]:
        result: Set[str] = set()
        if not self.last_fetch_tasks.exists():
            return result
        async with aiofiles.open(self.last_fetch_tasks.as_posix(), "r", encoding="utf-8") as f:
            raw = await f.read()
        if len(raw.strip()) == 0:
            return result

        try:
            js = json.loads(raw)
        except json.JSONDecodeError:
            js = {}

        task_ids = js.get("task_ids") if isinstance(js, dict) else None
        if isinstance(task_ids, list):
            for token in task_ids:
                if token is not None and str(token).strip():
                    result.add(str(token).strip())
        return result

    async def append_dedupe_task_ids(self, task_ids: List[str]) -> str:
        file_lock = global_file_lock_dict[self.last_fetch_tasks.as_posix()]
        async with file_lock:
            existing_ids: Set[str] = set()
            if self.last_fetch_tasks.exists():
                async with aiofiles.open(self.last_fetch_tasks.as_posix(), "r", encoding="utf-8") as f:
                    raw = await f.read()
                    if raw.strip():
                        try:
                            js = json.loads(raw)
                        except json.JSONDecodeError:
                            js = {}
                        rows = js.get("task_ids") if isinstance(js, dict) else None
                        if isinstance(rows, list):
                            existing_ids = {str(x).strip() for x in rows if x is not None and str(x).strip()}

            merged_ids = sorted(existing_ids.union({str(x).strip() for x in task_ids if str(x).strip()}))
            self.last_fetch_tasks.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": datetime.now(self.time_zone_info).strftime("%Y-%m-%d %H:%M:%S"),
                "task_ids": merged_ids,
            }
            async with aiofiles.open(self.last_fetch_tasks.as_posix(), "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return self.last_fetch_tasks.as_posix()

    async def task_id_exists_in_last_fetch(self, task_id: str) -> bool:
        task_id = str(task_id).strip()
        if not task_id:
            return False
        last_tasks_ids = await self.load_dedupe_task_id_set()
        return task_id in last_tasks_ids

    async def fetch_column_form(self) -> ColumnListForm:
        js = await self.banniu_client.column_list(project_id=self.project_id)
        rows = (((js or {}).get("response") or {}).get("map") or {}).get("result") or []
        form = ColumnListForm(rows=rows if isinstance(rows, list) else [])
        return form

    async def fetch_task_rows_by_window(self, star_created: str, end_created: str) -> List[dict]:
        page_size = 50
        # 任务状态; task_status: 0, 待处理; 1, 已完成; 2, 处理中; 3, 暂停中; 4, 已关闭
        # task_status = 0 # 待处理
        # task_status = 2 # 处理中
        # task_status = None
        condition_column = [
            {
                "字段": "审核状态",
                "字段类型": "文本类型",
                "搜索类型": "等于",
                "搜索内容": "待审核",
                # "搜索内容": "未通过",
            }
        ]
        all_rows: List[dict] = []
        for task_status in (0, 2):
            page_num = 1
            while True:
                js = await self.banniu_client.task_list_pretty(
                    project_id=self.project_id,
                    star_created=star_created,
                    end_created=end_created,
                    page_size=page_size,
                    page_num=page_num,
                    task_status=task_status,
                    condition_column=condition_column,
                )
                rows = js["response"]["map"]["result"]
                form = TaskListForm(raw_rows=rows if isinstance(rows, list) else [])
                page_rows = form.raw_rows
                if not page_rows:
                    break
                all_rows.extend(page_rows)
                if len(page_rows) < page_size:
                    break
                page_num += 1
                if page_num > 200:
                    logger.warning(f"{self.flag}分页超过200页，提前停止。")
                    break
        return all_rows

    @staticmethod
    def convert_task_row(raw_row: dict, column_form: ColumnListForm) -> dict:
        if not isinstance(raw_row, dict):
            return {}
        task_form = TaskListForm(raw_rows=[raw_row])
        pretty_rows = task_form.get_pretty_rows(column_form=column_form)
        if not pretty_rows:
            return {}
        return pretty_rows[0]

    async def save_task_row_as_json_file(self, task_id: str, task_raw: dict, task_formatted: dict, **kwargs) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = self.output_dir / f"{task_id}.json"
        payload = {
            "task_id": task_id,
            "updated_at": datetime.now(self.time_zone_info).strftime("%Y-%m-%d %H:%M:%S"),
            "task_raw": task_raw,
            "task_formatted": task_formatted,
            **kwargs,
        }
        file_lock = global_file_lock_dict[filename.as_posix()]
        async with file_lock:
            async with aiofiles.open(filename.as_posix(), "w", encoding="utf-8") as f:
                await f.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return filename.as_posix()

    async def do_task(self):
        star_created, end_created = await self.get_time_window()
        logger.info(f"{self.flag}拉取窗口: {star_created} ~ {end_created}")

        column_form = await self.fetch_column_form()
        raw_rows = await self.fetch_task_rows_by_window(star_created=star_created, end_created=end_created)
        if not raw_rows:
            await self.save_last_fetch_end_time(end_created=end_created)
            logger.info(f"{self.flag}未拉取到任务数据。")
            return

        task_ids_seen = await self.load_dedupe_task_id_set()
        new_ids: List[str] = []
        new_count = 0
        for raw_row in raw_rows:
            task_id = TaskListForm.get_task_id(raw_row)
            if task_id is None:
                continue
            # 每次保存前都再检查一次 last_fetch_tasks.json，避免重复落盘。
            if await self.task_id_exists_in_last_fetch(task_id):
                continue
            formatted = self.convert_task_row(raw_row, column_form)
            await self.save_task_row_as_json_file(
                task_id=task_id,
                task_raw=raw_row,
                task_formatted=formatted,
                window_start=star_created,
                window_end=end_created,
            )
            task_ids_seen.add(task_id)
            new_ids.append(task_id)
            new_count += 1
            logger.info(f"{self.flag}新增任务 task_id={task_id}")

        await self.append_dedupe_task_ids(new_ids)
        await self.save_last_fetch_end_time(end_created=end_created)
        logger.info(f"{self.flag}本轮拉取 {len(raw_rows)} 条，新增 {new_count} 条。")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = BanNiuTaskDownloadTask(
        project_id="39369",
        check_interval=60,
        output_dir="temp/banniu_39369/step_1_banniu_task_download/tasks",
        last_fetch_tasks="temp/banniu_39369/step_1_banniu_task_download/last_fetch_tasks.json",
        last_fetch_time_txt="temp/banniu_39369/step_1_banniu_task_download/last_fetch_time.txt",
    )
    # 示例只执行一轮拉取，便于本地查看结果文件。
    asyncio.run(task.do_task())
    return


if __name__ == "__main__":
    main()
