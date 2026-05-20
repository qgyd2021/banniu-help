#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Union, List, Optional

from pydantic import BaseModel, ConfigDict, Field


CountValue = Union[int, float, str]


class ReviewDuplicate(BaseModel):
    duplicate_task_ids: Optional[List[str]] = Field(default=None, description="重复的 task_id")


class ReviewText(BaseModel):
    model_config = ConfigDict(extra="allow")

    emotion_label: str = Field(default="", description="情绪标签")
    emotion_desc: str = Field(default="", description="情绪描述")
    title_length: int = Field(default=-1, description="标题长度")
    desc_length: int = Field(default=-1, description="描述长度")
    tags_match: Optional[List[str]] = Field(default=None, description="匹配到的标签")
    tags_miss: Optional[List[str]] = Field(default=None, description="未匹配到的标签")


class ReviewImage(BaseModel):
    model_config = ConfigDict(extra="allow")

    total_count: int = Field(default=-1, description="总的数量")
    check_count: int = Field(default=-1, description="打勾的数量")
    cross_count: int = Field(default=-1, description="打叉的数量")
    marks: Optional[dict] = Field(default=None, description="标注情况")


class ReviewVideo(BaseModel):
    model_config = ConfigDict(extra="allow")

    total_count: int = Field(default=-1, description="总的数量")
    check_count: int = Field(default=-1, description="打勾的数量")
    cross_count: int = Field(default=-1, description="打叉的数量")
    marks: Optional[dict] = Field(default=None, description="标注情况")


class ReviewFinal(BaseModel):
    model_config = ConfigDict(extra="allow")

    approved: Optional[bool] = Field(default=None, description="是否审核通过,为None时表示尚未决策。")
    reply_to_user: str = Field(default="", description="给用户的回复。")


class PostReview(BaseModel):
    model_config = ConfigDict(extra="allow")

    review_duplicate: ReviewDuplicate = Field(default_factory=ReviewDuplicate, description="重复检查")
    review_text: ReviewText = Field(default_factory=ReviewText, description="文本评价")
    review_image: ReviewImage = Field(default_factory=ReviewImage, description="图片评价")
    review_video: ReviewVideo = Field(default_factory=ReviewVideo, description="视频评价")
    review_final: ReviewFinal = Field(default_factory=ReviewFinal, description="最终审核")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostReview":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class PostReviewFinal(BaseModel):
    """与 JSON 顶层 ``post_review_final`` 对应；与 ``post_review`` 同级存储最终审核信息。"""

    model_config = ConfigDict(extra="allow")

    approved: Optional[bool] = Field(default=None, description="是否审核通过,为None时表示尚未决策。")
    approved_in_str: str = Field(default=None, description="是否审核通过, 字符类型，可选值：待审核，已通过，未通过。")
    reply_to_user: str = Field(default="", description="给用户的回复。")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostReviewFinal":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


def main() -> None:
    """示例：本地运行 ``python -m toolbox.porter.entity.post_review`` 验证终审字段判定与序列化。"""
    # 审核是否“已决策”，仅看 approved 是否为 None。
    assert ReviewFinal.model_validate({}).approved is None
    assert ReviewFinal.model_validate({"approved": None}).approved is None
    assert ReviewFinal.model_validate({"approved": True}).approved is True
    assert ReviewFinal.model_validate({"approved": False}).approved is False

    final = PostReviewFinal.from_dict({"approved": False, "reply_to_user": "测试回复"})
    dumped = final.to_dict()
    assert dumped.get("approved") is False and dumped.get("reply_to_user") == "测试回复"

    print("post_review main ok: approved null-check + PostReviewFinal roundtrip")


if __name__ == "__main__":
    main()
