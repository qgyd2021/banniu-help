#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
对「无视频」的任务直接打 0 分并流转到视频评分输出目录。
有视频的任务保留在源目录，继续由媒资审核（视频）流程处理。

与 ``PostReviewGetImageScoreBypassTask`` 对称：从各平台 ``*_post_meta_list`` 的 ``post_meta`` 中统计
``video_urls`` / ``video_url``；计数为 0 则旁路并写入 ``post_review_get_video_score``。
"""
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils


@BaseTask.register("post_review_get_video_score_bypass")
class PostReviewGetVideoScoreBypassTask(BaseTask, TaskJsonUtils):
    """
    对无视频稿件直接记 0 分并流转；有视频的留在上游目录等待审核。
    """

    def __init__(
        self,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
    ):
        super().__init__(
            flag=f"[{self.__class__.__name__}]",
            check_interval=check_interval,
        )

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

    @staticmethod
    def _extract_video_urls(post_meta: dict) -> List[str]:
        if not isinstance(post_meta, dict):
            return []
        urls: List[str] = []
        video_urls = post_meta.get("video_urls")
        if isinstance(video_urls, list):
            urls.extend([u for u in video_urls if isinstance(u, str) and u.startswith("http")])
        video_url = post_meta.get("video_url")
        if isinstance(video_url, str) and video_url.startswith("http"):
            urls.append(video_url)
        out: List[str] = []
        seen = set()
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
        return out

    def _count_videos(self, payload: dict) -> int:
        if not isinstance(payload, dict):
            return 0
        count = 0
        for key, value in payload.items():
            if not str(key).endswith("_post_meta_list") or not isinstance(value, list):
                continue
            for row in value:
                if not isinstance(row, dict):
                    continue
                post_meta = row.get("post_meta") or {}
                count += len(self._extract_video_urls(post_meta))
        return count

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return

        scanned, bypassed, kept = 0, 0, 0
        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(
                    f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}"
                )
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            for src in files:
                scanned += 1
                try:
                    payload = await self.load_json_file(src)
                except Exception as e:
                    logger.error(f"{self.flag}读取/解析失败: {src.as_posix()}, err={e}")
                    continue

                video_count = self._count_videos(payload)
                if video_count > 0:
                    kept += 1
                    continue

                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                payload["post_review_video_review"] = {"video_marks": {}}
                payload["post_review_video_review_status"] = "bypassed_no_video"
                payload["post_review_get_video_score"] = {
                    "score": 0,
                    "desc": "该任务未检测到视频，视频审核旁路，直接记 0 分。",
                    "video_count": 0,
                    "label_count": {"符合": 0, "不符合": 0, "空": 0},
                    "selected_top_scores": [],
                    "selected_top_streams": [],
                    "calculated_at": now,
                }
                payload["post_review_get_video_score_status"] = "done"
                payload["post_review_get_video_score_reason"] = "bypass_no_video"

                dst = target_dir / src.name
                final = await asyncio.to_thread(self.safe_move, src, dst)
                await self.write_json(final, payload)
                bypassed += 1
                logger.info(
                    f"{self.flag}无视频旁路并流转: {src.name} -> {final.as_posix()}, platform={platform}"
                )

        logger.info(f"{self.flag}本轮扫描 {scanned} 个文件，旁路 {bypassed} 个，保留 {kept} 个。")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewGetVideoScoreBypassTask(
        check_interval=60,
        platform_to_dirs=[
            (
                "bilibili",
                "temp/banniu_37728/step_7_banniu_task_text_update/bilibili",
                "temp/banniu_37728/step_9_post_review_get_video_score/bilibili",
            ),
        ],
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
