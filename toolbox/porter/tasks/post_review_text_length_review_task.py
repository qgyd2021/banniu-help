#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("toolbox")

from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.porter.entity.post_meta import PostMeta
from toolbox.porter.entity.post_review import PostReview


@BaseTask.register("post_review_text_length_review")
class PostReviewTextLengthReviewTask(BaseTask, TaskJsonUtils):
    def __init__(self,
                 check_interval: int,
                 platform_to_dirs: List[Tuple[str, str, str]],
                 **kwargs
                 ):
        super().__init__(
            flag=f"[{self.__class__.__name__}]",
            check_interval=check_interval
        )
        self.platform_to_dir = list()
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            src = self.resolve_project_path(src)
            dst = self.resolve_project_path(dst)
            self.platform_to_dir.append((p, src, dst))

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return

        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            for src in files:
                payload = await self.load_json_file(src)
                post_meta = PostMeta.from_dict(payload["post_meta"])

                post_review = PostReview.from_dict(payload.get("post_review", dict()))
                post_review.review_text.title_length = len(post_meta.title)
                post_review.review_text.desc_length = len(post_meta.desc)

                dst = target_dir / src.name
                self.safe_move(src, dst)
                await self.append_kv_to_task_file(dst, kv={"post_review": post_review.to_dict()})


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewTextLengthReviewTask(
        check_interval=60,
        platform_to_dirs=[
            ("douyin", "data/douyin_share_media_download/text_emotion_review_finished", "data/douyin_share_media_download/text_length_review_finished"),
            ("xiaohongshu", "data/xiaohongshu_share_media_download/text_emotion_review_finished", "data/xiaohongshu_share_media_download/text_length_review_finished"),
            ("kuaishou", "data/kuaishou_share_media_download/text_emotion_review_finished", "data/kuaishou_share_media_download/text_length_review_finished"),
            ("bilibili", "data/bilibili_share_media_download/text_emotion_review_finished", "data/bilibili_share_media_download/text_length_review_finished"),
            ("xiaoheihe", "data/xiaoheihe_share_media_download/text_emotion_review_finished", "data/xiaoheihe_share_media_download/text_length_review_finished"),
        ],
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
