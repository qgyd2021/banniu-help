#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from collections import defaultdict
import json
import logging
import shutil
import traceback
from pathlib import Path
from typing import List, Optional

import aiofiles

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.porter.common.params import Params


global_file_lock_dict = defaultdict(asyncio.Lock)


class BaseTask(Params):
    def __init__(self,
                 flag: str,
                 check_interval: int,
                 ):
        super().__init__()
        self.flag = flag
        self.check_interval = check_interval

    @staticmethod
    def resolve_project_path(raw_path: str) -> Path:
        p = Path(raw_path)
        if p.is_absolute():
            return p.resolve()
        return (project_path / p).resolve()

    async def do_task(self):
        raise NotImplementedError

    async def start(self):
        while True:
            try:
                await self.do_task()
                logger.info(f"{self.flag}任务检测... 刷新间隔 {self.check_interval}s")
                await asyncio.sleep(self.check_interval)
            except Exception as error:
                logger.error(f"{self.flag}任务检测出错\nerror type: {type(error)}, error text: {error}, traceback: {traceback.format_exc()}")
                await asyncio.sleep(self.check_interval)
                continue


class TaskJsonUtils(object):
    """
    Porter 任务中常见的 task json：发现、异步加载、加锁写入、安全移动。

    与 ``BaseTask`` 组合使用：``class FooTask(BaseTask, TaskJsonUtils)``。
    依赖子类已通过 ``BaseTask`` 提供 ``self.flag``（用于日志）。
    """

    @staticmethod
    def pick_task_files(base: Path, recursive: bool = False) -> List[Path]:
        pattern = "**/*.json" if recursive else "*.json"
        return [p for p in base.glob(pattern) if p.is_file()]

    @staticmethod
    async def load_json_file(path: Path) -> Optional[dict]:
        async with aiofiles.open(path.as_posix(), "r", encoding="utf-8") as f:
            raw = await f.read()
        return json.loads(raw)

    @staticmethod
    def safe_move(src: Path, dst: Path) -> Path:
        if src.resolve() == dst.resolve():
            return dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.move(src.as_posix(), dst.as_posix())
            return dst
        stem = dst.stem
        suffix = dst.suffix
        idx = 1
        while True:
            cand = dst.parent / f"{stem}_{idx}{suffix}"
            if not cand.exists():
                shutil.move(src.as_posix(), cand.as_posix())
                return cand
            idx += 1

    async def write_json(self, path: Path, payload: dict) -> str:
        file_lock = global_file_lock_dict[path.as_posix()]
        tmp_path = path.with_name(f"{path.name}.tmp")
        async with file_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                async with aiofiles.open(tmp_path.as_posix(), "w", encoding="utf-8") as f:
                    await f.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                # 同盘 replace 为原子操作，避免写失败时破坏原文件。
                tmp_path.replace(path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
        return path.as_posix()

    async def append_kv_to_task_file(self, task_file: Path, kv: dict) -> str:
        payload = await self.load_json_file(task_file)
        payload = {
            **payload,
            **kv
        }
        await self.write_json(task_file, payload)
        return task_file.as_posix()


if __name__ == "__main__":
    pass
