#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

import cacheout
import requests
from pydantic import BaseModel, ConfigDict, Field

from toolbox.utils.utils import when_error, when_expected_error, ExpectedError

logger = logging.getLogger("toolbox")

CountValue = Union[int, float, str]


class UserMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    platform: str = Field(default="xiaohongshu", description="平台标识")
    author_user_id: str = Field(default="", description="作者 userId")
    unique_id: str = Field(default="", description="小红书号 redId")
    nickname: str = Field(default="", description="昵称")
    signature: str = Field(default="", description="个性签名")

    follower_count: CountValue = Field(default="", description="粉丝数")
    following_count: CountValue = Field(default="", description="关注数")
    liked_count: CountValue = Field(default="", description="获赞与收藏数")

    avatar_url: str = Field(default="", description="头像 URL")
    profile_url: str = Field(default="", description="主页 URL")
    source: str = Field(default="", description="数据来源分支")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMeta":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class UserInfoRestful(object):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }

    def get_text_by_url(self, url: str) -> str:
        response = requests.get(url, headers=self.headers, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, text: {response.text}, url: {url}"
            )
        return response.text

    @staticmethod
    def build_user_profile_url(author_user_id: str = "") -> str:
        author_user_id = str(author_user_id or "").strip()
        if author_user_id:
            return f"https://www.xiaohongshu.com/user/profile/{author_user_id}"
        return "https://www.xiaohongshu.com/"


class UserInfo(UserInfoRestful):
    @staticmethod
    def parse_initial_state(html: str) -> Dict[str, Any]:
        marker = "window.__INITIAL_STATE__="
        start = html.find(marker)
        if start < 0:
            raise AssertionError("window.__INITIAL_STATE__ not found")
        start += len(marker)
        end = html.find("</script>", start)
        if end < 0:
            raise AssertionError("window.__INITIAL_STATE__ tail not found")
        raw = html[start:end].strip()
        raw = re.sub(r"\bundefined\b", "null", raw)
        raw = re.sub(r"\bNaN\b", "null", raw)
        raw = re.sub(r"\bInfinity\b", "null", raw)
        return json.loads(raw)

    @cacheout.memoize(ttl=600)
    def get_user_profile_state(self, author_user_id: str) -> Dict[str, Any]:
        author_user_id = str(author_user_id or "").strip()
        if not author_user_id:
            raise ExpectedError(status_code=60500, message="author_user_id is empty")
        profile_url = self.build_user_profile_url(author_user_id)
        html = self.get_text_by_url(profile_url)
        return self.parse_initial_state(html)

    @when_error(return_value=None)
    def build_user_meta_from_profile_state_branch_1(
        self,
        state: Dict[str, Any],
        author_user_id: str = "",
    ) -> UserMeta:
        user_meta = UserMeta()
        user_meta.source = "build_user_meta_from_profile_state_branch_1"

        basic_info = state["user"]["userPageData"]["basicInfo"]
        user_meta.author_user_id = str(author_user_id)
        user_meta.unique_id = str(basic_info["redId"])
        user_meta.nickname = str(basic_info["nickname"])
        user_meta.signature = str(basic_info.get("desc") or "")

        interactions = state["user"]["userPageData"].get("interactions")
        if isinstance(interactions, list):
            for item in interactions:
                if not isinstance(item, dict):
                    continue
                interaction_type = item.get("type")
                if interaction_type == "fans":
                    user_meta.follower_count = item.get("count", "")
                elif interaction_type == "follows":
                    user_meta.following_count = item.get("count", "")
                elif interaction_type == "interaction":
                    user_meta.liked_count = item.get("count", "")

        images = basic_info.get("images")
        if isinstance(images, str) and images:
            user_meta.avatar_url = images

        user_meta.profile_url = self.build_user_profile_url(user_meta.author_user_id)
        return user_meta

    @when_expected_error(return_value=None)
    def get_user_meta_by_author_user_id(self, author_user_id: str) -> Optional[Dict[str, Any]]:
        author_user_id = str(author_user_id or "").strip()
        if not author_user_id:
            raise ExpectedError(status_code=60500, message="author_user_id is empty")

        state = self.get_user_profile_state(author_user_id)
        user_meta = self.build_user_meta_from_profile_state_branch_1(state, author_user_id=author_user_id)
        if user_meta is None:
            raise ExpectedError(
                status_code=60500,
                message=f"未成功解析到用户信息；author_user_id: {author_user_id}",
            )
        return user_meta.to_dict()


def main() -> None:
    client = UserInfo()

    author_user_id = "61cc36b60000000010005df5"
    result = client.get_user_meta_by_author_user_id(author_user_id)
    print("user_meta by author_user_id:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
