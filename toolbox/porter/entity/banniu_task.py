#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


ScalarValue = Union[str, int, float, bool]


class BanniuTaskFormatted(BaseModel):
    # model_config = ConfigDict(extra="allow", populate_by_name=True)
    model_config = ConfigDict(extra="allow")  # 允许额外字段，但不保存到模型
    # model_config = ConfigDict(extra="forbid")  # 禁止额外字段

    task_id_int: Optional[int] = Field(default=None, alias="taskId(int)")
    task_id_str: Optional[str] = Field(default=None, alias="taskId(str)")

    share_text: Optional[str] = Field(default=None, alias="晒单内容链接")
    creator: Optional[str] = Field(default=None, alias="创建人")
    executor: Optional[str] = Field(default=None, alias="执行人")
    created_at: Optional[str] = Field(default=None, alias="创建时间")
    updated_at: Optional[str] = Field(default=None, alias="修改时间")
    task_status: Optional[str] = Field(default=None, alias="任务状态")
    create_type: Optional[str] = Field(default=None, alias="创建类型")
    title: Optional[str] = Field(default=None, alias="标题")

    ignore_address_warning: Optional[str] = Field(default=None, alias="是否忽略地址解析警告")
    receiver_name_for_query: Optional[str] = Field(default=None, alias="收货人（用于查询）")
    phone_for_cs_query: Optional[str] = Field(default=None, alias="手机号（用于客服查询）")
    phone_for_fill_query: Optional[str] = Field(default=None, alias="手机号码（用于填写/查询）")
    order_work_no: Optional[str] = Field(default=None, alias="工单编号")
    order_no: Optional[str] = Field(default=None, alias="订单号")

    sync_status: Optional[str] = Field(default=None, alias="同步状态")
    review_status: Optional[str] = Field(default=None, alias="审核状态")
    reject_reason: Optional[str] = Field(default=None, alias="审核不通过原因")

    publish_channel: Optional[str] = Field(default=None, alias="发布渠道")
    product_model: Optional[str] = Field(default=None, alias="产品型号")
    activity_desc: Optional[str] = Field(default=None, alias="活动简介")

    # 自动审核分数（注意：你后续已声明不作为新评分来源，这里仅建模存档）
    # text_review_score_auto: Optional[ScalarValue] = Field(default=None, alias="文字审核（自动）")
    # image_review_score_auto: Optional[ScalarValue] = Field(default=None, alias="图片审核（自动）")
    # video_review_score_auto: Optional[ScalarValue] = Field(default=None, alias="视频审核（自动）")
    # duplicate_review_score_auto: Optional[ScalarValue] = Field(default=None, alias="重复发贴（自动）")
    #
    # text_review_reason_auto: Optional[str] = Field(default=None, alias="文字审核原因（自动）")
    # image_review_reason_auto: Optional[str] = Field(default=None, alias="图片审核原因（自动）")
    # video_review_reason_auto: Optional[str] = Field(default=None, alias="视频审核原因（自动）")
    # duplicate_review_reason_auto: Optional[str] = Field(default=None, alias="重复发贴原因（自动）")

    # 流程/时效
    flow_status: Optional[str] = Field(default=None, alias="流程状态")
    is_auto_flow: Optional[str] = Field(default=None, alias="是否自动流转")
    review_time: Optional[str] = Field(default=None, alias="审核时间")
    reviewer: Optional[str] = Field(default=None, alias="审核人员")
    push_time: Optional[str] = Field(default=None, alias="推单时间")
    push_operator: Optional[str] = Field(default=None, alias="推单人员")
    wdt_push: Optional[str] = Field(default=None, alias="是否推单旺店通")
    review_sla: Optional[str] = Field(default=None, alias="审核时效")
    push_sla: Optional[str] = Field(default=None, alias="推单时效")

    @model_validator(mode="before")
    @classmethod
    def resolve_share_text(cls, values: dict):
        # 尝试从两个可能的键中取值，优先取“内容链接”
        if "内容链接" in values:
            values["share_text"] = values["内容链接"]
        elif "晒单内容链接" in values:
            values["share_text"] = values["晒单内容链接"]
        # 可选：删除原始字段避免污染（如果开启了 extra="forbid" 则必须删除）
        # values.pop("内容链接", None)
        # values.pop("晒单内容链接", None)
        return values

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BanniuTaskFormatted":
        return cls.model_validate(data or {})

    def to_dict(self, *, by_alias: bool = True) -> Dict[str, Any]:
        return self.model_dump(by_alias=by_alias)


if __name__ == "__main__":
    pass
