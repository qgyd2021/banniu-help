#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from toolbox.dewu.dewu_client import DewuClient


class ShareMediaDownload(DewuClient):
    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def sanitize_filename(name: str, max_len: int = 80) -> str:
        name = re.sub(r'[\\/:*?"<>|]', "_", (name or "").strip())
        name = re.sub(r"\s+", " ", name).strip(" .")
        if not name:
            name = "untitled"
        return name[:max_len]

    @staticmethod
    def get_share_url_by_share_text(text: str) -> str:
        patterns = [
            r"https?://dw4\.co/[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+",
            r"https?://m\.dewu\.com/[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                return m.group(0).rstrip(".,;)")
        raise AssertionError(f"no dewu share url found; text: {text!r}")

    @staticmethod
    def _extract_json_from_next_data(html: str) -> Dict[str, Any]:
        m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html, flags=re.IGNORECASE)
        if not m:
            return {}
        raw = (m.group(1) or "").strip()
        if not raw:
            return {}
        try:
            js = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(js, dict):
            return js
        return {}

    @staticmethod
    def _dedupe_keep_order(urls: List[str]) -> List[str]:
        out: List[str] = []
        seen: set = set()
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    @staticmethod
    def _iter_values_by_keys(obj: Any, target_keys: set) -> List[Any]:
        """递归收集 obj 中命中 key 的值（保留出现顺序）。"""
        out: List[Any] = []

        def _walk(x: Any):
            if isinstance(x, dict):
                for k, v in x.items():
                    if str(k) in target_keys:
                        out.append(v)
                    _walk(v)
            elif isinstance(x, list):
                for item in x:
                    _walk(item)

        _walk(obj)
        return out

    @classmethod
    def _pick_first_non_empty_str_by_keys(cls, obj: Any, keys: List[str]) -> str:
        values = cls._iter_values_by_keys(obj, set(keys))
        for v in values:
            s = str(v or "").strip()
            if s:
                return s
        return ""

    def _parse_content_from_next_data(self, next_data: Dict[str, Any]) -> Dict[str, Any]:
        page_props = ((next_data.get("props") or {}).get("pageProps") or {})
        meta_og_info = page_props.get("metaOGInfo") or {}
        rows = (meta_og_info.get("data") or []) if isinstance(meta_og_info, dict) else []
        if not rows or not isinstance(rows[0], dict):
            return {}
        row0 = rows[0]
        content = row0.get("content") or {}
        if not isinstance(content, dict):
            return {}

        title = (content.get("title") or "").strip()
        desc = (content.get("content") or "").strip()
        trend_id = content.get("contentId")
        cover = content.get("cover") or {}
        media = content.get("media") or {}
        media_list = media.get("list") or []

        image_urls: List[str] = []
        video_urls: List[str] = []
        if isinstance(media_list, list):
            for row in media_list:
                if not isinstance(row, dict):
                    continue
                u = row.get("url")
                t = (row.get("mediaType") or "").lower()
                if not (isinstance(u, str) and u.startswith("http")):
                    continue
                if t == "img":
                    image_urls.append(u)
                elif t in ("video", "mp4"):
                    video_urls.append(u)

        if not image_urls:
            cu = cover.get("url") if isinstance(cover, dict) else None
            if isinstance(cu, str) and cu.startswith("http"):
                image_urls.append(cu)

        image_urls = self._dedupe_keep_order(image_urls)
        video_urls = self._dedupe_keep_order(video_urls)
        image_url_candidates = [[u] for u in image_urls]
        video_url_candidates = [[u] for u in video_urls]
        media_type = "video" if video_urls else ("image" if image_urls else "text")
        if image_urls and video_urls:
            media_type = "mixed"

        # 得物页面结构存在差异：用户信息可能在 content.user / content.author，
        # 也可能嵌在 __NEXT_DATA__ 的其他层级，统一做兜底提取。
        user_info_obj = row0.get("userInfo") if isinstance(row0, dict) else None
        if not isinstance(user_info_obj, dict):
            user_info_obj = {}

        user_obj = {}
        for k in ("user", "author", "publisher"):
            v = content.get(k)
            if isinstance(v, dict) and v:
                user_obj = v
                break

        user_id = self._pick_first_non_empty_str_by_keys(
            user_obj or content,
            keys=["userId", "user_id", "uid", "authorId", "author_id", "publisherId", "publisher_id"],
        )
        if not user_id:
            user_id = self._pick_first_non_empty_str_by_keys(
                next_data,
                keys=["userId", "user_id", "uid", "authorId", "author_id", "publisherId", "publisher_id"],
            )
        user_name = self._pick_first_non_empty_str_by_keys(
            user_info_obj or user_obj or content,
            keys=["userName", "username", "name", "nickName", "nickname"],
        )

        return {
            "trend_id": str(trend_id or ""),
            "user_id": user_id if len(str(user_id)) > 0 else user_name,
            "user_name": user_name,
            "title": title or (str(trend_id) if trend_id else ""),
            "desc": desc,
            "caption": desc,
            "image_urls": image_urls,
            "image_url_candidates": image_url_candidates,
            "video_urls": video_urls,
            "video_url_candidates": video_url_candidates,
            "media_type": media_type,
        }

    def get_post_meta_by_share_url(self, share_url: str) -> Dict[str, Any]:
        response = self.session.get(share_url, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, url: {share_url}"
            )
        final_url = response.url
        html = response.text or ""
        next_data = self._extract_json_from_next_data(html)
        core = self._parse_content_from_next_data(next_data)
        if not core:
            raise AssertionError("parse __NEXT_DATA__ failed; page structure may have changed")

        trend_id = core.get("trend_id") or ""
        if not trend_id:
            m = re.search(r"[?&]trendId=(\d+)", final_url)
            trend_id = m.group(1) if m else ""

        row = {
            "post_type": "dewu_trend",
            "trend_id": trend_id,
            "user_id": core.get("user_id") or "",
            "user_name": core.get("user_name") or "",
            "title": core.get("title", ""),
            "desc": core.get("desc") or "",
            "caption": core.get("caption") or "",
            "media_type": core.get("media_type") or "text",
            "final_url": final_url.split("#", 1)[0],
            "image_urls": core.get("image_urls") or [],
            "image_url_candidates": core.get("image_url_candidates") or [],
            "video_urls": core.get("video_urls") or [],
            "video_url_candidates": core.get("video_url_candidates") or [],
        }
        return row

    def get_post_meta_by_share_text(self, text: str) -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.get_post_meta_by_share_url(share_url)

    def download_file(self, url: str, filename: Path, referer: Optional[str] = None) -> Path:
        filename = Path(filename)
        filename.parent.mkdir(parents=True, exist_ok=True)
        headers = {
            **self.headers,
            "Referer": referer or self.www_host + "/",
        }
        response = self.session.get(url, headers=headers, stream=True, timeout=120)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {url}")
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return filename

    def download_media_by_share_url(
        self,
        share_url: str,
        output_dir: str = "output_dewu_media",
        post_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = post_meta or self.get_post_meta_by_share_url(share_url)
        referer = row.get("final_url") or self.www_host + "/"

        output_dir_path = Path(output_dir)
        key = row.get("trend_id") or "trend"
        title_slug = self.sanitize_filename(row.get("title") or key)
        save_dir = output_dir_path / f"{key}_{title_slug}"
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded_images: List[str] = []
        for idx, image_url in enumerate(row.get("image_urls") or [], start=1):
            ext = ".jpg"
            lower = image_url.split("?", 1)[0].lower()
            if lower.endswith(".png"):
                ext = ".png"
            elif lower.endswith(".webp"):
                ext = ".webp"
            path = save_dir / f"image_{idx:02d}{ext}"
            self.download_file(image_url, path, referer=referer)
            downloaded_images.append(path.as_posix())

        downloaded_videos: List[str] = []
        for idx, video_url in enumerate(row.get("video_urls") or [], start=1):
            path = save_dir / f"video_{idx:02d}.mp4"
            self.download_file(video_url, path, referer=referer)
            downloaded_videos.append(path.as_posix())

        meta = {
            **row,
            "downloaded_images": downloaded_images,
            "downloaded_videos": downloaded_videos,
            "save_dir": save_dir.as_posix(),
        }
        with open(save_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    def download_media_by_share_text(self, text: str, output_dir: str = "output_dewu_media") -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.download_media_by_share_url(share_url=share_url, output_dir=output_dir)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    client = ShareMediaDownload()

    share_text = """
我没有orange为[迈从 Ace 68 V2 有线…]发布了一篇得物评价，https://dw4.co/t/A/1v2jx3B5v点开链接，快来看吧！
    """
    result = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
