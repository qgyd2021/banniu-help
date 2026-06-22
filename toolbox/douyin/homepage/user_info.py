#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

import cacheout
import requests
from pydantic import BaseModel, ConfigDict, Field

from toolbox.douyin.utils.cookies import NonceSignRefererUtils
from toolbox.utils.exception import ExpectedError
from toolbox.utils.utils import when_error, when_expected_error

logger = logging.getLogger("toolbox")

CountValue = Union[int, float, str]


class UserMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    platform: str = Field(default="douyin", description="平台标识")
    sec_uid: str = Field(default="", description="用户 secUid")
    author_user_id: str = Field(default="", description="用户 authorUserId / uid")
    unique_id: str = Field(default="", description="抖音号")
    short_id: str = Field(default="", description="短 ID")
    nickname: str = Field(default="", description="昵称")
    signature: str = Field(default="", description="个性签名")

    follower_count: CountValue = Field(default="", description="粉丝数")
    following_count: CountValue = Field(default="", description="关注数")
    aweme_count: CountValue = Field(default="", description="作品数")
    total_favorited: CountValue = Field(default="", description="获赞总数")
    favoriting_count: CountValue = Field(default="", description="喜欢数")

    avatar_url: str = Field(default="", description="头像 URL")
    profile_url: str = Field(default="", description="主页 URL")
    source: str = Field(default="", description="数据来源分支")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMeta":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class UserInfoRestful(NonceSignRefererUtils):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.douyin.com/",
    }

    _PROFILE_API_URL = "https://www.douyin.com/aweme/v1/web/user/profile/other/"
    _LIVE_USER_API_URL = "https://live.douyin.com/webcast/user/"
    _PROFILE_API_PARAMS = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "publish_video_strategy_type": "2",
        "source": "channel_pc_web",
        "version_code": "170400",
        "version_name": "17.4.0",
        "pc_client_type": "1",
        "cookie_enabled": "true",
        "browser_language": "zh-CN",
        "browser_online": "true",
    }

    _ANTI_CRAWL_KEYWORDS: List[str] = [
        "argus-csp-token",
        "Please wait...",
    ]

    def __init__(self) -> None:
        super().__init__()

    @classmethod
    def is_anti_crawl_page(cls, html: str) -> bool:
        if not html:
            return True
        if "secUid" in html or "followerCount" in html or "follower_count" in html:
            return False
        return any(key in html for key in cls._ANTI_CRAWL_KEYWORDS)

    @staticmethod
    def build_user_profile_url(sec_uid: str = "", author_user_id: str = "") -> str:
        if sec_uid:
            return f"https://www.douyin.com/user/{sec_uid}"
        if author_user_id:
            return f"https://www.douyin.com/user/{author_user_id}"
        return "https://www.douyin.com/"

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        _ = session.request(method="GET", url="https://www.douyin.com/", headers=self.headers)
        session.cookies.update(requests.utils.cookiejar_from_dict(self.ac_nonce_signature))
        return session

    @cacheout.memoize(ttl=10)
    def get_text_by_url_with_ac(self, url: str) -> str:
        session = self._build_session()
        response = session.get(
            url,
            headers={
                **self.headers,
                "Referer": url,
            },
            allow_redirects=True,
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, text: {response.text}, url: {url}"
            )
        return response.text

    def get_profile_api_json(self, params: Dict[str, str], referer: str) -> Dict[str, Any]:
        session = self._build_session()
        response = session.get(
            self._PROFILE_API_URL,
            headers={
                **self.headers,
                "Referer": referer,
            },
            params={
                **self._PROFILE_API_PARAMS,
                **params,
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, text: {response.text}"
            )
        if len(response.text) == 0:
            raise ExpectedError(status_code=60500, message="empty profile api response")
        js = response.json()
        status_code = js.get("status_code")
        if status_code not in (0, None):
            status_msg = js.get("status_msg") or ""
            raise ExpectedError(
                status_code=60500,
                message=f"profile api failed; status_code: {status_code}, status_msg: {status_msg}",
            )
        return js

    def get_live_user_api_json(
        self,
        author_user_id: str = "",
        sec_uid: str = "",
    ) -> Dict[str, Any]:
        if sec_uid:
            params = {
                "aid": "6383",
                "sec_target_uid": sec_uid,
            }
            referer = self.build_user_profile_url(sec_uid=sec_uid)
        else:
            author_user_id = str(author_user_id or "").strip()
            params = {
                "aid": "6383",
                "target_uid": author_user_id,
            }
            referer = f"https://live.douyin.com/{author_user_id}"
        session = self._build_session()
        response = session.get(
            self._LIVE_USER_API_URL,
            headers={
                **self.headers,
                "Referer": referer,
            },
            params=params,
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, text: {response.text}"
            )
        if len(response.text) == 0:
            raise ExpectedError(status_code=60500, message="empty live user api response")
        js = response.json()
        status_code = js.get("status_code")
        if status_code not in (0, None):
            status_msg = js.get("status_msg") or ""
            raise ExpectedError(
                status_code=60500,
                message=f"live user api failed; status_code: {status_code}, status_msg: {status_msg}",
            )
        data = js.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise ExpectedError(status_code=60500, message="live user api has no user data")
        return data


class UserInfo(UserInfoRestful):
    @staticmethod
    @when_error(return_value=None)
    def get_user_by_html(html: str) -> Optional[Dict[str, Any]]:
        pattern = re.compile(
            r"<script[^>]*>\s*self\.__pace_f\.push\((.*?)\)\s*</script>",
            flags=re.DOTALL,
        )
        for match in pattern.finditer(html):
            raw_call_args = (match.group(1) or "").strip()
            if "secUid" not in raw_call_args or "followerCount" not in raw_call_args:
                continue
            try:
                call_args = json.loads(raw_call_args)
            except json.JSONDecodeError:
                continue
            if not isinstance(call_args, list) or len(call_args) < 2:
                continue
            payload = call_args[1]
            if not isinstance(payload, str) or ":" not in payload:
                continue
            _, payload_json = payload.split(":", 1)
            try:
                data = json.loads(payload_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, list) or len(data) < 4 or not isinstance(data[3], dict):
                continue
            user_wrap = data[3].get("user")
            if not isinstance(user_wrap, dict):
                continue
            user = user_wrap.get("user")
            if isinstance(user, dict) and user.get("uid"):
                return user
        return None

    @when_error(return_value=None)
    def build_user_meta_from_html_branch_1(self, user: Dict[str, Any], sec_uid: str = "") -> UserMeta:
        user_meta = UserMeta()
        user_meta.source = "build_user_meta_from_html_branch_1"
        user_meta.sec_uid = str(user.get("secUid") or sec_uid or "")
        user_meta.author_user_id = str(user.get("uid") or "")
        user_meta.unique_id = str(user.get("uniqueId") or "")
        user_meta.short_id = str(user.get("shortId") or "")
        user_meta.nickname = str(user.get("nickname") or "")
        user_meta.signature = str(user.get("desc") or user.get("signature") or "")

        user_meta.follower_count = user.get("followerCount", "")
        user_meta.following_count = user.get("followingCount", "")
        user_meta.aweme_count = user.get("awemeCount", "")
        user_meta.total_favorited = user.get("totalFavorited", "")
        user_meta.favoriting_count = user.get("favoritingCount", "")

        avatar_url = user.get("avatarUrl") or ""
        if not avatar_url:
            avatar = user.get("avatar_thumb") or user.get("avatarThumb") or {}
            if isinstance(avatar, dict):
                url_list = avatar.get("url_list") or avatar.get("urlList") or []
                if url_list:
                    avatar_url = url_list[0]
        user_meta.avatar_url = str(avatar_url or "")
        user_meta.profile_url = self.build_user_profile_url(sec_uid=user_meta.sec_uid)
        return user_meta

    @when_error(return_value=None)
    def build_user_meta_from_api_branch_1(self, user: Dict[str, Any]) -> UserMeta:
        user_meta = UserMeta()
        user_meta.source = "build_user_meta_from_api_branch_1"
        user_meta.sec_uid = str(user.get("sec_uid") or user.get("secUid") or "")
        user_meta.author_user_id = str(user.get("uid") or "")
        user_meta.unique_id = str(user.get("unique_id") or user.get("uniqueId") or "")
        user_meta.short_id = str(user.get("short_id") or user.get("shortId") or "")
        user_meta.nickname = str(user.get("nickname") or "")
        user_meta.signature = str(user.get("signature") or "")

        user_meta.follower_count = user.get("follower_count", user.get("followerCount", ""))
        user_meta.following_count = user.get("following_count", user.get("followingCount", ""))
        user_meta.aweme_count = user.get("aweme_count", user.get("awemeCount", ""))
        user_meta.total_favorited = user.get("total_favorited", user.get("totalFavorited", ""))
        user_meta.favoriting_count = user.get("favoriting_count", user.get("favoritingCount", ""))

        avatar_url = ""
        avatar = user.get("avatar_thumb") or user.get("avatarThumb") or {}
        if isinstance(avatar, dict):
            url_list = avatar.get("url_list") or avatar.get("urlList") or []
            if url_list:
                avatar_url = url_list[0]
        if not avatar_url:
            avatar_larger = user.get("avatar_larger") or user.get("avatarLarger") or {}
            if isinstance(avatar_larger, dict):
                url_list = avatar_larger.get("url_list") or avatar_larger.get("urlList") or []
                if url_list:
                    avatar_url = url_list[0]
        user_meta.avatar_url = str(avatar_url or "")
        user_meta.profile_url = self.build_user_profile_url(
            sec_uid=user_meta.sec_uid,
            author_user_id=user_meta.author_user_id,
        )
        return user_meta

    @when_expected_error(return_value=None)
    def _get_user_meta_from_profile_api(
        self,
        params: Dict[str, str],
        referer: str,
    ) -> Optional[UserMeta]:
        js = self.get_profile_api_json(params=params, referer=referer)
        user = js.get("user")
        if isinstance(user, dict) and user.get("uid"):
            return self.build_user_meta_from_api_branch_1(user)
        return None

    @when_expected_error(return_value=None)
    def _get_user_meta_from_live_api_by_sec_uid(self, sec_uid: str) -> Optional[UserMeta]:
        live_user = self.get_live_user_api_json(sec_uid=sec_uid)
        author_user_id = str(live_user.get("id") or "")
        if author_user_id:
            user_meta = self._get_user_meta_from_profile_api(
                params={"user_id": author_user_id},
                referer=self.build_user_profile_url(author_user_id=author_user_id),
            )
            if user_meta is not None:
                user_meta.sec_uid = str(live_user.get("sec_uid") or sec_uid)
                return user_meta
        return self.build_user_meta_from_live_api_branch_1(live_user)

    @when_expected_error(return_value=None)
    def _get_user_meta_from_live_api(self, author_user_id: str) -> Optional[UserMeta]:
        live_user = self.get_live_user_api_json(author_user_id=author_user_id)
        sec_uid = str(live_user.get("sec_uid") or "")
        if sec_uid:
            profile_url = self.build_user_profile_url(sec_uid=sec_uid)
            html = self.get_text_by_url_with_ac(profile_url)
            if html and not self.is_anti_crawl_page(html):
                user = self.get_user_by_html(html)
                if user is not None:
                    user_meta = self.build_user_meta_from_html_branch_1(user, sec_uid=sec_uid)
                    if user_meta is not None:
                        return user_meta
            user_meta = self._get_user_meta_from_profile_api(
                params={"sec_user_id": sec_uid},
                referer=profile_url,
            )
            if user_meta is not None:
                return user_meta
        return self.build_user_meta_from_live_api_branch_1(live_user)

    @when_expected_error(return_value=None)
    def get_user_meta_by_sec_uid(self, sec_uid: str) -> Optional[Dict[str, Any]]:
        sec_uid = str(sec_uid or "").strip()
        if not sec_uid:
            raise ExpectedError(status_code=60500, message="sec_uid is empty")

        user_meta = None
        profile_url = self.build_user_profile_url(sec_uid=sec_uid)

        if user_meta is None:
            html = self.get_text_by_url_with_ac(profile_url)
            if html and not self.is_anti_crawl_page(html):
                user = self.get_user_by_html(html)
                if user is not None:
                    user_meta = self.build_user_meta_from_html_branch_1(user, sec_uid=sec_uid)

        if user_meta is None:
            user_meta = self._get_user_meta_from_profile_api(
                params={"sec_user_id": sec_uid},
                referer=profile_url,
            )

        if user_meta is None:
            user_meta = self._get_user_meta_from_live_api_by_sec_uid(sec_uid)

        if user_meta is None:
            raise ExpectedError(status_code=60500, message=f"未成功解析到用户信息；sec_uid: {sec_uid}")

        user_meta.profile_url = profile_url
        return user_meta.to_dict()

    @when_expected_error(return_value=None)
    def get_user_meta_by_author_user_id(self, author_user_id: str) -> Optional[Dict[str, Any]]:
        author_user_id = str(author_user_id or "").strip()
        if not author_user_id:
            raise ExpectedError(status_code=60500, message="author_user_id is empty")

        profile_url = self.build_user_profile_url(author_user_id=author_user_id)
        user_meta = None

        if user_meta is None:
            user_meta = self._get_user_meta_from_profile_api(
                params={"user_id": author_user_id},
                referer=profile_url,
            )

        if user_meta is None:
            user_meta = self._get_user_meta_from_live_api(author_user_id)

        if user_meta is None:
            raise ExpectedError(
                status_code=60500,
                message=f"未成功解析到用户信息；author_user_id: {author_user_id}",
            )

        user_meta.profile_url = self.build_user_profile_url(
            sec_uid=user_meta.sec_uid,
            author_user_id=user_meta.author_user_id or author_user_id,
        )
        return user_meta.to_dict()

    @when_error(return_value=None)
    def build_user_meta_from_live_api_branch_1(self, user: Dict[str, Any]) -> UserMeta:
        user_meta = UserMeta()
        user_meta.source = "build_user_meta_from_live_api_branch_1"
        user_meta.sec_uid = str(user.get("sec_uid") or "")
        user_meta.author_user_id = str(user.get("id") or user.get("id_str") or "")
        user_meta.unique_id = str(user.get("display_id") or "")
        user_meta.short_id = str(user.get("short_id") or "")
        user_meta.nickname = str(user.get("nickname") or "")
        user_meta.signature = str(user.get("signature") or "")

        follow_info = user.get("follow_info") or {}
        if isinstance(follow_info, dict):
            user_meta.follower_count = follow_info.get("follower_count", "")
            user_meta.following_count = follow_info.get("following_count", "")

        avatar_url = ""
        avatar = user.get("avatar_thumb") or {}
        if isinstance(avatar, dict):
            url_list = avatar.get("url_list") or []
            if url_list:
                avatar_url = url_list[0]
        user_meta.avatar_url = str(avatar_url or "")
        user_meta.profile_url = self.build_user_profile_url(
            sec_uid=user_meta.sec_uid,
            author_user_id=user_meta.author_user_id,
        )
        return user_meta


def main() -> None:
    client = UserInfo()

    sec_uid = "MS4wLjABAAAAf0qOK8d42d4y5nAFzm-MOI31El_mtLMIR6M-TmewcZDtJOM54w9gx9cmIDDpByFJ"
    result = client.get_user_meta_by_sec_uid(sec_uid)
    print("user_meta by sec_uid:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    author_user_id = "4037051124577773"
    result = client.get_user_meta_by_author_user_id(author_user_id)
    print("user_meta by author_user_id:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
