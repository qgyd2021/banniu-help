#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("toolbox")

from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.porter.entity.post_review import PostReview, PostReviewFinal


def _build_score_rejection_reply(
    *,
    emotion_ok: bool,
    positive_emotion_labels: List[str],
    length_ok: bool,
    min_total_text_length: int,
    tags_ok: bool,
    missing_required_tags: List[str],
    min_image_count: int,
    max_image_cross_rate: float,
    min_video_count: int,
    max_video_cross_rate: float,
    media_ok: bool,
) -> str:
    """根据未通过的自动审核项拼接给用户的说明（仅在不通过时使用），语气为直接告知要求。"""
    parts: List[str] = []
    if not emotion_ok:
        labels = "、".join(positive_emotion_labels) if positive_emotion_labels else "积极"
        if len(positive_emotion_labels) <= 1:
            parts.append(f"内容情绪请保持{labels}。")
        else:
            parts.append(f"内容情绪请符合以下方向：{labels}。")
    if not length_ok:
        parts.append(f"标题与描述总字数请不少于 {min_total_text_length} 字。")
    if not tags_ok and missing_required_tags:
        parts.append(f"请带上以下话题标签：{'、'.join(missing_required_tags)}。")
    if not media_ok:
        img_pct = max_image_cross_rate * 100
        img_pct_s = f"{img_pct:.0f}" if abs(img_pct - round(img_pct)) < 1e-9 else f"{img_pct:.1f}"
        vid_pct = max_video_cross_rate * 100
        vid_pct_s = f"{vid_pct:.0f}" if abs(vid_pct - round(vid_pct)) < 1e-9 else f"{vid_pct:.1f}"
        parts.append(
            "图片或视频需满足其一："
            f"图片不少于 {min_image_count} 张且不符占比不高于 {img_pct_s}%；"
            f"或视频不少于 {min_video_count} 条且不符占比不高于 {vid_pct_s}%。"
        )
    return "；".join(parts) if parts else "内容暂未达到活动要求，请核对后重新提交。"


@BaseTask.register("post_review_score")
class PostReviewScoreTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        positive_emotion_labels: Optional[List[str]] = None,
        min_total_text_length: int = 0,
        required_tags: Optional[List[str]] = None,
        min_image_count: int = 0,
        max_image_cross_rate: float = 0.0,
        min_video_count: int = 0,
        max_video_cross_rate: float = 0.0,
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)

        self.platform_to_dir: List[Tuple[str, Path, Path]] = []
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            src_dir = self.resolve_project_path(src)
            dst_dir = self.resolve_project_path(dst)
            self.platform_to_dir.append((p, src_dir, dst_dir))

        self.positive_emotion_labels = [str(x).strip() for x in (positive_emotion_labels or ["积极"]) if str(x).strip()]
        self.min_total_text_length = int(min_total_text_length)
        self.required_tags = [str(x).strip() for x in (required_tags or []) if str(x).strip()]
        self.min_image_count = int(min_image_count)
        self.max_image_cross_rate = float(max_image_cross_rate)
        self.min_video_count = int(min_video_count)
        self.max_video_cross_rate = float(max_video_cross_rate)

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag} platform_to_dirs 为空，跳过")
            return

        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag} 源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            for src in files:
                payload = await self.load_json_file(src)
                post_review = PostReview.from_dict(payload.get("post_review", dict()))

                if post_review.review_final.approved is not None:
                    post_review_final = PostReviewFinal.from_dict(post_review.review_final.model_dump())
                else:
                    rt = post_review.review_text
                    ri = post_review.review_image
                    rv = post_review.review_video

                    # 1) 情绪是否积极（标题+描述的情绪总评）
                    emotion_ok = (str(rt.emotion_label or "").strip() in set(self.positive_emotion_labels))

                    # 2) 字数是否足够
                    total_text_len = int(rt.title_length or 0) + int(rt.desc_length or 0)
                    length_ok = total_text_len >= self.min_total_text_length

                    # 3) 必选标签是否包含（以 tags_match 为准）
                    tags_match_set = set([str(x).strip() for x in (rt.tags_match or []) if str(x).strip()])
                    required_set = set(self.required_tags)
                    tags_ok = required_set.issubset(tags_match_set)
                    missing_required_tags = sorted(list(required_set - tags_match_set))

                    # 4) 图片数量是否足够 + 不符合占比是否超过阈值（未标记=符合）
                    image_total = int(ri.total_count or 0)
                    image_cross = int(ri.cross_count or 0)
                    image_count_ok = image_total >= self.min_image_count
                    image_cross_rate = (float(image_cross) / float(image_total)) if image_total > 0 else 0.0
                    image_ok = (
                        image_total <= 0
                        or image_cross_rate <= self.max_image_cross_rate + 1e-12
                    )

                    # 5) 视频数量是否足够 + 不符合占比是否超过阈值（未标记=符合）
                    video_total = int(rv.total_count or 0)
                    video_cross = int(rv.cross_count or 0)
                    video_count_ok = video_total >= self.min_video_count
                    video_cross_rate = (float(video_cross) / float(video_total)) if video_total > 0 else 0.0
                    video_ok = (
                        video_total <= 0
                        or video_cross_rate <= self.max_video_cross_rate + 1e-12
                    )

                    image_pass = image_count_ok and image_ok
                    video_pass = video_count_ok and video_ok
                    media_ok = image_pass or video_pass

                    approved = all([emotion_ok, length_ok, tags_ok, media_ok])

                    post_review_final = PostReviewFinal.from_dict({})
                    post_review_final.approved = approved

                    if approved:
                        post_review_final.reply_to_user = ""
                    else:
                        post_review_final.reply_to_user = _build_score_rejection_reply(
                            emotion_ok=emotion_ok,
                            positive_emotion_labels=self.positive_emotion_labels,
                            length_ok=length_ok,
                            min_total_text_length=self.min_total_text_length,
                            tags_ok=tags_ok,
                            missing_required_tags=missing_required_tags,
                            min_image_count=self.min_image_count,
                            max_image_cross_rate=self.max_image_cross_rate,
                            min_video_count=self.min_video_count,
                            max_video_cross_rate=self.max_video_cross_rate,
                            media_ok=media_ok,
                        )

                dst = target_dir / src.name
                self.safe_move(src, dst)
                await self.append_kv_to_task_file(
                    dst,
                    kv={
                        "post_review_final": post_review_final.to_dict(),
                    },
                )


@BaseTask.register("post_review_only_final")
class PostReviewOnlyFinal(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)

        self.platform_to_dir: List[Tuple[str, Path, Path]] = []
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            src_dir = self.resolve_project_path(src)
            dst_dir = self.resolve_project_path(dst)
            self.platform_to_dir.append((p, src_dir, dst_dir))

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag} platform_to_dirs 为空，跳过")
            return

        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag} 源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            for src in files:
                payload = await self.load_json_file(src)
                post_review = PostReview.from_dict(payload.get("post_review", dict()))

                if post_review.review_final.approved is None:
                    logger.info(f"{self.flag} 此任务只处理带有人工终审的Task，跳过: platform={platform}, source={source_dir.as_posix()}")
                    continue

                post_review_final = PostReviewFinal.from_dict(post_review.review_final.model_dump())
                if post_review_final.approved:
                    post_review_final.approved_in_str = "已通过"
                elif not post_review_final.approved:
                    post_review_final.approved_in_str = "未通过"
                else:
                    logger.info(f"{self.flag} 此任务只处理带有人工终审的Task，跳过: platform={platform}, source={source_dir.as_posix()}")
                    continue

                dst = target_dir / src.name
                self.safe_move(src, dst)
                await self.append_kv_to_task_file(
                    dst,
                    kv={
                        "post_review_final": post_review_final.to_dict(),
                    },
                )


async def main() -> None:
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewScoreTask(
        check_interval=60,
        platform_to_dirs=[
            ["xiaohongshu", "temp/banniu_37728_v2/step_6_post_review_submit/xiaohongshu", "temp/banniu_37728_v2/step_7_post_review_final/xiaohongshu"],
            ["dewu", "temp/banniu_37728_v2/step_6_post_review_submit/dewu", "temp/banniu_37728_v2/step_7_post_review_final/dewu"],
            ["douyin", "temp/banniu_37728_v2/step_6_post_review_submit/douyin", "temp/banniu_37728_v2/step_7_post_review_final/douyin"],
            ["kuaishou", "temp/banniu_37728_v2/step_6_post_review_submit/kuaishou", "temp/banniu_37728_v2/step_7_post_review_final/kuaishou"],
            ["bilibili", "temp/banniu_37728_v2/step_6_post_review_submit/bilibili", "temp/banniu_37728_v2/step_7_post_review_final/bilibili"],
            ["xiaoheihe", "temp/banniu_37728_v2/step_6_post_review_submit/xiaoheihe", "temp/banniu_37728_v2/step_7_post_review_final/xiaoheihe"],
            ["weibo", "temp/banniu_37728_v2/step_6_post_review_submit/weibo", "temp/banniu_37728_v2/step_7_post_review_final/weibo"]
        ],
        positive_emotion_labels=["积极"],
        min_total_text_length=100,
        required_tags=["迈从ACE68v2", "迈从"],
        min_image_count=3,
        max_image_cross_rate=0.5,
        min_video_count=1,
        max_video_cross_rate=0.5,
    )
    await task.do_task()


if __name__ == "__main__":
    asyncio.run(main())
