#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Union

from pydantic import BaseModel, ConfigDict, Field


CountValue = Union[int, float, str]


class PostMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    post_id: str = Field(default="", description="贴子 ID")

    platform: str = Field(default="", description="平台标识，如 xiaohongshu/bilibili/douyin 等")
    share_url: str = Field(default="", description="分享链接（短链或原链）")

    title: str = Field(default="", description="标题")
    desc: str = Field(default="", description="正文/描述")
    tags: List[str] = Field(default_factory=list, description="标签列表")

    user_id: str = Field(default="", description="作者 ID")
    nickname: str = Field(default="", description="作者昵称")

    liked_count: CountValue = Field(default="", description="点赞数（可能为 str/int）")
    collected_count: CountValue = Field(default="", description="收藏数（可能为 str/int）")
    comment_count: CountValue = Field(default="", description="评论数（可能为 str/int）")
    share_count: CountValue = Field(default="", description="分享数（可能为 str/int）")

    final_url: str = Field(default="", description="落地页最终 URL")
    image_urls: List[str] = Field(default_factory=list, description="图片 URL 列表")
    video_urls: List[str] = Field(default_factory=list, description="视频 URL 列表")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostMeta":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict_by_bilibili_opus(cls, data: Dict[str, Any]) -> "PostMeta":

        payload: Dict[str, Any] = {
            "platform": "bilibili",

            "post_id": data["opus_id"],
            "share_url": data["share_url"],
            "title": data["title"],
            "desc": data["body_text"],
            "tags": [],

            "user_id": str(data["author"]["mid"]),
            "nickname": data["author"]["name"],

            "liked_count": data["interact_info"]["like_count"],
            "collected_count": "",
            "comment_count": data["interact_info"]["comment_count"],
            "share_count": data["interact_info"]["forward_count"],

            "final_url": data["final_url"],
            "image_urls": data.get("image_urls", list()),
            "video_urls": data.get("video_urls", list()),
        }
        return cls.model_validate(payload)

    @classmethod
    def from_dict_by_bilibili_video(cls, data: Dict[str, Any]) -> "PostMeta":

        payload: Dict[str, Any] = {
            "platform": "bilibili",

            "post_id": data["bvid"],
            "share_url": data["share_url"],
            "title": data["title"],
            "desc": data["desc"],
            "tags": [],

            "user_id": str(data["author"]["mid"]),
            "nickname": data["author"]["name"],

            "liked_count": data["interact_info"]["like_count"],
            "collected_count": data["interact_info"]["favorite_count"],
            "comment_count": data["interact_info"]["reply_count"],
            "share_count": data["interact_info"]["share_count"],

            "final_url": data["final_url"],
            "image_urls": data.get("image_urls", list()),
            "video_urls": data.get("video_urls", list()),
        }
        return cls.model_validate(payload)

    @classmethod
    def from_dict_by_dewu(cls, data: Dict[str, Any]) -> "PostMeta":
        payload: Dict[str, Any] = {
            "platform": "dewu",

            "post_id": data["trend_id"],
            "share_url": data["share_url"],
            "title": data["title"],
            "desc": data["desc"],
            "tags": [],

            "user_id": data["user_name"],
            "nickname": data["user_id"],

            "liked_count": "",
            "collected_count": "",
            "comment_count": "",
            "share_count": "",

            "final_url": data["final_url"],
            "image_urls": data.get("image_urls", list()),
            "video_urls": data.get("video_urls", list()),
        }
        return cls.model_validate(payload)

    @classmethod
    def from_dict_by_douyin(cls, data: Dict[str, Any]) -> "PostMeta":
        """
        将 `toolbox.douyin.media.share_media_download.ShareMediaDownload.get_post_meta_*` 的返回值
        映射为统一 PostMeta。
        """
        payload: Dict[str, Any] = {
            "platform": "douyin",
            "post_id": data["aweme_id"],
            "share_url": data["share_url"],
            "title": data.get("title") or "",
            "desc": data.get("desc") or "",
            "tags": [],
            "user_id": str((data.get("author") or {}).get("uid") or (data.get("author") or {}).get("sec_uid") or ""),
            "nickname": str((data.get("author") or {}).get("nickname") or ""),
            "liked_count": (data.get("interact_info") or {}).get("digg_count", ""),
            "collected_count": (data.get("interact_info") or {}).get("collect_count", ""),
            "comment_count": (data.get("interact_info") or {}).get("comment_count", ""),
            "share_count": (data.get("interact_info") or {}).get("share_count", ""),
            "final_url": data.get("final_url") or "",
            "image_urls": data.get("image_urls", list()),
            "video_urls": data.get("video_urls", list()),
        }
        return cls.model_validate(payload)

    @classmethod
    def from_dict_by_xiaohongshu(cls, data: Dict[str, Any]) -> "PostMeta":
        """
        将 `toolbox.xiaohongshu.media.share_media_download.ShareMediaDownload.get_post_meta_*` 的返回值
        映射为统一 PostMeta。
        """
        user = data.get("user") or {}
        interact = data.get("interact_info") or {}
        payload: Dict[str, Any] = {
            "platform": "xiaohongshu",
            "post_id": data["note_id"],
            "share_url": data["share_url"],
            "title": data.get("title") or "",
            "desc": data.get("desc") or "",
            "tags": data.get("tags") or [],
            "user_id": str(user.get("user_id") or ""),
            "nickname": str(user.get("nickname") or ""),
            "liked_count": interact.get("liked_count", ""),
            "collected_count": interact.get("collected_count", ""),
            "comment_count": interact.get("comment_count", ""),
            "share_count": interact.get("share_count", ""),
            "final_url": data.get("final_url") or "",
            "image_urls": data.get("image_urls", list()),
            "video_urls": data.get("video_urls", list()),
        }
        return cls.model_validate(payload)

    @classmethod
    def from_dict_by_kuaishou(cls, data: Dict[str, Any]) -> "PostMeta":
        """
        将 `toolbox.kuaishou.media.share_media_download.ShareMediaDownload.get_post_meta_*` 的返回值
        映射为统一 PostMeta。
        """
        user = data.get("user") or {}
        interact = data.get("interact_info") or {}
        payload: Dict[str, Any] = {
            "platform": "kuaishou",
            "post_id": data.get("photo_sid") or data.get("photo_id") or "",
            "share_url": data["share_url"],
            "title": data.get("title") or "",
            "desc": data.get("caption") or "",
            "tags": [],
            "user_id": str(user.get("user_id") or ""),
            "nickname": str(user.get("nickname") or ""),
            "liked_count": interact.get("like_count", ""),
            "collected_count": "",
            "comment_count": interact.get("comment_count", ""),
            "share_count": interact.get("forward_count", ""),
            "final_url": data.get("final_url") or "",
            "image_urls": data.get("image_urls", list()),
            "video_urls": data.get("video_urls", list()),
        }
        return cls.model_validate(payload)

    @classmethod
    def from_dict_by_xiaoheihe(cls, data: Dict[str, Any]) -> "PostMeta":
        """
        将 `toolbox.xiaoheihe.media.share_media_download.ShareMediaDownload.get_post_meta_*` 的返回值
        映射为统一 PostMeta。
        """
        payload: Dict[str, Any] = {
            "platform": "xiaoheihe",
            "post_id": data["link_id"],
            "share_url": data["share_url"],
            "title": data.get("title") or "",
            "desc": data.get("desc") or "",
            "tags": [],
            "user_id": str(data.get("user_id") or ""),
            "nickname": str(data.get("username") or ""),
            "liked_count": "",
            "collected_count": "",
            "comment_count": "",
            "share_count": "",
            "final_url": data.get("final_url") or "",
            "image_urls": data.get("image_urls", list()),
            "video_urls": data.get("video_urls", list()),
        }
        return cls.model_validate(payload)

    @classmethod
    def from_dict_by_weibo(cls, data: Dict[str, Any]) -> "PostMeta":
        """
        将 `toolbox.weibo.media.share_media_download.ShareMediaDownload.get_post_meta_*` 的返回值
        映射为统一 PostMeta。
        """
        user = data.get("user") or {}
        interact = data.get("interact_info") or {}
        payload: Dict[str, Any] = {
            "platform": "weibo",
            "post_id": data["status_id"],
            "share_url": data["share_url"],
            "title": data.get("title") or "",
            "desc": data.get("text") or "",
            "tags": [],
            "user_id": str(user.get("id") or ""),
            "nickname": str(user.get("screen_name") or ""),
            "liked_count": interact.get("attitudes_count", ""),
            "collected_count": "",
            "comment_count": interact.get("comments_count", ""),
            "share_count": interact.get("reposts_count", ""),
            "final_url": data.get("final_url") or "",
            "image_urls": data.get("image_urls", list()),
            "video_urls": data.get("video_urls", list()),
        }
        return cls.model_validate(payload)


if __name__ == "__main__":
    pass
