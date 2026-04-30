#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
B 站分享链接「通用」下载：无需事先区分稿件视频与 Opus 动态。

内部先 ``classify_share_link`` 跟跳归类，再分别委托 ``ShareVideoDownload`` /
``ShareOpusDownload``。
"""
import json
from typing import Any, Dict

from toolbox.bilibili.media.share_download_base import BilibiliShareDownloadBase
from toolbox.bilibili.media.share_opus_download import ShareOpusDownload
from toolbox.bilibili.media.share_video_download import ShareVideoDownload

# 便于单模块导入基类（与历史路径对齐）
__all__ = ["BilibiliShareDownloadBase", "ShareMediaDownload"]


class ShareMediaDownload(BilibiliShareDownloadBase):
    """
    从一段分享文案或 URL 自动判断落地类型，拉取元信息或下载到本地。

    - 视频稿件：目录结构与 ``ShareVideoDownload`` 一致。
    - Opus 动态：目录结构与 ``ShareOpusDownload`` 一致。
    """

    def __init__(self) -> None:
        super().__init__()
        self.video = ShareVideoDownload()
        self.opus = ShareOpusDownload()

    def get_post_meta_by_share_text(self, text_or_url: str, timeout: int = 30) -> Dict[str, Any]:
        """
        解析分享入口，返回与对应子模块一致的 ``post_meta`` / ``opus`` 字段，
        并附加 ``share_kind``、``share_entry_url``、``share_final_url``（来自跟跳归类）。
        """
        info = self.classify_share_link(text_or_url, timeout=timeout)
        entry = info["entry_url"]
        if info["kind"] == "video":
            meta = self.video.get_post_meta_by_share_url(entry)
        else:
            meta = self.opus.get_opus_meta_by_url(entry)
        merged: Dict[str, Any] = dict(meta)
        merged["share_kind"] = info["kind"]
        merged["share_url"] = info["entry_url"]
        return merged

    def download_media_by_share_text(
        self,
        text_or_url: str,
        output_dir: str = "output_bilibili_share",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """按归类结果下载视频/封面或 Opus 正文与配图，返回子模块同结构的 result 字典。"""
        info = self.classify_share_link(text_or_url, timeout=timeout)
        entry = info["entry_url"]
        if info["kind"] == "video":
            return self.video.download_media_by_share_url(entry, output_dir=output_dir)
        return self.opus.download_opus_by_url(entry, output_dir=output_dir)


def main():
    client = ShareMediaDownload()
    share_text = """
https://b23.tv/1uHyBhd
    """
    # post_meta = client.get_post_meta_by_share_text(share_text)
    # print("post_meta:")
    # print(json.dumps(post_meta, ensure_ascii=False, indent=2))

    post_meta = client.download_media_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(post_meta, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
