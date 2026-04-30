#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
从快手分享短链 / 落地页解析作品信息并下载图片或视频（风格对齐 toolbox/xiaohongshu/media/share_media_download.py）。

分享页 HTML 内嵌 ``photo`` / ``atlas`` JSON，通过 ``json.JSONDecoder.raw_decode`` 抽取；
``shareObjectId`` 与 ``photoId`` 用于在多个 ``"photo":{`` 片段中定位正确对象。

说明：桌面浏览器 UA 常把短链重定向到 ``www.kuaishou.com/short-video/…``（Apollo 壳页，无内嵌 ``photo`` JSON），
因此请求分享页时使用 **移动端 UA**，以落到 ``…/fw/photo/…`` H5 页（与 App 分享一致）。
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse, unquote

from toolbox.kuaishou.kuaishou_client import KuaishouClient


class ShareMediaDownload(KuaishouClient):
    """拉取分享落地页时使用的移动端 UA（与 iPhone 打开分享链行为一致）。"""
    mobile_share_headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
        ),
    }

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
            r"https?://v\.kuaishou\.com/[A-Za-z0-9_\-]+",
            r"https?://(?:www\.)?kuaishou\.com/[^\s]+",
            r"https?://v\.m\.chenzhongtech\.com/[^\s]+",
            r"https?://m\.gifshow\.com/[^\s]+",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                return m.group(0).rstrip(".,;)")
        raise AssertionError(f"no kuaishou share url found; text: {text!r}")

    @staticmethod
    def _parse_landing_ids(final_url: str) -> Dict[str, Optional[str]]:
        parsed = urlparse(final_url)
        parts = [p for p in (parsed.path or "").strip("/").split("/") if p]
        photo_sid: Optional[str] = None
        if len(parts) >= 2 and parts[-2] == "photo":
            photo_sid = parts[-1].split("?")[0] or None
        elif len(parts) >= 2 and parts[-2] == "short-video":
            photo_sid = parts[-1].split("?")[0] or None
        qs = parse_qs(parsed.query)
        share_oid = (qs.get("shareObjectId") or [None])[0]
        if not photo_sid:
            pid_q = (qs.get("photoId") or [None])[0]
            if pid_q:
                photo_sid = pid_q
        return {"photo_sid": photo_sid, "share_object_id": share_oid}

    @classmethod
    def _resource_bucket_key(cls, url: str) -> str:
        """
        同一封面/视频在多个 CDN 上 URL 不同；快手常用 query ``clientCacheKey`` 标识同一文件。
        """
        if not isinstance(url, str) or not url.startswith("http"):
            return url or ""
        try:
            p = urlparse(url)
            qs = parse_qs(p.query, keep_blank_values=True)
            cck = (qs.get("clientCacheKey") or [None])[0]
            if isinstance(cck, str) and cck.strip():
                return unquote(cck.strip())
            name = (p.path or "").rsplit("/", 1)[-1]
            return name or url
        except Exception:
            return url

    @staticmethod
    def _cdn_to_origin(cdn: str) -> str:
        cdn = (cdn or "").strip()
        if not cdn:
            return ""
        if cdn.startswith("http://") or cdn.startswith("https://"):
            return cdn.rstrip("/")
        return "https://" + cdn.rstrip("/")

    @classmethod
    def _pick_photo_dict(cls, html: str, ids: Dict[str, Optional[str]]) -> Tuple[Dict[str, Any], int]:
        dec = json.JSONDecoder()
        share_oid = ids.get("share_object_id")
        photo_sid = ids.get("photo_sid")
        matches: List[Tuple[int, Dict[str, Any]]] = []
        for m in re.finditer(r'"photo"\s*:\s*\{', html):
            start = m.start() + m.group(0).rfind("{")
            try:
                obj, _ = dec.raw_decode(html[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                matches.append((m.start(), obj))
        if not matches:
            raise AssertionError("页面中未找到 photo JSON 片段，可能结构已变更或命中风控页。")

        if share_oid:
            for pos, obj in matches:
                if str(obj.get("photoId") or "") == share_oid:
                    return obj, pos
        if photo_sid:
            for pos, obj in matches:
                blob = json.dumps(obj, ensure_ascii=False)
                if photo_sid in blob:
                    return obj, pos
        return matches[-1][1], matches[-1][0]

    @classmethod
    def _pick_atlas_dict(cls, html: str, before_index: int) -> Dict[str, Any]:
        dec = json.JSONDecoder()
        last: Dict[str, Any] = {}
        for m in re.finditer(r'"atlas"\s*:\s*\{', html):
            if m.start() >= before_index:
                break
            start = m.start() + m.group(0).rfind("{")
            try:
                obj, _ = dec.raw_decode(html[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                last = obj
        return last

    @classmethod
    def _urls_from_atlas(cls, atlas: Dict[str, Any]) -> Tuple[List[str], List[List[str]]]:
        cdn_list = [cls._cdn_to_origin(x) for x in (atlas.get("cdn") or []) if x]
        if not cdn_list:
            cdn_list = ["https://p2.a.yximgs.com"]
        rel_list = atlas.get("list") or []
        candidates: List[List[str]] = []
        for rel in rel_list:
            if not isinstance(rel, str) or not rel.startswith("/"):
                continue
            group: List[str] = []
            for origin in cdn_list:
                group.append(origin + rel)
            group = list(dict.fromkeys(group))
            if group:
                candidates.append(group)
        urls = [g[0] for g in candidates]
        return urls, candidates

    @classmethod
    def _urls_from_cover_urls_grouped(cls, photo: Dict[str, Any]) -> Tuple[List[str], List[List[str]]]:
        """多条 coverUrls 常为同一封面的 CDN 镜像，按资源键合并为一条候选组。"""
        rows = photo.get("coverUrls") or []
        buckets: Dict[str, List[str]] = {}
        order: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            u = row.get("url")
            if not (isinstance(u, str) and u.startswith("http")):
                continue
            k = cls._resource_bucket_key(u)
            if k not in buckets:
                order.append(k)
                buckets[k] = []
            if u not in buckets[k]:
                buckets[k].append(u)
        candidates = [buckets[k] for k in order if buckets.get(k)]
        urls = [c[0] for c in candidates if c]
        return urls, candidates

    @classmethod
    def _video_groups_from_photo(cls, photo: Dict[str, Any]) -> List[List[str]]:
        """
        每个 mainMvUrls 元素内 ``url`` 与 ``url_list`` 常指向同一视频，合并为一组候选；
        多个元素若 clientCacheKey 相同则只保留一条逻辑视频。
        """
        raw = photo.get("mainMvUrls")
        if not isinstance(raw, list):
            return []
        groups: List[List[str]] = []
        seen_bucket: set = set()
        for item in raw:
            urls_in_item: List[str] = []
            if isinstance(item, str) and item.startswith("http"):
                urls_in_item.append(item)
            elif isinstance(item, dict):
                u = item.get("url") or item.get("src")
                if isinstance(u, str) and u.startswith("http"):
                    urls_in_item.append(u)
                inner = item.get("url_list") or item.get("urls")
                if isinstance(inner, list):
                    for x in inner:
                        if isinstance(x, str) and x.startswith("http"):
                            urls_in_item.append(x)
            urls_in_item = list(dict.fromkeys(urls_in_item))
            if not urls_in_item:
                continue
            key = cls._resource_bucket_key(urls_in_item[0])
            if key in seen_bucket:
                continue
            seen_bucket.add(key)
            groups.append(urls_in_item)
        return groups

    @classmethod
    def _atlas_music_urls(cls, atlas: Dict[str, Any]) -> List[str]:
        music = atlas.get("music")
        if not isinstance(music, str) or not music.startswith("/"):
            return []
        cdns: List[str] = []
        for row in atlas.get("musicCdnList") or []:
            if isinstance(row, dict):
                c = row.get("cdn")
                if isinstance(c, str) and c.strip():
                    cdns.append(cls._cdn_to_origin(c))
        if not cdns:
            cdns = ["https://p2.a.yximgs.com"]
        built = [origin + music for origin in cdns]
        return list(dict.fromkeys(built))

    def fetch_photo_by_share_url(self, share_url: str) -> Dict[str, Any]:
        headers = {**self.headers, **self.mobile_share_headers}
        response = self.session.get(share_url, headers=headers, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(
                f"请求分享页失败; url: {share_url}, status_code: {response.status_code}"
            )
        final_url = response.url
        html = response.text or ""
        ids = self._parse_landing_ids(final_url)
        photo, photo_pos = self._pick_photo_dict(html, ids)
        atlas = self._pick_atlas_dict(html, photo_pos)
        return {
            "final_url": final_url,
            "landing_ids": ids,
            "photo": photo,
            "atlas": atlas,
            "html_len": len(html),
        }

    def convert_photo_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        final_url = payload["final_url"]
        photo = payload["photo"]
        atlas = payload.get("atlas") or {}

        caption = (photo.get("caption") or "").strip()
        title = caption.split("\n", 1)[0].strip()[:120] if caption else ""
        if not title:
            title = str(photo.get("photoId") or payload["landing_ids"].get("photo_sid") or "kuaishou")

        atlas_list = [x for x in (atlas.get("list") or []) if isinstance(x, str) and x.startswith("/")]
        video_url_candidates = self._video_groups_from_photo(photo)
        video_urls = [g[0] for g in video_url_candidates if g]

        image_urls: List[str] = []
        image_url_candidates: List[List[str]] = []

        if atlas_list:
            image_urls, image_url_candidates = self._urls_from_atlas(atlas)
        elif not video_urls:
            image_urls, image_url_candidates = self._urls_from_cover_urls_grouped(photo)

        if video_urls and image_urls:
            media_type = "mixed"
        elif video_urls:
            media_type = "video"
        else:
            media_type = "image"

        audio_urls = self._atlas_music_urls(atlas)

        return {
            "post_type": "kuaishou_photo",
            "photo_id": str(photo.get("photoId") or ""),
            "photo_sid": payload["landing_ids"].get("photo_sid") or "",
            "title": title,
            "caption": caption,
            "media_type": media_type,
            "final_url": final_url,
            "image_urls": image_urls,
            "image_url_candidates": image_url_candidates,
            "video_urls": video_urls,
            "video_url_candidates": video_url_candidates,
            "audio_urls": audio_urls,
            "user": {
                "user_id": photo.get("userId"),
                "nickname": (photo.get("userName") or "").strip(),
            },
            "interact_info": {
                "like_count": photo.get("likeCount"),
                "comment_count": photo.get("commentCount"),
                "forward_count": photo.get("forwardCount"),
                "view_count": photo.get("viewCount"),
            },
        }

    def get_post_meta_by_share_url(self, share_url: str) -> Dict[str, Any]:
        payload = self.fetch_photo_by_share_url(share_url)
        return self.convert_photo_payload(payload)

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
            raise AssertionError(f"下载失败; status_code: {response.status_code}, url: {url}")
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return filename

    def download_media_by_share_url(
        self,
        share_url: str,
        output_dir: str = "output_kuaishou_media",
        post_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = post_meta or self.get_post_meta_by_share_url(share_url)
        referer = row.get("final_url") or self.www_host + "/"

        output_dir_path = Path(output_dir)
        key = row.get("photo_sid") or row.get("photo_id") or "photo"
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
            elif lower.endswith(".gif"):
                ext = ".gif"
            path = save_dir / f"image_{idx:02d}{ext}"
            self.download_file(image_url, path, referer=referer)
            downloaded_images.append(path.as_posix())

        downloaded_videos: List[str] = []
        for idx, video_url in enumerate(row.get("video_urls") or [], start=1):
            group: List[str] = []
            cands = row.get("video_url_candidates") or []
            if idx - 1 < len(cands):
                group = cands[idx - 1] or []
            pick = group[0] if group else video_url
            path = save_dir / f"video_{idx:02d}.mp4"
            self.download_file(pick, path, referer=referer)
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

    def download_media_by_share_text(self, text: str, output_dir: str = "output_kuaishou_media") -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.download_media_by_share_url(share_url=share_url, output_dir=output_dir)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    client = ShareMediaDownload()
    text = """
https://v.kuaishou.com/J7gprA8p

"""
    result = client.get_post_meta_by_share_text(text=text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 需要落盘时取消注释
    # out = client.download_media_by_share_text(text=text, output_dir="output_kuaishou_media")
    # print("save_dir:", out.get("save_dir"))


if __name__ == "__main__":
    main()
