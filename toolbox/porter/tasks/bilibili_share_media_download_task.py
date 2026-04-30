#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.bilibili.media.share_media_download import ShareMediaDownload


@BaseTask.register("bilibili_share_media_download")
class BilibiliShareMediaDownloadTask(BaseTask, TaskJsonUtils):
    """
    将 source_dir 下的 B 站 task 流转到 output_dir，并补充贴子元信息（不下载图片/视频）。
    """

    _BILIBILI_URL_PATTERNS = [
        r"https?://b23\.tv/[A-Za-z0-9_\-]+",
        r"https?://(?:www\.)?bilibili\.com/[^\s]+",
        r"https?://t\.bilibili\.com/[^\s]+",
    ]

    def __init__(self,
                 check_interval: int,
                 source_dir: str,
                 output_dir: str = "bilibili_share_media_download/tasks",
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
                urls.extend(BilibiliShareMediaDownloadTask._extract_urls_from_value(item))
        elif isinstance(value, dict):
            for _, v in value.items():
                urls.extend(BilibiliShareMediaDownloadTask._extract_urls_from_value(v))
        return list(dict.fromkeys(urls))

    @classmethod
    def _extract_bilibili_share_urls(cls, payload: dict) -> List[str]:
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
            for pat in cls._BILIBILI_URL_PATTERNS:
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
        meta_key, normalized_rows = self._normalize_meta_rows(meta_rows)
        payload[meta_key] = normalized_rows
        payload[f"{meta_key.replace('_list', '')}_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await self.write_json(task_file, payload)
        return task_file.as_posix()

    @staticmethod
    def _normalize_meta_rows(meta_rows: List[dict]) -> Tuple[str, List[dict]]:
        """
        将 meta_rows 规范化为项目希望的结构。

        - 小红书：直接展开 post_meta 字段，生成类似 examples/test.py 的扁平结构
        - 其他平台：保持原结构 {"share_url","fetched_at","post_meta":...}
        """
        if not meta_rows:
            return "bilibili_post_meta_list", []

        first = meta_rows[0] if isinstance(meta_rows[0], dict) else {}
        post_meta = first.get("post_meta") if isinstance(first, dict) else None
        # 小红书特征字段：note_id / user / interact_info / image_urls
        if isinstance(post_meta, dict) and (
            "note_id" in post_meta or ("user" in post_meta and "image_urls" in post_meta)
        ):
            out_rows: List[dict] = []
            for row in meta_rows:
                if not isinstance(row, dict):
                    continue
                share_url = str(row.get("share_url") or "").strip()
                fetched_at = str(row.get("fetched_at") or "").strip()
                pm = row.get("post_meta") if isinstance(row.get("post_meta"), dict) else {}

                user = pm.get("user") if isinstance(pm.get("user"), dict) else {}
                interact = pm.get("interact_info") if isinstance(pm.get("interact_info"), dict) else {}

                out_rows.append(
                    {
                        "platform": "xiaohongshu",
                        "share_url": share_url,
                        "fetched_at": fetched_at,
                        "title": str(pm.get("title") or ""),
                        "desc": str(pm.get("desc") or ""),
                        "tags": pm.get("tags") if isinstance(pm.get("tags"), list) else [],
                        "user_id": str(user.get("user_id") or ""),
                        "nickname": str(user.get("nickname") or ""),
                        "liked_count": interact.get("liked_count", ""),
                        "collected_count": interact.get("collected_count", ""),
                        "comment_count": interact.get("comment_count", ""),
                        "share_count": interact.get("share_count", ""),
                        "final_url": str(pm.get("final_url") or ""),
                        "image_urls": pm.get("image_urls") if isinstance(pm.get("image_urls"), list) else [],
                        "video_urls": pm.get("video_urls") if isinstance(pm.get("video_urls"), list) else [],
                    }
                )
            return "xiaohongshu_post_meta_list", out_rows

        return "bilibili_post_meta_list", meta_rows

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
            urls = self._extract_bilibili_share_urls(payload)
            if not urls:
                continue

            meta_rows: List[dict] = []
            for share_url in urls:
                try:
                    post_meta = await asyncio.to_thread(
                        self.share_media_client.get_post_meta_by_share_text,
                        share_url
                    )
                except Exception as e:
                    logger.error(f"{self.flag}拉取B站元信息失败: url={share_url}, err={e}")
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

    task = BilibiliShareMediaDownloadTask(
        check_interval=60,
        source_dir="data/banniu_task_download/routed/bilibili",
        output_dir="data/bilibili_share_media_download/tasks",
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
