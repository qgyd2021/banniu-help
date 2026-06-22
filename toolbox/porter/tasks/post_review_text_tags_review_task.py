#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import re
from typing import Dict, List, Tuple

logger = logging.getLogger("toolbox")

from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.porter.entity.post_meta import PostMeta
from toolbox.porter.entity.banniu_task import BanniuTaskFormatted
from toolbox.porter.entity.post_review import PostReview


@BaseTask.register("post_review_text_tags_review")
class PostReviewTextTagsReviewTask(BaseTask, TaskJsonUtils):
    """
    依据“标准名 + 相似名（同义词）”在标题/正文中做关键词检测，并统计每个标准名命中次数。
    """

    def __init__(
        self,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        tags_config: Dict[str, Dict[str, List[str]]] = None,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.platform_to_dir = list()
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            src = self.resolve_project_path(src)
            dst = self.resolve_project_path(dst)
            self.platform_to_dir.append((p, src, dst))
        self.tags_config = tags_config or dict()

    @staticmethod
    def desc_has_hashtag_tag(desc: str, tag: str) -> bool:
        """正文 desc 中出现 #标签 或 # 标签（# 后可有空白）时视为带有该标签。"""
        tag = str(tag or "").strip().lower()
        if not tag:
            return False
        text = str(desc or "").lower()
        if not text:
            return False
        pattern = r"#\s*" + re.escape(tag)
        return re.search(pattern, text) is not None

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return
        if not self.tags_config:
            logger.info(f"{self.flag}tags_config 为空，跳过")
            return

        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            for src in files:
                payload: dict = await self.load_json_file(src)
                task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
                post_meta = PostMeta.from_dict(payload["post_meta"])

                product_tags_config: Dict[str, List[str]] = self.tags_config.get(task_formatted.product_model)

                user_tags = [str(tag).strip().strip("#").strip().lower() for tag in post_meta.tags]

                match = set()
                desc = post_meta.desc or ""
                for standard, similar_list in product_tags_config.items():
                    for similar in similar_list:
                        similar = str(similar).lower()
                        if similar in user_tags or self.desc_has_hashtag_tag(desc, similar):
                            match.add(standard)
                            break
                miss = set(product_tags_config.keys()) - match

                post_review = PostReview.from_dict(payload.get("post_review", dict()))
                post_review.review_text.tags_match = list(match)
                post_review.review_text.tags_miss = list(miss)

                dst = target_dir / src.name
                await self.append_kv_to_task_file(src, kv={"post_review": post_review.to_dict()})
                self.safe_move(src, dst)


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewTextTagsReviewTask(
        check_interval=60,
        platform_to_dirs=[
            ("douyin", "temp/banniu_37728/step_4_post_review_text_emotion_review/douyin", "temp/banniu_37728/step_5_post_review_text_tags_review/douyin"),
            ("xiaohongshu", "temp/banniu_37728/step_4_post_review_text_emotion_review/xiaohongshu", "temp/banniu_37728/step_5_post_review_text_tags_review/xiaohongshu"),
        ],
        tags_config={
            "Ace68Turbo": {
                "迈从": ["迈从", "MCHose", "MC Hose"],
                "迈从Ace68Turbo": ["迈从Ace68Turbo", "迈从 Ace68Turbo", "Ace68Turbo"],
            },
            "Ace68GT": {
                "迈从": ["迈从", "MCHose", "MC Hose"],
                "迈从Ace68GT": ["迈从Ace68GT", "迈从 Ace68GT", "Ace68GT"],
            },
            "Ace68Air 2": {
                "迈从": ["迈从", "MCHose", "MC Hose"],
                "迈从Ace68Air2": ["迈从ace68air2", "迈从ace68air 2", "ace68air2", "ace68air 2"],
            },
            "A7V2": {
                "迈从": ["迈从", "MCHose", "MC Hose"],
                "迈从A7V2": ["迈从A7V2", "迈从 A7V2", "A7V2", "迈从A7鼠标"]
            },
            "Ace68V2": {
                "迈从": ["迈从", "MCHose", "MC Hose"],
                "迈从ACE68v2": ["迈从ACE68 v2", "迈从ACE68v2", "ACE68v2"],
            },
            "K20GT": {
                "迈从": ["迈从", "MCHose", "MC Hose"],
                "迈从K20GT": ["迈从K20GT", "迈从 K20GT", "K20GT"],
            },
        },
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
