#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
import re
from typing import Dict, List, Optional

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.douyin.media.share_media_download import ShareMediaDownload


@BaseTask.register("douyin_share_media_download")
class DouyinShareMediaDownloadTask(BaseTask, TaskJsonUtils):
    """
    将 source_dir 下的抖音 task 流转到 output_dir，并补充抖音贴子元信息（不下载图片/视频）。
    """

    _DOUYIN_URL_PATTERNS = [
        r"https://v\.douyin\.com/[A-Za-z0-9_\-]+/",
        r"https?://www\.douyin\.com/[^\s]+",
        r"https?://www\.iesdouyin\.com/[^\s]+",
    ]

    def __init__(self,
                 check_interval: int,
                 source_dir: str,
                 output_dir: str = "douyin_share_media_download/tasks",
                 **kwargs
                 ):
        super().__init__(
            flag=f"[{self.__class__.__name__}]",
            check_interval=check_interval
        )

        if not os.path.isabs(source_dir):
            self.source_dir = project_path / source_dir
        else:
            self.source_dir = Path(source_dir)

        if not os.path.isabs(output_dir):
            self.output_dir = project_path / output_dir
        else:
            self.output_dir = Path(output_dir)

        self.share_media_client = ShareMediaDownload()

    @staticmethod
    def _extract_urls_from_value(value: object) -> List[str]:
        urls: List[str] = []
        pattern = r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+"
        if isinstance(value, str):
            urls.extend(re.findall(pattern, value))
        elif isinstance(value, list):
            for item in value:
                urls.extend(DouyinShareMediaDownloadTask._extract_urls_from_value(item))
        elif isinstance(value, dict):
            for _, v in value.items():
                urls.extend(DouyinShareMediaDownloadTask._extract_urls_from_value(v))
        return list(dict.fromkeys(urls))

    @classmethod
    def _extract_douyin_share_urls(cls, payload: dict) -> List[str]:
        if not isinstance(payload, dict):
            return []
        task_formatted = payload.get("task_formatted")
        if not isinstance(task_formatted, dict):
            return []
        share_link_value = task_formatted.get("晒单内容链接")
        urls = cls._extract_urls_from_value(share_link_value)

        out: List[str] = []
        for url in urls:
            low = url.lower()
            for pat in cls._DOUYIN_URL_PATTERNS:
                if re.search(pat, low, flags=re.IGNORECASE):
                    out.append(url.rstrip(".,;)"))
                    break
        return list(dict.fromkeys(out))

    async def _move_task_to_output(self, source_task_file: Path) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        dst = self.output_dir / source_task_file.name
        return await asyncio.to_thread(self.safe_move, source_task_file, dst)

    async def _append_post_meta_to_task_file(self, task_file: Path, meta_rows: List[dict]) -> str:
        payload = await self.load_json_file(task_file)
        if not isinstance(payload, dict):
            payload = {}
        payload["douyin_post_meta_list"] = meta_rows
        payload["douyin_post_meta_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await self.write_json(task_file, payload)
        return task_file.as_posix()

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无 task 文件: {self.source_dir.as_posix()}")
            return

        new_count = 0
        moved_count = 0
        for task_file in files:
            try:
                payload = await self.load_json_file(task_file)
            except Exception as e:
                logger.error(f"{self.flag}读取/解析失败: {task_file.as_posix()}, err={e}")
                continue
            urls = self._extract_douyin_share_urls(payload)
            if not urls:
                continue

            meta_rows: List[dict] = []
            for share_url in urls:
                try:
                    post_meta = await asyncio.to_thread(
                        self.share_media_client.get_post_meta_by_share_url,
                        share_url
                    )
                except Exception as e:
                    logger.error(f"{self.flag}拉取抖音元信息失败: url={share_url}, err={e}")
                    continue

                meta_rows.append({
                    "share_url": share_url,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "post_meta": post_meta,
                })
                new_count += 1

            if not meta_rows:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            moved_task_file = await self._move_task_to_output(task_file)
            save_path = await self._append_post_meta_to_task_file(
                task_file=moved_task_file,
                meta_rows=meta_rows,
            )
            moved_count += 1
            logger.info(f"{self.flag}任务流转并补充元信息成功: {save_path}, meta_count={len(meta_rows)}")

        logger.info(f"{self.flag}本轮新增元信息 {new_count} 条，成功流转任务 {moved_count} 个。")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = DouyinShareMediaDownloadTask(
        check_interval=60,
        source_dir="data/banniu_task_download/routed/douyin",
        output_dir="data/douyin_share_media_download/tasks",
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
