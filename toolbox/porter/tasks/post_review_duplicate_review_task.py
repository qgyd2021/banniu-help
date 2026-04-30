#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from collections import defaultdict
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiofiles

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils, global_file_lock_dict


@BaseTask.register("post_review_duplicate_review")
class PostReviewDuplicateReviewTask(BaseTask, TaskJsonUtils):
    """
    从每个帖子的 post_meta 中抽取作者 ID，去重后追加写入指定文件（一行一个 ID）；
    每轮 do_task 开始时从该文件加载历史 ID，再处理目录中的 task json 并流转。
    """

    def __init__(
        self,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        post_duplicate_file: str,
        platform_meta_config: Optional[Dict[str, Dict[str, object]]] = None,
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)

        self.platform_to_dir = list()
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

        if not os.path.isabs(post_duplicate_file):
            self.post_duplicate_file_path = project_path / post_duplicate_file
        else:
            self.post_duplicate_file_path = Path(post_duplicate_file)

        self.platform_meta_config = platform_meta_config or {}

        self.author_id_to_task_ids: Dict[str, List[str]] = None

    @staticmethod
    def get_nested(obj: object, dotted_key: str) -> object:
        cur: object = obj
        for part in str(dotted_key or "").split("."):
            if not part:
                continue
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    @staticmethod
    def get_author_id_path(conf: Dict[str, object]) -> List[str]:
        paths = conf.get("author_id_paths")
        if isinstance(paths, list) and paths:
            return [str(p).strip() for p in paths if str(p).strip()]
        author_id = conf.get("author_id_path")

        result = "user.user_id"
        if author_id is not None:
            result = str(author_id).strip()
        return result

    def get_author_id_from_payload(
        self, payload: dict, platform: str, conf: Dict[str, object]
    ) -> Tuple[str, str]:
        meta_list_key = str(conf.get("meta_list_key") or "").strip()
        if not meta_list_key:
            return None, "missing_meta_list_key"
        rows = payload.get(meta_list_key)
        if not isinstance(rows, list) or not rows:
            return None, "empty_meta_list"

        author_id_path = self.get_author_id_path(conf)
        row = rows[0]
        if not isinstance(row, dict):
            return None, None
        post_meta = row.get("post_meta")
        if not isinstance(post_meta, dict):
            post_meta = {}

        author_id = self.get_nested(post_meta, author_id_path)
        if author_id is not None:
            author_id = str(author_id).strip()
            if author_id:
                return author_id, None
        return author_id, None

    async def append_new_author_ids(self, platform: str, author_id: str, task_id: str):
        if author_id is None or str(author_id) == 0:
            return
        row = {"platform": platform, "author_id": author_id, "task_id": task_id}
        row = json.dumps(row, ensure_ascii=False)

        path = self.post_duplicate_file_path
        path.parent.mkdir(parents=True, exist_ok=True)

        lock = global_file_lock_dict[path.as_posix()]
        async with lock:
            async with aiofiles.open(path.as_posix(), "a+", encoding="utf-8") as f:
                await f.write(f"{row}\n")

    async def load_author_id_to_task_ids(self) -> Dict[str, set]:
        path = self.post_duplicate_file_path
        lock = global_file_lock_dict[path.as_posix()]
        if not path.exists():
            return list()

        async with lock:
            async with aiofiles.open(path.as_posix(), "r", encoding="utf-8") as f:
                raw = await f.read()

        result = defaultdict(set)
        for row in raw.splitlines():
            row = json.loads(row)
            platform = row["platform"]
            author_id = row["author_id"]
            task_id = row["task_id"]
            if author_id is None:
                continue
            if str(author_id) == 0:
                continue
            key = f"{platform}_{author_id}"
            result[key].add(task_id)

        return result

    def check_duplicate(self, platform: str, author_id: str, task_id: str):
        key = f"{platform}_{author_id}"
        value: set = self.author_id_to_task_ids[key]
        value.discard(task_id)
        return value

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return
        if not str(self.post_duplicate_file_path):
            logger.info(f"{self.flag}author_ids_file 无效，跳过")
            return

        if self.author_id_to_task_ids is None:
            self.author_id_to_task_ids = await self.load_author_id_to_task_ids()

        moved = 0
        processed = 0
        scanned = 0
        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            for src in files:
                scanned += 1
                payload = await self.load_json_file(src)
                if payload is None:
                    continue

                task_id = payload["task_id"]
                conf = self.platform_meta_config.get(platform)
                if not isinstance(conf, dict):
                    logger.info(f"{self.flag}缺少平台配置，跳过: platform={platform}, file={src.name}")
                    continue

                author_id, err = self.get_author_id_from_payload(payload, platform, conf)
                if author_id is None:
                    logger.info(f"{self.flag}未提取到 author_id，跳过: {src.name}, platform={platform}")
                    continue
                if err == "missing_meta_list_key":
                    logger.info(f"{self.flag}缺少 meta_list_key，跳过: {src.name}, platform={platform}")
                    continue
                if err == "empty_meta_list":
                    logger.info(f"{self.flag}meta 列表为空，跳过: {src.name}, platform={platform}")
                    continue

                await self.append_new_author_ids(platform, author_id, task_id)

                task_ids: set = self.check_duplicate(platform, author_id, task_id)

                duplicate = len(task_ids) > 0
                label = "是" if duplicate else "否"
                score = 0 if duplicate else 100
                desc = f"发贴作者存在重复，与之重复的工单号：{';'.join(task_ids)}" if duplicate else ""

                result = {
                    "platform": platform,
                    "author_id": author_id,
                    "task_ids": list(task_ids),
                    "label": label,
                    "score": score,
                    "desc": desc,
                    "post_duplicate_file_path": self.post_duplicate_file_path.as_posix(),
                    "meta_list_key": str(conf.get("meta_list_key") or ""),
                    "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                payload["post_review_duplicate_review"] = result
                payload["post_review_duplicate_review_status"] = "done"

                dst = target_dir / src.name
                final = self.safe_move(src, dst)
                await self.write_json(final, payload)
                processed += 1
                moved += 1
                logger.info(
                    f"{self.flag}作者 ID 收集并流转: {src.name} -> {final.as_posix()}, "
                    f"platform={platform}"
                )

        logger.info(f"{self.flag}本轮扫描 {scanned} 个文件，处理 {processed} 个，移动 {moved} 个。")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewDuplicateReviewTask(
        check_interval=60,
        post_duplicate_file="temp/banniu_37728/post_duplicatev.jsonl",
        platform_to_dirs=[
            (
                "xiaohongshu",
                "temp/banniu_37728/step_12_post_review_duplicate_review/xiaohongshu",
                "temp/banniu_37728/step_13_banniu_task_duplicate_update/xiaohongshu",
            ),
        ],
        platform_meta_config={
            "xiaohongshu": {"meta_list_key": "xiaohongshu_post_meta_list", "author_id_path": "user.user_id"},
        },
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
