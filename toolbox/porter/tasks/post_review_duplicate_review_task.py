#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import copy
from collections import defaultdict
import json
import logging
from typing import Dict, List, Set, Tuple

import aiofiles

logger = logging.getLogger("toolbox")

from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils, global_file_lock_dict
from toolbox.porter.entity.post_meta import PostMeta
from toolbox.porter.entity.banniu_task import BanniuTaskFormatted
from toolbox.porter.entity.post_review import PostReview


@BaseTask.register("post_review_duplicate_review")
class PostReviewDuplicateReviewTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        post_duplicate_file: str,
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.platform_to_dir = list()
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            src = self.resolve_project_path(src)
            dst = self.resolve_project_path(dst)
            self.platform_to_dir.append((p, src, dst))

        self.post_duplicate_file = self.resolve_project_path(post_duplicate_file)
        self.author_id_to_task_ids: Dict[str, Set[str]] = None

    async def append_new_author_ids(self, platform: str, author_id: str, product_model: str, task_id: str):
        if author_id is None or str(author_id) == 0:
            return
        row = {"platform": platform, "author_id": author_id, "product_model": product_model, "task_id": task_id}
        row = json.dumps(row, ensure_ascii=False)

        path = self.post_duplicate_file
        path.parent.mkdir(parents=True, exist_ok=True)

        lock = global_file_lock_dict[path.as_posix()]
        async with lock:
            async with aiofiles.open(path.as_posix(), "a+", encoding="utf-8") as f:
                await f.write(f"{row}\n")

    async def load_author_id_to_task_ids(self) -> Dict[str, set]:
        result = defaultdict(set)

        path = self.post_duplicate_file
        lock = global_file_lock_dict[path.as_posix()]
        if not path.exists():
            return result

        async with lock:
            async with aiofiles.open(path.as_posix(), "r", encoding="utf-8") as f:
                raw = await f.read()

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

    def check_duplicate(self, platform: str, author_id: str, product_model: str, task_id: str) -> Set[str]:
        key = f"{platform}_{author_id}_{product_model}"
        value: set = self.author_id_to_task_ids[key]
        value = copy.deepcopy(value)
        value.discard(task_id)
        self.author_id_to_task_ids[key].add(task_id)
        return value

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return
        if not str(self.post_duplicate_file):
            logger.info(f"{self.flag}author_ids_file 无效，跳过")
            return

        if self.author_id_to_task_ids is None:
            self.author_id_to_task_ids = await self.load_author_id_to_task_ids()

        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            for src in files:
                payload: dict = await self.load_json_file(src)
                task_id = payload["task_id"]
                post_meta = PostMeta.from_dict(payload["post_meta"])
                platform = post_meta.platform
                author_id = post_meta.user_id
                task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
                product_model = task_formatted.product_model

                await self.append_new_author_ids(platform, author_id, product_model, task_id)
                task_ids: set = self.check_duplicate(platform, author_id, product_model, task_id)
                post_review = PostReview.from_dict(payload.get("post_review", dict()))
                post_review.review_duplicate.duplicate_task_ids = list(task_ids)

                dst = target_dir / src.name
                self.safe_move(src, dst)
                await self.append_kv_to_task_file(dst, kv={"post_review": post_review.to_dict()})


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewDuplicateReviewTask(
        check_interval=60,
        post_duplicate_file="temp/banniu_37728_v2/post_duplicatev.jsonl",
        platform_to_dirs=[
            ["xiaohongshu", "temp/banniu_37728_v2/step_3_xiaohongshu_share_media_download/tasks", "temp/banniu_37728_v2/step_4_post_review_duplicate_review/xiaohongshu"],
            ["dewu", "temp/banniu_37728_v2/step_3_dewu_share_media_download/tasks", "temp/banniu_37728_v2/step_4_post_review_duplicate_review/dewu"],
            ["douyin", "temp/banniu_37728_v2/step_3_douyin_share_media_download/tasks", "temp/banniu_37728_v2/step_4_post_review_duplicate_review/douyin"],
            ["kuaishou", "temp/banniu_37728_v2/step_3_kuaishou_share_media_download/tasks", "temp/banniu_37728_v2/step_4_post_review_duplicate_review/kuaishou"],
            ["bilibili", "temp/banniu_37728_v2/step_3_bilibili_share_media_download/tasks", "temp/banniu_37728_v2/step_4_post_review_duplicate_review/bilibili"],
            ["xiaoheihe", "temp/banniu_37728_v2/step_3_xiaoheihe_share_media_download/tasks", "temp/banniu_37728_v2/step_4_post_review_duplicate_review/xiaoheihe"],
            ["weibo", "temp/banniu_37728_v2/step_3_weibo_share_media_download/tasks", "temp/banniu_37728_v2/step_4_post_review_duplicate_review/weibo"]
        ],
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
