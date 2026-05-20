#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import requests

logger = logging.getLogger("toolbox")


class ShareMediaDownload(object):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    mobile_headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
    }

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.trust_env = False

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
            r"https://v\.douyin\.com/[A-Za-z0-9_\-]+/",
            r"https?://www\.douyin\.com/[^\s]+",
            r"https?://www\.iesdouyin\.com/[^\s]+",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is not None:
                return match.group(0).rstrip(".,;)")
        raise AssertionError(f"no share url found; text: {text}")

    @staticmethod
    def parse_aweme_id_by_url(url: str) -> str:
        match = re.search(r"/(?:video|note)/(\d+)", url)
        if match is None:
            raise AssertionError(f"cannot parse aweme_id from url: {url}")
        return match.group(1)

    @staticmethod
    def parse_aweme_type_by_url(url: str) -> str:
        if re.search(r"/note/\d+", url):
            return "note"
        if re.search(r"/video/\d+", url):
            return "video"
        return "video"

    def get_router_data_json_by_share_url(self, share_url: str) -> Dict[str, Any]:
        redirect_response = self.session.get(
            share_url,
            headers=self.headers,
            allow_redirects=True,
            timeout=30,
        )
        if redirect_response.status_code != 200:
            raise AssertionError(
                f"invalid share_url: {share_url}, status_code: {redirect_response.status_code}"
            )

        final_url = redirect_response.url
        aweme_id = self.parse_aweme_id_by_url(final_url)
        aweme_type = self.parse_aweme_type_by_url(final_url)
        page_url = f"https://www.iesdouyin.com/share/{aweme_type}/{aweme_id}"

        page_response = self.session.get(
            page_url,
            headers=self.mobile_headers,
            allow_redirects=True,
            timeout=30,
        )
        if page_response.status_code != 200:
            raise AssertionError(
                f"request failed; page_url: {page_url}, status_code: {page_response.status_code}"
            )

        pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
        match = pattern.search(page_response.text)
        if match is None:
            raise AssertionError("parse _ROUTER_DATA failed")

        js = json.loads(match.group(1).strip())
        return {
            "router_data": js,
            "aweme_id": aweme_id,
            "aweme_type_url": aweme_type,
            "final_url": final_url,
            "page_url": page_url,
        }

    @staticmethod
    def _extract_aweme(router_data: Dict[str, Any]) -> Dict[str, Any]:
        loader_data = router_data.get("loaderData") or {}
        for _, value in loader_data.items():
            if not isinstance(value, dict):
                continue
            video_info_res = value.get("videoInfoRes") or {}
            item_list = video_info_res.get("item_list") or []
            if item_list and isinstance(item_list[0], dict):
                return item_list[0]
        raise AssertionError("aweme item not found in _ROUTER_DATA")

    @staticmethod
    def _safe_url_list(node: Any) -> List[str]:
        if not isinstance(node, list):
            return []
        return [u for u in node if isinstance(u, str) and u.startswith("http")]

    def convert_aweme(self, aweme: Dict[str, Any], aweme_id: str, final_url: str) -> Dict[str, Any]:
        desc = (aweme.get("desc") or "").strip()
        title = desc or aweme_id
        aweme_type = aweme.get("aweme_type")

        image_urls: List[str] = []
        image_url_candidates: List[List[str]] = []
        image_items = [x for x in (aweme.get("images") or []) if isinstance(x, dict)]
        image_items.extend([x for x in (aweme.get("image_infos") or []) if isinstance(x, dict)])
        for image in image_items:
            urls = self._safe_url_list(image.get("url_list"))
            if not urls:
                continue
            group = list(dict.fromkeys(urls))
            image_url_candidates.append(group)
            image_urls.append(group[0])

        video_urls: List[str] = []
        video_url_candidates: List[List[str]] = []
        video = aweme.get("video") or {}
        play_addr = video.get("play_addr") or {}
        urls = self._safe_url_list(play_addr.get("url_list"))
        # 图文笔记（常见 2/68）经常带一个兜底 video 字段，这不是正文视频，避免误判为 video。
        if urls and aweme_type not in (2, 68):
            group = []
            for url in urls:
                group.append(url.replace("playwm", "play"))
            group = list(dict.fromkeys(group))
            video_url_candidates.append(group)
            video_urls.append(group[0])

        media_type = "video" if video_urls else "image"
        if image_urls and not video_urls:
            media_type = "image"
        statistics = aweme.get("statistics") or {}
        author = aweme.get("author") or {}
        return {
            "aweme_id": aweme_id,
            "title": title,
            "desc": desc,
            "media_type": media_type,
            "final_url": final_url,
            "image_urls": image_urls,
            "image_url_candidates": image_url_candidates,
            "video_urls": video_urls,
            "video_url_candidates": video_url_candidates,
            "author": {
                "sec_uid": author.get("sec_uid"),
                "uid": author.get("uid"),
                "nickname": author.get("nickname"),
            },
            "interact_info": {
                "digg_count": statistics.get("digg_count"),
                "comment_count": statistics.get("comment_count"),
                "collect_count": statistics.get("collect_count"),
                "share_count": statistics.get("share_count"),
            },
        }

    def get_post_meta_by_share_url(self, share_url: str) -> Dict[str, Any]:
        data = self.get_router_data_json_by_share_url(share_url)
        aweme = self._extract_aweme(data["router_data"])
        return self.convert_aweme(
            aweme=aweme,
            aweme_id=data["aweme_id"],
            final_url=data["final_url"],
        )

    def get_post_meta_by_share_text(self, text: str) -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.get_post_meta_by_share_url(share_url)

    def download_file(self, url: str, filename: Path, headers: Dict[str, str]) -> Path:
        filename = Path(filename)
        filename.parent.mkdir(parents=True, exist_ok=True)
        response = self.session.get(url, headers=headers, stream=True, timeout=60)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {url}")
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return filename

    def download_media_by_share_url(self, share_url: str, output_dir: str = "output_douyin_media") -> Dict[str, Any]:
        post_meta = self.get_post_meta_by_share_url(share_url)

        output_dir_path = Path(output_dir)
        title_slug = self.sanitize_filename(post_meta["title"])
        save_dir = output_dir_path / f"{post_meta['aweme_id']}_{title_slug}"
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded_images = []
        for index, image_url in enumerate(post_meta["image_urls"], start=1):
            filename = save_dir / f"image_{index:02d}.jpg"
            self.download_file(image_url, filename, headers=self.mobile_headers)
            downloaded_images.append(filename.as_posix())

        downloaded_videos = []
        for index, video_url in enumerate(post_meta["video_urls"], start=1):
            filename = save_dir / f"video_{index:02d}.mp4"
            self.download_file(video_url, filename, headers=self.mobile_headers)
            downloaded_videos.append(filename.as_posix())

        result = {
            **post_meta,
            "downloaded_images": downloaded_images,
            "downloaded_videos": downloaded_videos,
            "save_dir": save_dir.as_posix(),
        }
        with open(save_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def download_media_by_share_text(self, text: str, output_dir: str = "output_douyin_media") -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.download_media_by_share_url(share_url=share_url, output_dir=output_dir)


def main():
    client = ShareMediaDownload()

    share_text = """
7.12 复制打开抖音，看看【H的图文作品】# 迈从 # 迈从A7V2 新尝试，大手玩家大喜  https://v.douyin.com/OJsMk7lQIJM/ Bgo:/ :5pm d@A.GI 05/20
"""
    post_meta = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(post_meta, ensure_ascii=False, indent=2))

    # result = client.download_media_by_share_text(text, output_dir="output_douyin_media")
    # print(json.dumps(result, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
