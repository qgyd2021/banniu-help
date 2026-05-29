#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils


@BaseTask.register("post_review_router")
class PostReviewRouterTask(BaseTask, TaskJsonUtils):
    """
    将待处理 task 文件按平台分流到不同目录。

    识别逻辑：
    - 仅处理 task_formatted["晒单内容链接"] 字段
    - 仅通过链接域名判断平台
    - 未识别时移动到 unknown_dir（若配置）
    """

    _PLATFORM_PATTERNS: Dict[str, List[str]] = {
        "xiaohongshu": [
            r"xhslink\.com",
            r"(?:www\.)?xiaohongshu\.com",
            r"(?:www\.)?rednote\.com",
        ],
        "dewu": [
            r"dw4\.co",
            r"m\.dewu\.com",
            r"(?:www\.)?dewu\.com",
        ],
        "douyin": [
            r"v\.douyin\.com",
            r"(?:www\.)?douyin\.com",
            r"(?:www\.)?iesdouyin\.com",
        ],
        "kuaishou": [
            r"v\.kuaishou\.com",
            r"(?:www\.)?kuaishou\.com",
            r"v\.m\.chenzhongtech\.com",
            r"m\.gifshow\.com",
        ],
        "bilibili": [
            r"b23\.tv",
            r"(?:www\.)?bilibili\.com",
            r"t\.bilibili\.com",
        ],
        "xiaoheihe": [
            r"(?:www\.)?xiaoheihe\.cn",
            r"api\.xiaoheihe\.cn",
        ],
        "weibo": [
            r"(?:www\.)?weibo\.com",
            r"m\.weibo\.cn",
            r"(?:www\.)?weibo\.cn",
        ],
    }

    def __init__(self,
                 check_interval: int,
                 source_dir: str,
                 platform_to_dir: Dict[str, str],
                 blank_dir: Optional[str],
                 unknown_dir: Optional[str],
                 share_post_url_field: str = "晒单内容链接",
                 ):
        super().__init__(
            flag=f"[{self.__class__.__name__}]",
            check_interval=check_interval
        )
        if not os.path.isabs(source_dir):
            self.source_dir = project_path / source_dir
        else:
            self.source_dir = Path(source_dir)

        self.platform_to_dir: Dict[str, Path] = {}
        for platform, dst in (platform_to_dir or {}).items():
            if not os.path.isabs(dst):
                self.platform_to_dir[str(platform).strip().lower()] = project_path / dst
            else:
                self.platform_to_dir[str(platform).strip().lower()] = Path(dst)

        self.blank_dir = (project_path / blank_dir) if not os.path.isabs(blank_dir) else Path(blank_dir)
        self.unknown_dir = (project_path / unknown_dir) if not os.path.isabs(unknown_dir) else Path(unknown_dir)

        self.share_post_url_field = share_post_url_field

    @staticmethod
    def _extract_urls_from_share_link_field(value: object) -> List[str]:
        urls: List[str] = []
        pattern = r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+"
        if isinstance(value, str):
            urls.extend(re.findall(pattern, value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    urls.extend(re.findall(pattern, item))
                elif isinstance(item, dict):
                    for _, v in item.items():
                        if isinstance(v, str):
                            urls.extend(re.findall(pattern, v))
        elif isinstance(value, dict):
            for _, v in value.items():
                if isinstance(v, str):
                    urls.extend(re.findall(pattern, v))
        return list(dict.fromkeys(urls))

    def _detect_platform(self, payload: dict) -> Tuple[Optional[str], str]:
        if not isinstance(payload, dict):
            return None, "invalid_payload"
        task_formatted = payload.get("task_formatted")
        if not isinstance(task_formatted, dict):
            return None, "no_task_formatted"

        share_link = task_formatted[self.share_post_url_field]
        urls = self._extract_urls_from_share_link_field(share_link)
        if not urls:
            return None, "no_share_link_url"

        for url in urls:
            low_url = url.lower()
            for platform, patterns in self._PLATFORM_PATTERNS.items():
                for pat in patterns:
                    if re.search(pat, low_url, flags=re.IGNORECASE):
                        return platform, f"url:{url}"

        return None, "no_platform_matched_by_url"

    def _target_path(self, src: Path, platform: Optional[str], reason: str) -> Optional[Path]:
        dst_dir = self.platform_to_dir.get(platform)
        if dst_dir is None:
            if reason == "no_share_link_url":
                dst_dir = self.blank_dir
            else:
                dst_dir = self.unknown_dir
        dst_dir.mkdir(parents=True, exist_ok=True)
        return dst_dir / src.name

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无待处理 json: {self.source_dir.as_posix()}")
            return

        moved = 0
        for fp in files:
            try:
                payload = await self.load_json_file(fp)
            except Exception as e:
                logger.error(f"{self.flag}读取/解析文件失败: {fp.as_posix()}, err={e}")
                continue
            platform, reason = self._detect_platform(payload)
            dst = self._target_path(fp, platform, reason)
            if dst is None:
                logger.info(f"{self.flag}未配置目标目录，跳过: {fp.name}, platform={platform}, reason={reason}")
                continue
            final = self.safe_move(fp, dst)
            moved += 1
            logger.info(f"{self.flag}路由完成: {fp.name} -> {final.as_posix()}, platform={platform}, reason={reason}")

        logger.info(f"{self.flag}本轮处理 {len(files)} 个文件，移动 {moved} 个文件。")


def main():
    import log
    from project_settings import project_path, log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewRouterTask(
        check_interval=60,
        source_dir="temp/banniu_39369/routed/blank",
        platform_to_dir={
            "xiaohongshu": "temp/banniu_39369/step_2_post_review_router/routed/xiaohongshu",
            "douyin": "temp/banniu_39369/step_2_post_review_router/routed/douyin",
            "kuaishou": "temp/banniu_39369/step_2_post_review_router/routed/kuaishou",
            "bilibili": "temp/banniu_39369/step_2_post_review_router/routed/bilibili",
            "xiaoheihe": "temp/banniu_39369/step_2_post_review_router/routed/xiaoheihe",
            "weibo": "temp/banniu_39369/step_2_post_review_router/routed/weibo",
        },
        blank_dir="temp/banniu_39369/step_2_post_review_router/routed/blank",
        unknown_dir="temp/banniu_39369/step_2_post_review_router/routed/unknown",
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
