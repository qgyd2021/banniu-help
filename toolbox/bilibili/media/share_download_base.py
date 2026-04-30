#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
B 站「分享链接」类下载器的公共基类。

抽取 `share_video_download`（稿件视频）与 `share_opus_download`（Opus 动态）共用的：
Session、默认请求头、文件名清洗、风控/验证码页判断、__INITIAL_STATE__ 解析、
http→https、带 Referer 的 CDN 请求头、流式下载文件。
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import requests


class BilibiliShareDownloadBase(object):
    """视频稿件与 Opus 动态共用的请求与工具；子类实现各自解析逻辑。"""

    # 从一段文案中提取「分享入口」时的匹配顺序（先 b23，再直链）
    _SHARE_ENTRY_URL_PATTERNS: List[str] = [
        r"https?://b23\.tv/[A-Za-z0-9]+(?:\?[^\s]*)?",
        r"https?://(?:www\.)?bilibili\.com/opus/\d+(?:\?[^\s]*)?",
        r"https?://(?:www\.)?bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)(?:/|\?[^\s]*)?",
        r"https?://m\.bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)(?:/|\?[^\s]*)?",
        r"https?://t\.bilibili\.com/\d+(?:\?[^\s]*)?",
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com",
    }

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(self.headers)

    @classmethod
    def find_share_entry_url(cls, text_or_url: str) -> str:
        """
        从分享文案或单独 URL 中取出一条 B 站分享入口链接（b23 / 视频页 / Opus / 动态）。
        """
        raw = (text_or_url or "").strip()
        if raw.startswith("http") and "\n" not in raw:
            single = raw.split()[0].rstrip(".,;)")
            if re.search(r"(?:b23\.tv|bilibili\.com)", single, re.I):
                return single
        for pattern in cls._SHARE_ENTRY_URL_PATTERNS:
            match = re.search(pattern, text_or_url, flags=re.IGNORECASE)
            if match is not None:
                return match.group(0).rstrip(".,;)")
        raise AssertionError(f"未识别到 B 站分享链接; text: {text_or_url!r}")

    def classify_share_link(self, text_or_url: str, timeout: int = 30) -> Dict[str, str]:
        """
        判断分享入口跟跳后的落地类型：``video``（稿件视频页）或 ``opus``（图文动态页）。

        返回字典字段：
        - ``kind``: ``\"video\"`` 或 ``\"opus\"``
        - ``entry_url``: 从文案解析出的入口 URL
        - ``final_url``: HTTP 跟跳后的浏览器地址栏 URL

        若命中验证码/风控页，抛出 ``AssertionError``。
        """
        entry_url = self.find_share_entry_url(text_or_url)
        response = self.session.get(entry_url, allow_redirects=True, timeout=timeout)
        if response.status_code != 200:
            raise AssertionError(
                f"classify_share_link 请求失败; status_code: {response.status_code}, url: {entry_url}"
            )
        if self._looks_like_captcha_or_risk(response):
            raise AssertionError(
                "链接落地为验证码或风控页，无法判断类型；请在浏览器完成验证后使用最终地址再试。"
            )
        final_url = response.url
        if re.search(r"bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)", final_url, re.I):
            return {"kind": "video", "entry_url": entry_url, "final_url": final_url}
        if re.search(r"bilibili\.com/opus/\d+", final_url, re.I):
            return {"kind": "opus", "entry_url": entry_url, "final_url": final_url}
        raise AssertionError(
            f"跟跳后无法归类为 video 或 opus: {final_url}；"
            "当前仅识别 www.bilibili.com/video/… 与 www.bilibili.com/opus/… 落地页。"
        )

    @staticmethod
    def sanitize_filename(name: str, max_len: int = 80) -> str:
        name = re.sub(r'[\\/:*?"<>|]', "_", (name or "").strip())
        name = re.sub(r"\s+", " ", name).strip(" .")
        if not name:
            name = "untitled"
        return name[:max_len]

    @staticmethod
    def _looks_like_captcha_or_risk(response: requests.Response) -> bool:
        text = response.text or ""
        u = (response.url or "").lower()
        if "passport.bilibili.com" in u or "/h5/project-verify" in u:
            return True
        if "gcaptcha4.geetest.com" in text.lower() or "api.geevisit.com" in text.lower():
            return True
        if re.search(r"<title>[^<]*验证码[^<]*</title>", text, flags=re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _extract_initial_state_json(html: str) -> Optional[Dict[str, Any]]:
        patterns = [
            r"__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;\s*\(function",
            r"__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;\s*</script>",
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.DOTALL)
            if not match:
                continue
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _https_url(url: str) -> str:
        if url.startswith("http://"):
            parts = urlparse(url)
            return urlunparse(("https", parts.netloc, parts.path, parts.params, parts.query, parts.fragment))
        return url

    def _headers_for_video_cdn(self, referer: str, origin: str = "https://www.bilibili.com") -> Dict[str, str]:
        """图床 / 视频 CDN 常校验 Referer + Origin。"""
        return {
            **self.headers,
            "Referer": referer,
            "Origin": origin,
        }

    def download_file(self, url: str, filename: Path, referer: Optional[str] = None, timeout: int = 120) -> Path:
        filename = Path(filename)
        filename.parent.mkdir(parents=True, exist_ok=True)
        headers = self._headers_for_video_cdn(referer or "https://www.bilibili.com/")
        response = self.session.get(url, stream=True, timeout=timeout, headers=headers)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {url}")
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return filename


def main():
    """
    示例：从分享文案提取入口链接，并判断跟跳后是视频稿件还是 Opus 动态。
    运行：python -m toolbox.bilibili.media.share_download_base
    """
    client = BilibiliShareDownloadBase()

    share_text_video = "【示例】复制打开 https://b23.tv/4UwmGmu 观看视频"
    share_text_opus = "动态示例 https://b23.tv/1uHyBhd"

    print("=== find_share_entry_url ===")
    print("video:", client.find_share_entry_url(share_text_video))
    print("opus:", client.find_share_entry_url(share_text_opus))

    print("\n=== classify_share_link ===")
    for label, text in (("video", share_text_video), ("opus", share_text_opus)):
        try:
            info = client.classify_share_link(text)
            print(f"{label}:", json.dumps(info, ensure_ascii=True, indent=2))
        except AssertionError as exc:
            print(f"{label} failed:", str(exc))


if __name__ == "__main__":
    main()
