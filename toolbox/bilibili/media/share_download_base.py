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

import cacheout
import requests


class BilibiliShareDownloadBaseRestful(object):
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

    @cacheout.memoize(ttl=30)
    def get_web_dynamic(self, dynamic_id: str, timeout: int = 30) -> Dict[str, Any]:
        response = self.session.get(
            url="https://api.bilibili.com/x/polymer/web-dynamic/v1/detail",
            params={
                "id": dynamic_id,
                "features": "itemOpusStyle,opusBigCover,onlyfansVote,endFooterHidden,decorationCard,onlyfansAssetsV2,ugcDelete,onlyfansQaCard,editable,opusPrivateVisible,avatarAutoTheme,sunflowerStyle,cardsEnhance,eva3CardOpus,eva3CardVideo,eva3CardComment,eva3CardVote,eva3CardUser",
            },
            timeout=timeout,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"dynamic detail api failed; status_code: {response.status_code}, dynamic_id: {dynamic_id}"
            )
        js = response.json()
        if js.get("code") != 0:
            raise AssertionError(
                f"dynamic detail api error; code: {js.get('code')}, message: {js.get('message')}, dynamic_id: {dynamic_id}"
            )
        return js

    def get_final_url_by_share_url(self, share_url: str) -> str:
        response = self.session.get(share_url, headers=self.headers, timeout=30)
        return response.url


class BilibiliShareDownloadBase(BilibiliShareDownloadBaseRestful):
    """视频稿件与 Opus 动态共用的请求与工具；子类实现各自解析逻辑。"""

    # 从一段文案中提取「分享入口」时的匹配顺序（先 b23，再直链）
    _SHARE_ENTRY_URL_PATTERNS: List[str] = [
        r"https?://b23\.tv/[A-Za-z0-9]+(?:\?[^\s]*)?",
        r"https?://(?:www\.)?bilibili\.com/opus/\d+(?:\?[^\s]*)?",
        r"https?://(?:www\.)?bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)(?:/|\?[^\s]*)?",
        r"https?://m\.bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)(?:/|\?[^\s]*)?",
        r"https?://t\.bilibili\.com/\d+(?:\?[^\s]*)?",
    ]

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

    @staticmethod
    def parse_dynamic_id_from_url(url: str) -> Optional[str]:
        match = re.search(r"t\.bilibili\.com/(\d+)", url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def get_video_url_from_web_dynamic(self, dynamic_id: str, timeout: int = 30) -> Optional[str]:
        js = self.get_web_dynamic(dynamic_id, timeout=timeout)
        item = js["data"]["item"]

        major_archive = item["modules"]["module_dynamic"]["major"].get("archive")
        if not isinstance(major_archive, dict):
            return None

        bvid = major_archive.get("bvid")
        if isinstance(bvid, str) and bvid:
            return f"https://www.bilibili.com/video/{bvid}/"

        for key in ("jump_url", "jump_uri", "url"):
            url = major_archive.get(key)
            if not isinstance(url, str) or not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            if re.search(r"bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)", url, re.I):
                return url
        return None

    def classify_share_link(self, text_or_url: str, timeout: int = 30) -> Dict[str, str]:
        entry_url = self.find_share_entry_url(text_or_url)
        response = self.session.get(entry_url, allow_redirects=True, timeout=timeout)
        if response.status_code != 200:
            raise AssertionError(
                f"classify_share_link 请求失败; status_code: {response.status_code}, url: {entry_url}"
            )
        if self.looks_like_captcha_or_risk(response):
            raise AssertionError(
                "链接落地为验证码或风控页，无法判断类型；请在浏览器完成验证后使用最终地址再试。"
            )
        final_url = response.url
        if re.search(r"bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)", final_url, re.I):
            return {"kind": "video", "entry_url": entry_url, "final_url": final_url}
        if re.search(r"bilibili\.com/opus/\d+", final_url, re.I):
            return {"kind": "opus", "entry_url": entry_url, "final_url": final_url}
        dynamic_id = self.parse_dynamic_id_from_url(final_url)
        if dynamic_id:
            js = self.get_web_dynamic(dynamic_id, timeout=timeout)
            item = js["data"]["item"]
            item_type = item["type"]
            major_type = item["modules"]["module_dynamic"]["major"]["type"]
            major_archive = item["modules"]["module_dynamic"]["major"].get("archive")

            if item_type == "DYNAMIC_TYPE_AV" or major_type == "MAJOR_TYPE_ARCHIVE" or major_archive:
                video_url = self.get_video_url_from_web_dynamic(dynamic_id)
                if not video_url:
                    raise AssertionError(
                        f"动态为视频类型但未解析到视频地址；dynamic_id: {dynamic_id}；final_url: {final_url}"
                    )
                return {"kind": "video", "entry_url": entry_url, "final_url": video_url}
            else:
                # DYNAMIC_TYPE_DRAW, MAJOR_TYPE_DRAW
                return {"kind": "opus", "entry_url": entry_url, "final_url": final_url}
        raise AssertionError(
            f"跟跳后无法归类为 video 或 opus；\nfinal_url: {final_url}；\nentry_url: {entry_url}；\ntext_or_url: {text_or_url}；\n"
            "当前仅识别 www.bilibili.com/video/…、www.bilibili.com/opus/… 与 t.bilibili.com/… 落地页。"
        )

    @staticmethod
    def sanitize_filename(name: str, max_len: int = 80) -> str:
        name = re.sub(r'[\\/:*?"<>|]', "_", (name or "").strip())
        name = re.sub(r"\s+", " ", name).strip(" .")
        if not name:
            name = "untitled"
        return name[:max_len]

    @staticmethod
    def looks_like_captcha_or_risk(response: requests.Response) -> bool:
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
    def extract_initial_state_json(html: str) -> Optional[Dict[str, Any]]:
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

    share_text = """
    https://t.bilibili.com/1202874151861223426/
    """
    result = client.classify_share_link(share_text)
    print(result)


if __name__ == "__main__":
    main()
