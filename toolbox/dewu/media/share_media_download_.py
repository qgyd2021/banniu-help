#!/usr/bin/python3
# -*- coding: utf-8 -*-
import re
import json
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Union

import requests

from toolbox.utils.utils import when_error

CountValue = Union[int, float, str]


class VideoMeta(BaseModel):
    cover_url: str = Field(default="", description="贴子 ID")
    video_url: str = Field(default="", description="贴子 ID")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoMeta":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class PostMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    platform: str = Field(default="dewu", description="平台标识，如 xiaohongshu/bilibili/douyin 等")
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
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }

    def get_final_url_by_share_url(self, share_url: str) -> str:
        response = requests.get(share_url, headers=self.headers, timeout=30)
        return response.url

    def get_text_by_url(self, url: str):
        response = requests.get(url, headers=self.headers, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {url}")
        return response.text


class ShareMediaDownload(ShareMediaDownloadRestful):
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

    def get_next_data_by_final_url(self, final_url: str) -> Dict[str, Any]:
        html = self.get_text_by_url(final_url)

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

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        # print(f"share_url: {share_url}")
        final_url = self.get_final_url_by_share_url(share_url)
        # print(f"final_url: {final_url}")
        next_data = self.get_next_data_by_final_url(final_url)
        # print(json.dumps(next_data, ensure_ascii=False, indent=2))
        post_meta: PostMeta = self.build_post_meta_from_next_data_branch_1(next_data)
        if post_meta is None:
            raise AssertionError(f"未成功解析到信息；share_url: {share_url}")

        post_meta.share_url = share_url
        post_meta.final_url = final_url
        return post_meta.to_dict()

    @when_error(return_value=None)
    def build_post_meta_from_next_data_branch_1(self, next_data: dict):
        """
        https://dw4.co/t/A/1vQO3OAYQ

        #贴子内容不可见
        https://dw4.co/t/A/1vSUDChAQ
        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_next_data_branch_1"

        # for k, v in next_data.items():
        #     print(k)
        #     print(json.dumps(v, ensure_ascii=False, indent=2))

        page_props = next_data["props"]["pageProps"]
        post_meta.post_id = page_props["trendId"]
        data = page_props["metaOGInfo"]["data"]
        if len(data) == 0:
            post_meta.title = "blank"
            post_meta.desc = "blank"
            return post_meta
        data = data[0]
        user_info = data["userInfo"]
        content = data["content"]
        media_list = content["media"]["list"]

        post_meta.title = content["title"]

        desc = content["content"]
        tags = re.findall(r'#\S+', desc)
        desc = re.sub(r'#\S+', '', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()

        post_meta.desc = desc
        post_meta.tags = tags

        image_urls = list()
        for media in media_list:
            media_type = media["mediaType"]
            media_url = media["url"]
            if media_type == "img":
                image_urls.append(media_url)
        post_meta.image_urls = image_urls

        # post_meta.tags = [item["tag_name"] for item in tags]

        # post_meta.user_id = str(video_data["owner"]["mid"])
        post_meta.nickname = user_info["userName"]

        # post_meta.liked_count = video_data["stat"]["like"]
        # post_meta.collected_count = video_data["stat"]["favorite"]
        # post_meta.comment_count = video_data["stat"]["reply"]
        # post_meta.share_count = video_data["stat"]["share"]

        return post_meta



def main() -> None:
    client = ShareMediaDownload()

    share_text = """

https://dw4.co/t/A/1vQO3OAYQ

    """
    result = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
