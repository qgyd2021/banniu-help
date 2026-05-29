#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json

from pandas._libs.hashtable import Factorizer
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Tuple, Optional

from toolbox.porter.entity.banniu_task import BanniuTaskFormatted
from toolbox.porter.entity.post_review import PostReview, PostReviewFinal
from toolbox.porter.common.params import Params


class PostReviewCheckerReviewMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_model: Optional[str] = Field(default=None, description="产品型号与订单信息不匹配")
    review_duplicate: Optional[str] = Field(default=None, description="贴子重复")
    emotion_label: Optional[str] = Field(default=None, description="情绪标签")
    text_length: Optional[str] = Field(default=None, description="字数")
    tags_miss: Optional[str] = Field(default=None, description="缺少标签")
    image_item_miss: Optional[str] = Field(default=None, description="图片物品检测")
    min_image_count: Optional[str] = Field(default=None, description="最小图片数")
    min_video_count: Optional[str] = Field(default=None, description="最小视频数")
    image_and_video: Optional[str] = Field(default=None, description="图片或视频必须有")
    max_image_cross_rate: Optional[str] = Field(default=None, description="太多图片不符合")
    max_video_cross_rate: Optional[str] = Field(default=None, description="太多视频不符合")
    review_final: Optional[str] = Field(default=None, description="人工审核结果")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostReviewCheckerResult":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class PostReviewCheckerResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    approval: bool = Field(default=None, description="审核是否通过")
    review_msg: PostReviewCheckerReviewMessage = Field(default_factory=PostReviewCheckerReviewMessage, description="审核信息")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostReviewCheckerResult":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class PostReviewChecker(object):
    def __init__(
        self,
        positive_emotion_labels: List[str] = None,
        min_total_text_length: int = 0,
        required_tags_dict: Dict[str, List[str]] = None,
        required_image_item_dict: Dict[str, List[str]] = None,
        min_image_count: int = 0,
        max_image_cross_rate: float = 0.0,
        min_video_count: int = 0,
        max_video_cross_rate: float = 0.0,
    ):
        self.positive_emotion_labels = positive_emotion_labels or ["积极"]
        self.min_total_text_length = int(min_total_text_length)
        self.required_tags_dict = required_tags_dict or dict()
        self.required_image_item_dict = required_image_item_dict or dict()
        self.min_image_count = int(min_image_count)
        self.max_image_cross_rate = float(max_image_cross_rate)
        self.min_video_count = int(min_video_count)
        self.max_video_cross_rate = float(max_video_cross_rate)

    def predict(self, post_review: PostReview, task_formatted: BanniuTaskFormatted) -> PostReviewCheckerResult:
        product_model = task_formatted.product_model

        result = PostReviewCheckerResult()

        #旺店通-商家编号
        merchant_id = task_formatted.purchase_info_dict.get("39400", "")
        if product_model not in merchant_id:
            result.review_msg.product_model = f"用户给的产品型号与订单信息不匹配。{product_model}，{merchant_id}"

        duplicate_task_ids = post_review.review_duplicate.duplicate_task_ids or []
        if len(duplicate_task_ids) > 0:
            result.review_msg.review_duplicate = f"重复提交；重复ID：{'，'.join(duplicate_task_ids)}。"

        emotion_label = post_review.review_text.emotion_label
        if emotion_label not in self.positive_emotion_labels:
            result.review_msg.emotion_label = f"贴子应为正向积极的内容；当前情绪：{emotion_label}。"

        title_length = post_review.review_text.title_length
        desc_length = post_review.review_text.desc_length
        total_length = title_length + desc_length
        if total_length < self.min_total_text_length:
            result.review_msg.text_length = f"标题和描述的总字数太少；总长度：{total_length}，最小长应：{self.min_total_text_length}。"

        tags_match = post_review.review_text.tags_match or []
        required_tags = self.required_tags_dict.get(product_model, [])
        tags_miss = [tag for tag in required_tags if tag not in tags_match]
        if len(tags_miss) > 0:
            result.review_msg.tags_miss = f"缺少标签：{'，'.join(tags_miss)}。"

        image_total = post_review.review_image.total_count
        image_cross = post_review.review_image.cross_count

        video_total = post_review.review_video.total_count
        video_cross = post_review.review_video.cross_count

        if image_total > 0:
            required_image_items = self.required_image_item_dict.get(product_model, [])
            image_item_match = list()
            for image_item in (post_review.review_image_item.images or []):
                class_counts: dict = image_item.get("class_counts") or {}
                for k, _ in class_counts.items():
                    if k in required_image_items:
                        image_item_match.append(k)
            image_item_miss = [image_item for image_item in required_image_items if image_item not in image_item_match]
            if len(image_item_miss) > 0:
                result.review_msg.image_item_miss = f"未从图片中检测到物品：{'，'.join(image_item_miss)}。"

        if video_total <= 0 and image_total < self.min_image_count:
            result.review_msg.min_image_count = f"图片太少；当前图片数量: {image_total}。"
        if image_total <= 0 and video_total < self.min_video_count:
            result.review_msg.min_video_count = f"视频太少；当前视频数量: {video_total}。"
        if image_total <= 0 and video_total <= 0:
            result.review_msg.image_and_video = "必须要有图片或视频。"

        if image_total > 0:
            image_cross_rate = image_cross / image_total
            if image_cross_rate > self.max_image_cross_rate:
                result.review_msg.max_image_cross_rate = f"太多不符合的图片；图片总数: {image_total}，不符合的图片数：{image_cross}。"

        if video_total > 0:
            video_cross_rate = video_cross / video_total
            if video_cross_rate > self.max_video_cross_rate:
                result.review_msg.max_video_cross_rate = f"太多不符合的视频；视频总数: {video_total}，不符合的视频数：{video_cross}。"

        if post_review.review_final.approved is False:
            result.review_msg.review_final = f"人工已审核为不通过；{post_review.review_final.reply_to_user}。"

        # ``approval`` 反映 "自动审核是否会通过"，纯看自动检测项，不让 ``review_final``
        # （人工已审核状态）这条参考信息干扰判定，避免出现 "人工已审核为通过" 时
        # 自动预测反而显示 "将不通过" 的反直觉情况。
        review_msg_for_approval = result.review_msg.to_dict()
        review_msg_for_approval.pop("review_final", None)
        result.approval = len(review_msg_for_approval) == 0
        return result


class PostReviewer(Params):
    def process(self, post_review_checker_result: PostReviewCheckerResult) -> PostReviewFinal:
        raise NotImplementedError


@PostReviewer.register("missing_tag_only")
class PostReviewerMissingTagOnly(PostReviewer):
    def __init__(self):
        pass

    def process(self, post_review_checker_result: PostReviewCheckerResult) -> PostReviewFinal:
        """
        当贴子的问题项有且只有 `缺少标签` 时。进行驳回。

        自动审稿时
        """
        if post_review_checker_result.approval:
            return None

        review_msg = post_review_checker_result.review_msg.to_dict()

        # 自动审稿时不考虑图片数量与是否符合的问题。
        review_msg.pop("min_image_count", None)
        review_msg.pop("min_video_count", None)
        review_msg.pop("image_and_video", None)

        # print(f"review_msg: {json.dumps(review_msg, ensure_ascii=False, indent=4)}")
        if len(review_msg) != 1:
            return None
        tags_miss = review_msg.get("tags_miss")
        if tags_miss is None:
            return None

        post_review_final = PostReviewFinal()
        post_review_final.reviewer = "missing_tag_only"
        post_review_final.approved = False
        post_review_final.approved_in_str = PostReviewFinal.get_approved_in_str(post_review_final.approved)
        post_review_final.reply_to_user = f"{tags_miss} 修改后可联系客服重新修改审核。"
        return post_review_final


def main():
    js = {
        "review_duplicate": {
            "duplicate_task_ids": [
                "7098673"
            ]
        },
        "review_text": {
            "emotion_label": "积极",
            "emotion_desc": "用户请求对其发布的社交媒体帖子中的文字部分进行情感分析。根据提供的标题“最新视频上线，求关注！”，该描述表达了积极推广和寻求互动的态度。",
            "title_length": 11,
            "desc_length": 1,
            "tags_match": [],
            "tags_miss": [
                "迈从ACE68v2",
                "迈从"
            ]
        },
        "review_image": {
            "total_count": 1,
            "check_count": 1,
            "cross_count": 0,
            "marks": {
                "https://i1.hdslb.com/bfs/archive/bee6ba810200174c74ad795e4d58a0c5b4abf05e.jpg": ""
            }
        },
        "review_video": {
            "total_count": 1,
            "check_count": 1,
            "cross_count": 0,
            "marks": {
                "https://upos-sz-estghw.bilivideo.com/upgcxcode/42/82/38371068242/38371068242-1-192.mp4?e=ig8euxZM2rNcNbRj7bdVhwdlhWTjhwdVhoNvNC8BqJIzNbfqXBvEqxTEto8BTrNvN0GvT90W5JZMkX_YN0MvXg8gNEV4NC8xNEV4N03eN0B5tZlqNxTEto8BTrNvNeZVuJ10Kj_g2UB02J0mN0B5tZlqNCNEto8BTrNvNC7MTX502C8f2jmMQJ6mqF2fka1mqx6gqj0eN0B599M=&platform=pc&trid=99d8be1cc74e40ef97e6b0781ba03adu&oi=245014963&mid=0&uipk=5&deadline=1779191688&gen=playurlv3&os=estghw&og=hw&nbs=1&upsig=427d1e0d8103a8b326163b9b1c0cae93&uparams=e,platform,trid,oi,mid,uipk,deadline,gen,os,og,nbs&bvc=vod&nettype=0&bw=1357436&buvid=81E17CDC-23CA-E558-6C5A-9E314F99007980601infoc&build=0&dl=0&f=u_0_0&qn_dyeid=6930d5c40f5b490600c5cbce6a0c3368&agrr=1&orderid=0,3": ""
            }
        },
        "review_final": {
            "approved": False,
            "reply_to_user": "字数应不少于40个。\n应带上 #A7V2标签。"
        }
    }

    js = {
        "review_duplicate": {
            "duplicate_task_ids": [
                "7098673"
            ]
        },
        "review_text": {
            "emotion_label": "积极",
            "emotion_desc": "用户请求对其发布的社交媒体帖子中的文字部分进行情感分析。根据提供的标题“最新视频上线，求关注！”，该描述表达了积极推广和寻求互动的态度。",
            "title_length": 11,
            "desc_length": 1,
            "tags_match": [],
            "tags_miss": [
                "迈从ACE68v2",
                "迈从"
            ]
        },
        "review_image": {
            "total_count": 1,
            "check_count": 0,
            "cross_count": 1,
            "marks": {
                "https://i1.hdslb.com/bfs/archive/bee6ba810200174c74ad795e4d58a0c5b4abf05e.jpg": ""
            }
        },
        "review_video": {
            "total_count": 0,
            "check_count": 0,
            "cross_count": 0,
            "marks": {}
        },
        "review_final": {
            "approved": False,
            "reply_to_user": "字数应不少于40个。\n应带上 #A7V2标签。"
        }
    }
    post_review = PostReview.from_dict(js)
    print(post_review)

    post_review_checker = PostReviewChecker(
        positive_emotion_labels=["积极"],
        min_total_text_length=40,
        required_tags_dict={"A7V2": ["迈从"]},
        min_image_count=3,
        max_image_cross_rate=0.4,
        min_video_count=1,
        max_video_cross_rate=0.5
    )

    result = post_review_checker.predict(post_review, product_model="A7V2")
    print(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
