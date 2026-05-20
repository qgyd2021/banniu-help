#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
从分享文案或链接解析 B 站稿件元信息，并可选下载视频（分 P 各一条）与封面。

参考：
- toolbox/douyin/media/share_media_download.py（结构与对外方法）
- toolbox/bilibili/bilibili_client.py（UA / Referer 习惯）
- toolbox/bilibili/media/share_download_base.py（基类 BilibiliShareDownloadBase）
- 公开接口：x/web-interface/view、x/player/playurl（无需登录，可能被风控）
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from toolbox.bilibili.media.share_download_base import BilibiliShareDownloadBase


class ShareVideoDownload(BilibiliShareDownloadBase):
    @staticmethod
    def get_share_url_by_share_text(text: str) -> str:
        patterns = [
            r"https?://b23\.tv/[A-Za-z0-9]+(?:\?[^\s]*)?",
            r"https?://(?:www\.)?bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)(?:/|\?[^\s]*)?",
            r"https?://m\.bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)(?:/|\?[^\s]*)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is not None:
                return match.group(0).rstrip(".,;)")
        raise AssertionError(f"no bilibili share url found; text: {text}")

    def resolve_video_page_url(self, url: str) -> str:
        response = self.session.get(
            url,
            allow_redirects=True,
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(f"invalid url: {url}, status_code: {response.status_code}")
        final_url = response.url
        if not re.search(r"bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)", final_url, re.I):
            raise AssertionError(
                f"resolved url is not a video page: {final_url}; "
                "目前仅支持稿件视频页（含 b23.tv 跳转）。"
            )
        return final_url

    @staticmethod
    def parse_bvid_or_aid_from_url(url: str) -> Dict[str, Optional[str]]:
        match_bv = re.search(r"(BV[a-zA-Z0-9]{10})", url, flags=re.IGNORECASE)
        if match_bv:
            return {"bvid": match_bv.group(1), "aid": None}
        match_av = re.search(r"av(\d+)", url, flags=re.IGNORECASE)
        if match_av:
            return {"bvid": None, "aid": match_av.group(1)}
        raise AssertionError(f"cannot parse bvid or aid from url: {url}")

    @staticmethod
    def canonical_video_page_url(bvid: Optional[str], aid: Any) -> str:
        if bvid:
            return f"https://www.bilibili.com/video/{bvid}/"
        return f"https://www.bilibili.com/video/av{aid}/"

    def get_view(self, bvid: Optional[str], aid: Optional[str]) -> Dict[str, Any]:
        params: Dict[str, str] = {}
        if bvid:
            params["bvid"] = bvid
        elif aid:
            params["aid"] = aid
        else:
            raise AssertionError("bvid and aid are both empty")
        response = self.session.get(
            "https://api.bilibili.com/x/web-interface/view",
            params=params,
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(f"view failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        if js.get("code") != 0:
            raise AssertionError(f"view api error; code: {js.get('code')}, message: {js.get('message')}")
        return js["data"]

    def get_playurl_for_cid(
        self,
        bvid: Optional[str],
        aid: Optional[str],
        cid: int,
        page_referer: str,
        qn: int = 120,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "cid": cid,
            "qn": qn,
            "fnval": 1,
            "fourk": 1,
        }
        if bvid:
            params["bvid"] = bvid
        elif aid:
            params["aid"] = aid
        response = self.session.get(
            "https://api.bilibili.com/x/player/playurl",
            params=params,
            headers=self._headers_for_video_cdn(page_referer),
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(f"playurl failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        if js.get("code") != 0:
            raise AssertionError(f"playurl api error; code: {js.get('code')}, message: {js.get('message')}")
        return js["data"]

    @classmethod
    def _pick_video_url_from_playurl_data(cls, data: Dict[str, Any]) -> List[str]:
        """返回同一清晰度下主链路与备用地址列表（去重）。"""
        durl = data.get("durl") or []
        if not durl or not isinstance(durl[0], dict):
            return []
        first = durl[0]
        urls: List[str] = []
        main = first.get("url")
        if isinstance(main, str) and main.startswith("http"):
            urls.append(cls._https_url(main))
        for u in first.get("backup_url") or []:
            if isinstance(u, str) and u.startswith("http"):
                u2 = cls._https_url(u)
                if u2 not in urls:
                    urls.append(u2)
        return urls

    def build_post_meta(self, view_data: Dict[str, Any]) -> Dict[str, Any]:
        bvid = view_data.get("bvid")
        aid = view_data.get("aid")
        title = (view_data.get("title") or "").strip() or (bvid or str(aid))
        desc = (view_data.get("desc") or "").strip()
        pic = view_data.get("pic") or ""
        stat = view_data.get("stat") or {}
        owner = view_data.get("owner") or {}

        pages = view_data.get("pages") or []
        if not pages:
            cid = view_data.get("cid")
            if cid:
                pages = [{"cid": cid, "part": "P1"}]
        if not pages:
            raise AssertionError("view data has no pages/cid")

        page_referer = self.canonical_video_page_url(bvid, aid)

        video_urls: List[str] = []
        video_url_candidates: List[List[str]] = []

        for page in pages:
            if not isinstance(page, dict):
                continue
            cid = page.get("cid")
            if not cid:
                continue
            play = self.get_playurl_for_cid(
                bvid=bvid,
                aid=str(aid) if aid and not bvid else None,
                cid=int(cid),
                page_referer=page_referer,
            )
            group = self._pick_video_url_from_playurl_data(play)
            if group:
                video_url_candidates.append(group)
                video_urls.append(group[0])

        image_urls: List[str] = []
        image_url_candidates: List[List[str]] = []
        if isinstance(pic, str) and pic.startswith("http"):
            pic_u = self._https_url(pic)
            image_urls.append(pic_u)
            image_url_candidates.append([pic_u])

        media_type = "video" if video_urls else "image"

        return {
            "bvid": bvid,
            "aid": aid,
            "title": title,
            "desc": desc,
            "post_type": "video",
            "media_type": media_type,
            "final_url": page_referer,
            "cover_url": pic if isinstance(pic, str) else "",
            "image_urls": image_urls,
            "image_url_candidates": image_url_candidates,
            "video_urls": video_urls,
            "video_url_candidates": video_url_candidates,
            "pages": [
                {"index": idx, "cid": p.get("cid"), "part": (p.get("part") or f"P{idx}")}
                for idx, p in enumerate(pages, start=1)
                if isinstance(p, dict)
            ],
            "author": {
                "mid": owner.get("mid"),
                "name": owner.get("name"),
            },
            "interact_info": {
                "view_count": stat.get("view"),
                "danmaku_count": stat.get("danmaku"),
                "reply_count": stat.get("reply"),
                "favorite_count": stat.get("favorite"),
                "coin_count": stat.get("coin"),
                "share_count": stat.get("share"),
                "like_count": stat.get("like"),
            },
        }

    def get_post_meta_by_share_url(self, share_url: str) -> Dict[str, Any]:
        page_url = self.resolve_video_page_url(share_url)
        ids = self.parse_bvid_or_aid_from_url(page_url)
        view_data = self.get_view(bvid=ids["bvid"], aid=ids["aid"])
        return self.build_post_meta(view_data)

    def get_post_meta_by_share_text(self, text: str) -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.get_post_meta_by_share_url(share_url)

    def download_media_by_share_url(self, share_url: str, output_dir: str = "output_bilibili_media") -> Dict[str, Any]:
        post_meta = self.get_post_meta_by_share_url(share_url)
        referer = post_meta.get("final_url") or "https://www.bilibili.com/"

        output_dir_path = Path(output_dir)
        title_slug = self.sanitize_filename(post_meta["title"])
        key = post_meta.get("bvid") or f"av{post_meta.get('aid')}"
        save_dir = output_dir_path / f"{key}_{title_slug}"
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded_images: List[str] = []
        for index, image_url in enumerate(post_meta.get("image_urls") or [], start=1):
            ext = ".jpg"
            if ".png" in image_url.split("?")[0].lower():
                ext = ".png"
            elif ".webp" in image_url.split("?")[0].lower():
                ext = ".webp"
            filename = save_dir / f"cover{ext}" if index == 1 else save_dir / f"image_{index:02d}{ext}"
            self.download_file(image_url, filename, referer=referer)
            downloaded_images.append(filename.as_posix())

        downloaded_videos: List[str] = []
        for index, video_url in enumerate(post_meta.get("video_urls") or [], start=1):
            filename = save_dir / f"video_{index:02d}.mp4"
            self.download_file(video_url, filename, referer=referer)
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

    def download_media_by_share_text(self, text: str, output_dir: str = "output_bilibili_media") -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.download_media_by_share_url(share_url=share_url, output_dir=output_dir)


def main():
    client = ShareVideoDownload()
#     share_text = """
# https://t.bilibili.com/1202874151861223426?from_spmid=dt.dt.0.0.pv&plat_id=493&share_from=dynamic&share_medium=android&share_plat=android&share_session_id=2a8ae822-79c3-40bc-9ede-c2737b7de2e8&share_source=COPY&share_tag=s_i&spmid=dt.dt.0.0&timestamp=1778904366&unique_k=njmyI6r
#     """
    share_text = """"
https://b23.tv/oBke03t
    """
    post_meta = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(post_meta, ensure_ascii=False, indent=2))

    # post_meta = client.download_media_by_share_text(share_text)
    # print("post_meta:")
    # print(json.dumps(post_meta, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
