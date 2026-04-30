#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import logging
from pathlib import Path
import random
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from cacheout import Cache

from toolbox.weibo.weibo_client import WeiboClient

logger = logging.getLogger("toolbox")

cache = Cache(ttl=20)


class ShareMediaDownload(WeiboClient):
    def __init__(self):
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
            r"https?://weibo\.com/[^\s]+",
            r"https?://m\.weibo\.cn/[^\s]+",
            r"https?://t\.cn/[A-Za-z0-9]+",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                return m.group(0).rstrip(".,;)")
        raise AssertionError(f"no share url found; text: {text}")

    @staticmethod
    def parse_status_id_by_url(url: str) -> Optional[str]:
        path = urlparse(url).path.strip("/")
        parts = [x for x in path.split("/") if x]
        # 常见路径：/7417459023/5289790880614819 或 /detail/5289790880614819
        for part in reversed(parts):
            if re.fullmatch(r"\d{10,}", part):
                return part
        return None

    @staticmethod
    def parse_render_data(html: str) -> Dict[str, Any]:
        marker = "render_data = "
        start = html.find(marker)
        if start < 0:
            raise AssertionError("render_data marker not found")
        start += len(marker)
        end = html.find("][0] || {};", start)
        if end < 0:
            raise AssertionError("render_data tail not found")
        arr_text = html[start:end + 1]
        arr = json.loads(arr_text)
        if not arr or not isinstance(arr[0], dict):
            raise AssertionError("render_data array invalid")
        return arr[0]

    @staticmethod
    def _strip_html(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _extract_video_url_candidates(status: dict) -> List[str]:
        """
        提取状态级（非 pics 级）视频候选。
        """
        candidates: List[str] = []

        def add_url(value: Any):
            if isinstance(value, str) and value.startswith("http"):
                if any(ext in value.lower() for ext in (".mp4", ".m3u8")) or any(
                    key in value.lower() for key in ("stream", "play", "video", "mp4")
                ):
                    candidates.append(value)

        page_info = status.get("page_info") or {}
        media_info = page_info.get("media_info") or {}

        for key in ("stream_url_hd", "stream_url", "mp4_hd_url", "mp4_sd_url"):
            add_url(media_info.get(key))

        # page_info.urls 常见于部分微博视频结构
        urls_dict = page_info.get("urls") or {}
        if isinstance(urls_dict, dict):
            for _, value in urls_dict.items():
                add_url(value)

        playback_list = media_info.get("playback_list") or []
        for row in playback_list:
            if not isinstance(row, dict):
                continue
            play_info = row.get("play_info") or {}
            if not isinstance(play_info, dict):
                continue
            add_url(play_info.get("url"))

        # mix_media_info: 图文视频混排场景
        mix_media_info = status.get("mix_media_info") or {}
        if isinstance(mix_media_info, dict):
            for item in mix_media_info.get("items") or []:
                if not isinstance(item, dict):
                    continue
                data = item.get("data") or {}
                if not isinstance(data, dict):
                    continue
                media = data.get("media_info") or data.get("page_info") or data
                if isinstance(media, dict):
                    for key in ("stream_url_hd", "stream_url", "mp4_hd_url", "mp4_sd_url"):
                        add_url(media.get(key))
                    playback = media.get("playback_list") or []
                    for p in playback:
                        if isinstance(p, dict):
                            add_url((p.get("play_info") or {}).get("url"))

        # 兜底：递归扫描，按字段名和内容关键词捕获视频链接
        def walk(obj: Any, path: str = ""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    p = f"{path}.{k}" if path else k
                    if isinstance(v, str):
                        lower_p = p.lower()
                        if any(x in lower_p for x in ("video", "stream", "play", "mp4")):
                            add_url(v)
                    else:
                        walk(v, p)
            elif isinstance(obj, list):
                for idx, it in enumerate(obj):
                    walk(it, f"{path}[{idx}]")

        walk(status)

        return list(dict.fromkeys(candidates))

    @staticmethod
    def _extract_pic_video_candidates(pic: dict) -> List[str]:
        """
        从图片结构中提取视频候选（如 livephoto / videoSrc）。
        """
        result: List[str] = []
        for key in ("videoSrc", "video_src"):
            value = pic.get(key)
            if isinstance(value, str) and value.startswith("http"):
                result.append(value)
        return list(dict.fromkeys(result))

    @staticmethod
    def _extract_image_url_candidates(pic: dict) -> List[str]:
        candidates: List[str] = []
        large = (pic.get("large") or {}).get("url")
        if isinstance(large, str) and large.startswith("http"):
            candidates.append(large)

        direct = pic.get("url")
        if isinstance(direct, str) and direct.startswith("http"):
            candidates.append(direct)

        for key in ("mw2000", "bmiddle", "thumbnail"):
            value = (pic.get(key) or {}).get("url")
            if isinstance(value, str) and value.startswith("http"):
                candidates.append(value)
        return list(dict.fromkeys(candidates))

    @cache.memoize(ttl=10)
    def get_status_by_share_url(self, share_url: str) -> Dict[str, Any]:
        # 先从原始链接解析一次 id（部分场景会直接跳 passport）
        status_id = self.parse_status_id_by_url(share_url)

        # 再尝试跳转拿标准链接
        response = self.session.get(share_url, headers=self.headers, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"request failed; share_url: {share_url}, status_code: {response.status_code}")
        final_url = response.url
        status_id = status_id or self.parse_status_id_by_url(final_url)
        if not status_id and "passport.weibo.com/visitor/visitor" in final_url:
            qs = parse_qs(urlparse(final_url).query)
            origin_url = unquote((qs.get("url") or [""])[0])
            status_id = self.parse_status_id_by_url(origin_url)
        if not status_id:
            raise AssertionError(f"cannot parse status_id from url: {final_url}")

        detail_url = f"https://m.weibo.cn/detail/{status_id}"
        self.login_as_visitor(return_url=detail_url)
        detail_resp = self.session.get(detail_url, headers=self.headers, allow_redirects=True, timeout=30)
        if detail_resp.status_code != 200:
            raise AssertionError(f"detail request failed; status_code: {detail_resp.status_code}")

        render_data = self.parse_render_data(detail_resp.text)
        status = render_data.get("status") or {}
        if not status:
            raise AssertionError(f"status not found; detail_url: {detail_url}")
        return {
            "status": status,
            "status_id": status_id,
            "final_url": final_url,
            "detail_url": detail_url,
        }

    def convert_status(self, status: dict, status_id: str, final_url: str) -> Dict[str, Any]:
        text = self._strip_html(status.get("text") or "")
        title = self._strip_html(status.get("status_title") or "") or text.split("\n", 1)[0]
        user = status.get("user") or {}

        pics = status.get("pics") or []
        image_url_candidates: List[List[str]] = []
        image_urls: List[str] = []
        video_candidate_groups: List[List[str]] = []
        for pic in pics:
            if not isinstance(pic, dict):
                continue
            pic_video_group = self._extract_pic_video_candidates(pic)
            if pic_video_group:
                video_candidate_groups.append(pic_video_group)
            candidates = self._extract_image_url_candidates(pic)
            if candidates:
                image_url_candidates.append(candidates)
                image_urls.append(candidates[0])

        # 状态级候选通常缺少“按视频分组”的语义，作为额外单元素分组补充
        extra_video_candidates = self._extract_video_url_candidates(status)
        existed = {u for group in video_candidate_groups for u in group}
        for url in extra_video_candidates:
            if url not in existed:
                video_candidate_groups.append([url])
                existed.add(url)

        # 每个视频取候选组里的第一条作为默认下载链接
        video_urls = [group[0] for group in video_candidate_groups if group]

        media_type = "video" if video_urls else "image"
        if video_urls and image_urls:
            media_type = "mixed"
            # 当视频数量 >= 图片数量时，通常这些图片是视频封面，按视频贴处理
            if len(video_urls) >= len(image_urls):
                media_type = "video"
                image_urls = []
                image_url_candidates = []

        return {
            "status_id": status_id,
            "title": title,
            "text": text,
            "final_url": final_url,
            "media_type": media_type,
            "image_urls": image_urls,
            "image_url_candidates": image_url_candidates,
            "video_urls": video_urls,
            # 每个视频对应一个候选列表，避免多个视频候选混在一起
            "video_url_candidates": video_candidate_groups,
            "user": {
                "id": user.get("id"),
                "screen_name": user.get("screen_name"),
            },
            "interact_info": {
                "attitudes_count": status.get("attitudes_count"),
                "comments_count": status.get("comments_count"),
                "reposts_count": status.get("reposts_count"),
            },
            "created_at": status.get("created_at"),
            "source": self._strip_html(status.get("source") or ""),
        }

    def get_post_meta_by_share_url(self, share_url: str) -> Dict[str, Any]:
        data = self.get_status_by_share_url(share_url)
        return self.convert_status(
            status=data["status"],
            status_id=data["status_id"],
            final_url=data["final_url"],
        )

    def get_post_meta_by_share_text(self, text: str) -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.get_post_meta_by_share_url(share_url)

    def download_file(self, url: str, filename: Path, referer: str = "https://weibo.com/") -> Path:
        filename = Path(filename)
        filename.parent.mkdir(parents=True, exist_ok=True)
        headers = {
            **self.headers,
            "Referer": referer,
        }
        response = self._session.get(url, headers=headers, stream=True, timeout=60)
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
        output_dir: str = "output_weibo_media",
        post_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = post_meta or self.get_post_meta_by_share_url(share_url)

        output_dir_path = Path(output_dir)
        title_slug = self.sanitize_filename(row["title"] or row["status_id"])
        save_dir = output_dir_path / f"{row['status_id']}_{title_slug}"
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded_images: List[str] = []
        for idx, image_url in enumerate(row["image_urls"], start=1):
            filename = save_dir / f"image_{idx:02d}.jpg"
            self.download_file(image_url, filename, referer="https://weibo.com/")
            downloaded_images.append(filename.as_posix())

        downloaded_videos: List[str] = []
        for idx, video_url in enumerate(row["video_urls"], start=1):
            filename = save_dir / f"video_{idx:02d}.mp4"
            self.download_file(video_url, filename, referer="https://weibo.com/")
            downloaded_videos.append(filename.as_posix())

        meta = {
            **row,
            "downloaded_images": downloaded_images,
            "downloaded_videos": downloaded_videos,
            "save_dir": save_dir.as_posix(),
        }
        with open(save_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    def download_media_by_share_text(self, text: str, output_dir: str = "output_weibo_media") -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.download_media_by_share_url(share_url=share_url, output_dir=output_dir)


def main():
    client = ShareMediaDownload()
    share_url = "https://weibo.com/7281031190/5289820563702404"

    result = client.get_post_meta_by_share_url(share_url=share_url)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # result = client.download_media_by_share_url(share_url=share_url, output_dir="output_weibo_media")
    # print(json.dumps(result, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
