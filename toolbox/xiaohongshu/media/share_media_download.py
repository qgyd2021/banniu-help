#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from cacheout import Cache

from toolbox.xiaohongshu.xiaohongshu_client import XiaoHongShuClient

logger = logging.getLogger("toolbox")

cache = Cache(ttl=20)


class ShareMediaDownload(XiaoHongShuClient):
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
            r"https?://xhslink\.com/[A-Za-z0-9/_\-]+",
            r"https?://www\.xiaohongshu\.com/[^\s]+",
            r"https?://www\.rednote\.com/[^\s]+",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                return m.group(0).rstrip(".,;)")
        raise AssertionError(f"no share url found; text: {text}")

    # @cache.memoize(ttl=10)
    # def resolve_share_url(self, share_url: str) -> str:
    #     response = self.session.get(share_url, headers=self.headers, allow_redirects=True, timeout=30)
    #     if response.status_code != 200:
    #         raise AssertionError(f"invalid share_url: {share_url}, status_code: {response.status_code}")
    #     return response.url

    @staticmethod
    def parse_note_id_by_url(url: str) -> str:
        path = urlparse(url).path.strip("/")
        if "/discovery/item/" in url:
            return path.split("/")[-1]
        if "/explore/" in url:
            return path.split("/")[-1]
        return path.split("/")[-1]

    @staticmethod
    def _sanitize_initial_state_json(raw: str) -> str:
        s = re.sub(r"\bundefined\b", "null", raw)
        s = re.sub(r"\bNaN\b", "null", s)
        s = re.sub(r"\bInfinity\b", "null", s)
        return s

    def parse_initial_state(self, html: str) -> Dict[str, Any]:
        needle = "window.__INITIAL_STATE__="
        pos = html.find(needle)
        if pos < 0:
            raise AssertionError("window.__INITIAL_STATE__ not found")
        start = pos + len(needle)
        end = html.find("</script>", start)
        if end < 0:
            raise AssertionError("initial state script end not found")
        raw = html[start:end].strip()
        if not raw:
            raise AssertionError("initial state is empty")
        return json.loads(self._sanitize_initial_state_json(raw))

    @cache.memoize(ttl=10)
    def get_note_by_share_url(self, share_url: str) -> Dict[str, Any]:
        response = self.session.get(share_url, headers=self.headers, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"request failed; share_url: {share_url}, status_code: {response.status_code}")
        final_url = response.url
        note_id = self.parse_note_id_by_url(final_url)
        state = self.parse_initial_state(response.text)
        note_map = ((state.get("note") or {}).get("noteDetailMap") or {})
        detail = note_map.get(note_id) or next(iter(note_map.values()), None)
        if not detail:
            raise AssertionError(f"noteDetailMap empty; final_url: {final_url}")
        note = detail.get("note") or {}
        if not note:
            raise AssertionError(f"note data empty; final_url: {final_url}")
        return {
            "final_url": final_url,
            "note_id": note_id,
            "note": note,
        }

    @staticmethod
    def _extract_image_url_candidates(image: dict) -> List[str]:
        """
        返回图片候选链接，按清晰度优先级排序：
        WB_DFT > WB_ORI > WB_WM > WB_PRV > urlDefault。
        """
        info_list = image.get("infoList") or []
        scene_to_url: Dict[str, str] = {}
        for row in info_list:
            if not isinstance(row, dict):
                continue
            scene = row.get("imageScene")
            url = row.get("url")
            if isinstance(scene, str) and isinstance(url, str) and url.startswith("http"):
                scene_to_url[scene] = url

        candidates: List[str] = []
        for scene in ("WB_DFT", "WB_ORI", "WB_WM", "WB_PRV"):
            if scene_to_url.get(scene):
                candidates.append(scene_to_url[scene])

        url_default = image.get("urlDefault")
        if isinstance(url_default, str) and url_default.startswith("http"):
            candidates.append(url_default)

        return list(dict.fromkeys(candidates))

    def _collect_video_urls(self, obj: Any, path: str = "") -> List[str]:
        result: List[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                child_path = f"{path}.{k}" if path else k
                if isinstance(v, str):
                    lower_path = child_path.lower()
                    if v.startswith("http") and (
                        ".mp4" in v.lower()
                        or "video" in lower_path
                        or "stream" in lower_path
                        or "masterurl" in lower_path
                    ):
                        result.append(v)
                else:
                    result.extend(self._collect_video_urls(v, child_path))
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                result.extend(self._collect_video_urls(item, f"{path}[{idx}]"))
        return result

    def _extract_video_candidate_groups(self, note: dict) -> List[List[str]]:
        groups: List[List[str]] = []
        seen_groups = set()

        # 1) 先取 note.video 主视频结构
        video_obj = note.get("video")
        if isinstance(video_obj, dict):
            candidates = list(dict.fromkeys(self._collect_video_urls(video_obj)))
            if candidates:
                key = tuple(candidates)
                if key not in seen_groups:
                    seen_groups.add(key)
                    groups.append(candidates)

        # 2) 再取 imageList 内可能的 livephoto / video 结构
        for image in note.get("imageList") or []:
            if not isinstance(image, dict):
                continue
            candidates = list(dict.fromkeys(self._collect_video_urls(image)))
            if candidates:
                key = tuple(candidates)
                if key not in seen_groups:
                    seen_groups.add(key)
                    groups.append(candidates)

        # 3) 兜底：整条 note 扫描出的链接补充为单元素分组
        all_candidates = list(dict.fromkeys(self._collect_video_urls(note)))
        existed_urls = {u for group in groups for u in group}
        for url in all_candidates:
            if url not in existed_urls:
                groups.append([url])
                existed_urls.add(url)

        return groups

    def convert_note(self, note: dict, note_id: str, final_url: str) -> Dict[str, Any]:
        title = (note.get("title") or "").strip()
        desc = (note.get("desc") or "").strip()
        tags = [x.get("name") for x in (note.get("tagList") or []) if isinstance(x, dict) and x.get("name")]
        interact_info = note.get("interactInfo") or {}
        user_info = note.get("user") or {}

        image_urls: List[str] = []
        image_url_candidates: List[List[str]] = []
        for image in note.get("imageList") or []:
            if not isinstance(image, dict):
                continue
            candidates = self._extract_image_url_candidates(image)
            if candidates:
                image_url_candidates.append(candidates)
                image_urls.append(candidates[0])

        video_url_candidates = self._extract_video_candidate_groups(note)
        video_urls = [group[0] for group in video_url_candidates if group]

        media_type = "video" if video_urls else "image"
        if video_urls and image_urls:
            media_type = "mixed"

        row = {
            "note_id": note_id,
            "title": title,
            "desc": desc,
            "tags": tags,
            "user": {
                "user_id": user_info.get("userId"),
                "nickname": user_info.get("nickname"),
            },
            "interact_info": {
                "liked_count": interact_info.get("likedCount"),
                "collected_count": interact_info.get("collectedCount"),
                "comment_count": interact_info.get("commentCount"),
                "share_count": interact_info.get("shareCount"),
            },
            "media_type": media_type,
            "final_url": final_url,
            "image_urls": image_urls,
            "image_url_candidates": image_url_candidates,
            "video_urls": video_urls,
            "video_url_candidates": video_url_candidates,
        }
        return row

    def get_post_meta_by_share_url(self, share_url: str) -> Dict[str, Any]:
        """
        仅获取贴子元信息，不下载媒体文件。
        """
        note_data = self.get_note_by_share_url(share_url)
        return self.convert_note(
            note=note_data["note"],
            note_id=note_data["note_id"],
            final_url=note_data["final_url"],
        )

    def get_post_meta_by_share_text(self, text: str) -> Dict[str, Any]:
        """
        从分享文本提取链接后，仅获取贴子元信息，不下载媒体文件。
        """
        share_url = self.get_share_url_by_share_text(text)
        return self.get_post_meta_by_share_url(share_url)

    def download_file(self, url: str, filename: Path) -> Path:
        filename = Path(filename)
        filename.parent.mkdir(parents=True, exist_ok=True)
        response = self._session.get(url, headers=self.headers, stream=True, timeout=60)
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
        output_dir: str = "output_xhs_media",
        post_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = post_meta or self.get_post_meta_by_share_url(share_url)

        output_dir_path = Path(output_dir)
        title_slug = self.sanitize_filename(row["title"] or row["note_id"])
        save_dir = output_dir_path / f"{row['note_id']}_{title_slug}"
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded_images: List[str] = []
        for idx, image_url in enumerate(row["image_urls"], start=1):
            ext = ".jpg"
            if ".png" in image_url.lower():
                ext = ".png"
            filename = save_dir / f"image_{idx:02d}{ext}"
            self.download_file(image_url, filename)
            downloaded_images.append(filename.as_posix())

        downloaded_videos: List[str] = []
        for idx, video_url in enumerate(row["video_urls"], start=1):
            candidate_group = []
            if idx - 1 < len(row.get("video_url_candidates") or []):
                candidate_group = row["video_url_candidates"][idx - 1] or []
            pick_url = candidate_group[0] if candidate_group else video_url
            filename = save_dir / f"video_{idx:02d}.mp4"
            self.download_file(pick_url, filename)
            downloaded_videos.append(filename.as_posix())

        meta_path = save_dir / "meta.json"
        meta = {
            **row,
            "downloaded_images": downloaded_images,
            "downloaded_videos": downloaded_videos,
            "save_dir": save_dir.as_posix(),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return meta

    def download_media_by_share_text(self, text: str, output_dir: str = "output_xhs_media") -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.download_media_by_share_url(share_url=share_url, output_dir=output_dir)


def main():
    client = ShareMediaDownload()

    text = """
http://xhslink.com/o/8ekDPRNcz63
"""
    # 默认只获取元信息，不下载媒体
    result = client.get_post_meta_by_share_text(text=text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 需要下载时，调用下面方法
    # result = client.download_media_by_share_text(text=text, output_dir="output_xhs_media")
    # print(json.dumps(result, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
