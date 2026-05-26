#!/usr/bin/python3
# -*- coding: utf-8 -*-
import re
import json
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, unquote, urlparse

import requests

from toolbox.utils.utils import when_error, when_expected_error, ExpectedError

CountValue = Union[int, float, str]


class VideoMeta(BaseModel):
    cover_url: str = Field(default="", description="封面 URL")
    video_url: str = Field(default="", description="视频 URL")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoMeta":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class PostMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    platform: str = Field(default="kuaishou", description="平台标识，如 xiaohongshu/bilibili/douyin 等")
    share_url: str = Field(default="", description="分享链接（短链或原链）")
    final_url: str = Field(default="", description="落地页最终 URL")

    post_id: str = Field(default="", description="贴子 ID")
    post_type: str = Field(default="", description="视频,图文,")

    title: str = Field(default="", description="标题")
    desc: str = Field(default="", description="正文/描述")
    tags: List[str] = Field(default_factory=list, description="标签列表")

    user_id: str = Field(default="", description="作者 ID")
    nickname: str = Field(default="", description="作者昵称")

    liked_count: CountValue = Field(default="", description="点赞数（可能为 str/int）")
    collected_count: CountValue = Field(default="", description="收藏数（可能为 str/int）")
    comment_count: CountValue = Field(default="", description="评论数（可能为 str/int）")
    share_count: CountValue = Field(default="", description="分享数（可能为 str/int）")

    image_urls: List[str] = Field(default_factory=list, description="图片 URL 列表")
    video_urls: List[VideoMeta] = Field(default_factory=list, description="视频 URL 列表")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostMeta":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class ShareMediaDownloadRestful(object):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
    }

    def get_html_and_final_url_by_share_url(self, share_url: str) -> str:
        response = requests.get(share_url, headers=self.headers,
                                allow_redirects=True,
                                timeout=30)
        return response.text, response.url

    def get_text_by_url(self, url: str) -> str:
        response = requests.get(url, headers=self.headers, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {url}")
        return response.text


class ShareMediaDownload(ShareMediaDownloadRestful):
    _SHARE_ENTRY_URL_PATTERNS: List[str] = [
        r"https?://v\.kuaishou\.com/[A-Za-z0-9_\-]+",
        r"https?://(?:www\.)?kuaishou\.com/[^\s]+",
        r"https?://v\.m\.chenzhongtech\.com/[^\s]+",
        r"https?://m\.gifshow\.com/[^\s]+",
    ]

    @classmethod
    def get_share_url_by_share_text(cls, share_text: str) -> str:
        """
        从分享文案或单独 URL 中取出一条快手分享入口链接。
        """
        if share_text.startswith("http") and "\n" not in share_text:
            single = share_text.split()[0].rstrip(".,;)")
            if re.search(r"(?:kuaishou\.com|chenzhongtech\.com|gifshow\.com)", single, re.I):
                return single
        for pattern in cls._SHARE_ENTRY_URL_PATTERNS:
            m = re.search(pattern, share_text, flags=re.IGNORECASE)
            if m is not None:
                return m.group(0).rstrip(".,;)")
        raise AssertionError(f"未识别到快手分享链接; text: {share_text!r}")

    @staticmethod
    def extract_tags_and_desc(caption: str) -> Tuple[List[str], str]:
        tags = list()
        desc = caption

        caption = caption.strip()
        if not caption:
            return tags, desc

        tags = re.findall(r"[#＃]([^\s#＃]+)", caption)
        desc = caption
        for tag in sorted(tags, key=len, reverse=True):
            desc = desc.replace(f"#{tag}", "")
            desc = desc.replace(f"＃{tag}", "")
        desc = re.sub(r"[ \t]+", " ", desc).strip()
        return tags, desc

    def get_photo_data_by_html(self, html: str) -> Optional[PostMeta]:
        dec = json.JSONDecoder()

        photo_data = None
        for match in re.finditer(r'"photo"\s*:\s*\{', html):
            start = match.start() + match.group(0).rfind("{")
            try:
                js, _ = dec.raw_decode(html[start:])
            except json.JSONDecodeError:
                continue
            if not isinstance(js, dict):
                continue
            # print(json.dumps(js, ensure_ascii=False, indent=2))
            photo_type = js.get("photoType")
            if photo_type not in ("VIDEO", "SINGLE_PICTURE", "HORIZONTAL_ATLAS"):
                continue
            photo_data = js
            break
        return photo_data

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        result = self.get_post_meta_by_share_url(share_url)
        return result

    @when_expected_error(return_value=None)
    def get_post_meta_by_share_url(self, share_url: str) -> dict:
        html, final_url = self.get_html_and_final_url_by_share_url(share_url)
        # print(f"final_url: {final_url}")
        # print(f"html: {html}")

        photo_data = self.get_photo_data_by_html(html)
        # print(f"photo_data: {json.dumps(photo_data, ensure_ascii=False, indent=2)}")

        photo_type = photo_data["photoType"]
        if photo_type == "VIDEO":
            post_meta: PostMeta = self.build_post_meta_from_photo_data_branch_1(photo_data, html)
        elif photo_type == "SINGLE_PICTURE":
            post_meta: PostMeta = self.build_post_meta_from_photo_data_branch_2(photo_data, html)
        elif photo_type == "HORIZONTAL_ATLAS":
            post_meta: PostMeta = self.build_post_meta_from_photo_data_branch_3(photo_data, html)
        else:
            raise NotImplementedError

        if post_meta is None:
            raise ExpectedError(status_code=60500, message="未成功解析到信息；share_url: {share_url}")

        post_meta.share_url = share_url
        post_meta.final_url = final_url
        return post_meta.to_dict()

    @when_error(return_value=None)
    def build_post_meta_from_photo_data_branch_1(self, photo_data: dict, html: str) -> Optional[PostMeta]:
        """
        https://www.kuaishou.com/f/X-2tHDrwukrgI2kl
https://www.kuaishou.com/f/X1SmYFVFZy0Xeoh
        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_photo_data_branch_1"

        photo_type = photo_data["photoType"]
        # print(f"photo_type: {photo_type}")

        tags, desc = self.extract_tags_and_desc(photo_data["caption"])

        post_meta.post_id = photo_data["photoId"]
        post_meta.title = ""
        post_meta.desc = desc
        post_meta.tags = tags

        post_meta.user_id = str(photo_data["userId"])
        post_meta.nickname = photo_data["userName"]

        post_meta.liked_count = photo_data["likeCount"]
        post_meta.comment_count = photo_data["commentCount"]
        post_meta.share_count = photo_data["forwardCount"]

        match = re.search(r'"collectionCount":(\d+),"', html)
        if match is not None:
            post_meta.collected_count = match.group(1)

        # post_meta.image_urls = self._image_urls_from_atlas(atlas) if atlas else []

        video_url: str = photo_data["mainMvUrls"][0]["url"]
        cover_url: str = photo_data["coverUrls"][0]["url"]
        post_meta.video_urls = [VideoMeta(cover_url=cover_url, video_url=video_url)]

        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_photo_data_branch_2(self, photo_data: dict, html: str) -> Optional[PostMeta]:
        """
        SINGLE_PICTURE
        https://v.kuaishou.com/KD1hnkg3

        https://v.kuaishou.com/KE8R7a5Y
        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_photo_data_branch_2"

        # print(f"photo_data: {json.dumps(photo_data, ensure_ascii=False, indent=4)}")

        photo_type = photo_data["photoType"]
        # print(f"photo_type: {photo_type}")

        tags, desc = self.extract_tags_and_desc(photo_data["caption"])

        post_meta.post_id = photo_data["photoId"]
        post_meta.title = ""
        post_meta.desc = desc
        post_meta.tags = tags

        post_meta.user_id = str(photo_data["userId"])
        post_meta.nickname = photo_data["userName"]

        post_meta.liked_count = photo_data.get("likeCount", 0)
        post_meta.comment_count = photo_data["commentCount"]
        post_meta.share_count = photo_data["forwardCount"]

        match = re.search(r'"collectionCount":(\d+),"', html)
        if match is not None:
            post_meta.collected_count = match.group(1)

        post_meta.image_urls = [photo_data["coverUrls"][0]["url"]]
        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_photo_data_branch_3(self, photo_data: dict, html: str) -> Optional[PostMeta]:
        """
        HORIZONTAL_ATLAS
        https://v.kuaishou.com/KneovpYF
        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_photo_data_branch_3"

        photo_type = photo_data["photoType"]
        # print(f"photo_type: {photo_type}")

        # print(f"photo_data: {json.dumps(photo_data, ensure_ascii=False, indent=2)}")

        tags, desc = self.extract_tags_and_desc(photo_data["caption"])

        post_meta.post_id = photo_data["photoId"]
        post_meta.title = ""
        post_meta.desc = desc
        post_meta.tags = tags

        post_meta.user_id = str(photo_data["userId"])
        post_meta.nickname = photo_data["userName"]

        post_meta.liked_count = photo_data.get("likeCount", 0)
        post_meta.comment_count = photo_data["commentCount"]
        post_meta.share_count = photo_data["forwardCount"]
        # print(f"photo_data: {json.dumps(photo_data, ensure_ascii=False, indent=2)}")

        match = re.search(r'"collectionCount":(\d+),"', html)
        if match is not None:
            post_meta.collected_count = match.group(1)

        image_urls = photo_data["ext_params"]["atlas"]["list"]
        image_urls = [f"https://p2.a.yximgs.com/{image_url}" for image_url in image_urls]
        post_meta.image_urls = image_urls
        return post_meta


def main() -> None:
    """
    https://v.kuaishou.com/KneovpYF
    :return:
    """
    client = ShareMediaDownload()

    share_text = """

https://v.kuaishou.com/KE8R7a5Y

"""
    # share_text = """
    # https://v.kuaishou.com/J7gprA8p
    # """
    result = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
