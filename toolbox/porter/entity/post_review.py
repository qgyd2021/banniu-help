#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Union

from pydantic import BaseModel, ConfigDict, Field


CountValue = Union[int, float, str]


class ReviewText(BaseModel):
    """
    文本审核聚合结果（保持原有类名与字段名不变）。

    历史 JSON 可能缺字段，因此全部给默认值以避免解析失败。
    """

    model_config = ConfigDict(extra="allow")

    emotion_label: str = Field(default="", description="情绪标签")
    emotion_score: float = Field(default=-1, description="情绪分数")
    emotion_desc: str = Field(default="", description="情绪描述")
    length_score: float = Field(default=-1, description="长度分数")
    length_desc: str = Field(default="", description="长度描述")
    tags_score: float = Field(default=-1, description="标签分数")
    tags_desc: str = Field(default="", description="标签描述")


class ReviewImage(BaseModel):
    """图片审核聚合结果（保持原有类名与字段名不变）。"""

    model_config = ConfigDict(extra="allow")

    image_score: float = Field(default=-1, description="图片分数")
    image_desc: str = Field(default="", description="图片描述")


class ReviewVideo(BaseModel):
    """视频审核聚合结果（保持原有类名与字段名不变）。"""

    model_config = ConfigDict(extra="allow")

    video_score: float = Field(default=-1, description="视频分数")
    video_desc: str = Field(default="", description="视频描述")


class PostReview(BaseModel):
    model_config = ConfigDict(extra="allow")

    review_text: ReviewText = Field(default_factory=ReviewText, description="文本评价")
    review_image: ReviewImage = Field(default_factory=ReviewImage, description="图片评价")
    review_video: ReviewVideo = Field(default_factory=ReviewVideo, description="视频评价")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostReview":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


if __name__ == "__main__":
    pass
