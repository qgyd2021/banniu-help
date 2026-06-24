#!/usr/bin/python3
# -*- coding: utf-8 -*-
import base64
import hashlib
import logging
import re
import json
import sys
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import cacheout
import requests

from toolbox.douyin.homepage.user_info import UserInfo, UserMeta
from toolbox.douyin.utils.cookies import NonceSignRefererUtils
from toolbox.douyin.utils.html_utils import DouyinHtmlUtils
from toolbox.utils.utils import when_error, when_expected_error, ExpectedError

logger = logging.getLogger("toolbox")

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

    platform: str = Field(default="douyin", description="平台标识，如 xiaohongshu/bilibili/douyin 等")
    share_url: str = Field(default="", description="分享链接（短链或原链）")
    final_url: str = Field(default="", description="落地页最终 URL")

    post_id: str = Field(default="", description="贴子 ID")
    post_type: str = Field(default="", description="视频,图文,")

    title: str = Field(default="", description="标题")
    desc: str = Field(default="", description="正文/描述")
    tags: List[str] = Field(default_factory=list, description="标签列表")

    author_user_id: str = Field(default="", description="作者 authorUserId / uid")
    sec_user_id: str = Field(default="", description="作者 secUid")
    unique_id: str = Field(default="", description="作者抖音号（与 user_id 相同）")
    short_id: str = Field(default="", description="作者短 ID")

    user_id: str = Field(default="", description="作者ID（抖音号）")
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


class ShareMediaDownloadRestfulWindows(NonceSignRefererUtils):
    windows_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.douyin.com/",
    }

    def __init__(self) -> None:
        super().__init__()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        _ = session.request(method="GET", url="https://www.douyin.com/", headers=self.windows_headers)
        session.cookies.update(requests.utils.cookiejar_from_dict(self.ac_nonce_signature))
        return session

    def get_final_url_by_share_url(self, share_url: str) -> str:
        session = self._build_session()
        response = session.get(
            share_url,
            headers={
                **self.windows_headers,
                "Referer": "https://www.douyin.com/",
            },
            allow_redirects=True,
            timeout=30,
        )
        return response.url

    def fetch_text_by_url_with_ac(self, url: str, refresh_ac: bool = False) -> str:
        if refresh_ac:
            self.set_nonce_signature()
        session = self._build_session()
        response = session.get(
            url,
            headers={
                **self.windows_headers,
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

    def get_aweme_detail_api_json(self, aweme_id: str, referer: str) -> Dict[str, Any]:
        session = self._build_session()
        response = session.get(
            url="https://www.douyin.com/aweme/v1/web/aweme/detail/",
            headers={
                **self.windows_headers,
                "Referer": referer,
            },
            params={
                "device_platform": "webapp",
                "aid": "6383",
                "channel": "channel_pc_web",
                "version_code": "170400",
                "version_name": "17.4.0",
                "aweme_id": aweme_id,
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, text: {response.text}"
            )
        if len(response.text) == 0:
            raise ExpectedError(status_code=60500, message="empty aweme detail api response")
        js = response.json()
        status_code = js.get("status_code")
        if status_code not in (0, None):
            status_msg = js.get("status_msg") or ""
            raise ExpectedError(
                status_code=60500,
                message=f"aweme detail api failed; status_code: {status_code}, status_msg: {status_msg}",
            )
        return js

    @cacheout.memoize(ttl=10)
    def get_text_by_url(self, url: str) -> Optional[str]:
        response = requests.get(
            url,
            headers=self.windows_headers,
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, text: {response.text}, url: {url}"
            )
        return response.text


class ShareMediaDownloadRestfulIPhone(object):
    iphone_headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.douyin.com/",
    }

    @staticmethod
    def _b64decode_padded(data: str) -> bytes:
        return base64.b64decode(data + "=" * (-len(data) % 4))

    @classmethod
    def _build_waf_challenge_cookie(cls, html: str) -> Optional[str]:
        if "Please wait..." not in html or 'cs="' not in html:
            return None
        match = re.search(r'cs="([^"]+)"', html)
        if match is None:
            return None

        challenge = json.loads(cls._b64decode_padded(match.group(1)))
        prefix = cls._b64decode_padded(challenge["v"]["a"])
        expect_hex = cls._b64decode_padded(challenge["v"]["c"]).hex()
        for i in range(1_000_001):
            if hashlib.sha256(prefix + str(i).encode()).hexdigest() == expect_hex:
                challenge["d"] = base64.b64encode(str(i).encode()).decode()
                return base64.b64encode(
                    json.dumps(challenge, separators=(",", ":")).encode()
                ).decode()
        return None

    def fetch_text_by_url(self, url: str) -> str:
        headers = self.iphone_headers
        session = requests.Session()
        response = session.get(
            url,
            headers=headers,
            allow_redirects=True,
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, text: {response.text}, url: {url}"
            )

        waf_cookie = self._build_waf_challenge_cookie(response.text)
        if waf_cookie is not None:
            hostname = urlparse(url).hostname or ""
            session.cookies.set("_wafchallengeid", waf_cookie, domain=hostname)
            response = session.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=30,
            )
            if response.status_code != 200:
                raise AssertionError(
                    f"request failed; status_code: {response.status_code}, text: {response.text}, url: {url}"
                )

        return response.text


class ShareMediaDownloadRestful(DouyinHtmlUtils, ShareMediaDownloadRestfulWindows, ShareMediaDownloadRestfulIPhone):
    is_anti_crawl_page = DouyinHtmlUtils.is_anti_crawl_aweme_page

    def build_page_url_candidates(self, share_url: str, final_url: str, aweme_id: str) -> List[str]:
        if not share_url:
            raise AssertionError("share_url is empty")
        if not final_url:
            raise AssertionError("final_url is empty")
        if not aweme_id:
            raise AssertionError("aweme_id is empty")

        page_url_set: set[str] = {
            final_url,
            share_url,
            f"https://www.iesdouyin.com/share/video/{aweme_id}/",
            f"https://www.douyin.com/video/{aweme_id}",
            f"https://www.douyin.com/note/{aweme_id}",
            f"https://www.douyin.com/user/self?modal_id={aweme_id}",
        }
        return list(page_url_set)

    def iter_page_html_candidates(self, share_url: str, final_url: str, aweme_id: str) -> Iterator[Tuple[str, str]]:
        seen: set[Tuple[int, str]] = set()

        for page_url in self.build_page_url_candidates(share_url, final_url, aweme_id):
            html = self.fetch_text_by_url(page_url)
            key = (len(html), page_url)
            if key not in seen:
                seen.add(key)
                yield html, page_url

            html = self.fetch_text_by_url_with_ac(page_url)
            key = (len(html), page_url)
            if key not in seen:
                seen.add(key)
                yield html, page_url

            html = self.fetch_text_by_url_with_ac(page_url, refresh_ac=True)
            key = (len(html), page_url)
            if key not in seen:
                seen.add(key)
                yield html, page_url

            html = self.get_text_by_url(page_url)
            if html:
                key = (len(html), page_url)
                if key not in seen:
                    seen.add(key)
                    yield html, page_url


class ShareMediaDownload(ShareMediaDownloadRestful):
    def __init__(self) -> None:
        super().__init__()
        self.user_info = UserInfo()

    @staticmethod
    def apply_user_meta_to_post_meta(
        post_meta: PostMeta,
        user_meta: Optional[UserMeta],
    ) -> PostMeta:
        if user_meta is None:
            return post_meta
        if user_meta.author_user_id:
            post_meta.author_user_id = str(user_meta.author_user_id)
        if user_meta.sec_uid:
            post_meta.sec_user_id = str(user_meta.sec_uid)
        if user_meta.short_id:
            post_meta.short_id = str(user_meta.short_id)
        if user_meta.nickname:
            post_meta.nickname = str(user_meta.nickname)
        if user_meta.unique_id:
            post_meta.user_id = user_meta.unique_id
            post_meta.unique_id = user_meta.unique_id
        return post_meta

    @when_error(return_value=None)
    def get_user_meta_by_post_meta(self, post_meta: PostMeta) -> Optional[UserMeta]:
        if not post_meta.sec_user_id and not post_meta.author_user_id:
            return None
        if post_meta.sec_user_id:
            user_meta_dict = self.user_info.get_user_meta_by_sec_uid(post_meta.sec_user_id)
        else:
            user_meta_dict = self.user_info.get_user_meta_by_author_user_id(post_meta.author_user_id)
        if user_meta_dict is None:
            return None
        result = UserMeta.from_dict(user_meta_dict)
        return result

    @staticmethod
    def get_share_url_by_share_text(text: str) -> str:
        patterns = [
            r"https://v\.douyin\.com/[A-Za-z0-9_\-]+/",
            r"https?://www\.douyin\.com/[^\s]+",
            r"https?://www\.iesdouyin\.com/[^\s]+",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is not None:
                return match.group(0).rstrip(".,;)")
        raise ExpectedError(status_code=60500, message="no share url found; text: {text}")

    @staticmethod
    @when_error(return_value=None)
    def get_aweme_by_html(html: str) -> str:
        pattern = re.compile(
            r"<script[^>]*>\s*self\.__pace_f\.push\((.*?)\)\s*</script>",
            flags=re.DOTALL,
        )
        for match in pattern.finditer(html):
            raw_call_args = (match.group(1) or "").strip()
            if "awemeId" not in raw_call_args or "authorInfo" not in raw_call_args:
                continue
            try:
                call_args = json.loads(raw_call_args)
            except json.JSONDecodeError:
                continue
            if not isinstance(call_args, list) or len(call_args) < 2:
                continue
            payload = call_args[1]
            if not isinstance(payload, str) or "awemeId" not in payload:
                continue
            # payload 形如：7:[...json...]，冒号前是 React Flight 行号。
            if ":" not in payload:
                continue
            _, payload_json = payload.split(":", 1)
            try:
                data = json.loads(payload_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, list) or len(data) < 4 or not isinstance(data[3], dict):
                continue
            aweme = data[3].get("aweme")
            if not isinstance(aweme, dict):
                continue
            detail = aweme.get("detail")
            if not isinstance(detail, dict):
                continue
            result = detail
            # result = json.dumps(detail, ensure_ascii=False, indent=2)
            return result
        return None

    @when_error(return_value=None)
    def get_router_data_by_html(self, html: str) -> Dict[str, Any]:
        pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
        match = pattern.search(html)
        if match is None:
            return None
        raw = match.group(1)
        js = json.loads(raw)
        return js

    def get_aweme_type_and_id_by_final_url(self, final_url: str) -> Tuple[str, str]:
        match = re.search(r"/(video|note|slides)/(\d+)", final_url)
        if match is not None:
            return match.group(1), match.group(2)

        match = re.search(r"[?&]modal_id=(\d+)", final_url)
        if match is not None:
            return "note", match.group(1)

        if re.search(r"(?:jinritemai|haohuo)\.", final_url, re.I):
            raise ExpectedError(
                status_code=60500,
                message=f"该链接为抖音商城商品页，非视频/图文作品；final_url: {final_url}",
            )

        raise ExpectedError(
            status_code=60500,
            message=f"无法从落地页解析 aweme_id；final_url: {final_url}",
        )

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        result = self.get_post_meta_by_share_url(share_url)
        return result

    @when_expected_error(return_value=None)
    def get_post_meta_by_share_url(self, share_url: str) -> dict:
        final_url = self.get_final_url_by_share_url(share_url)
        _, aweme_id = self.get_aweme_type_and_id_by_final_url(final_url)

        post_meta = None
        resolved_final_url = final_url
        for html, page_url in self.iter_page_html_candidates(share_url, final_url, aweme_id):
            if self.is_anti_crawl_page(html):
                continue
            post_meta = self.get_post_meta_from_html(html)
            if post_meta is not None:
                resolved_final_url = page_url
                break

        if post_meta is None:
            for referer in self.build_page_url_candidates(share_url, final_url, aweme_id):
                post_meta = self.get_post_meta_from_aweme_detail_api(aweme_id, referer)
                if post_meta is not None:
                    resolved_final_url = referer
                    break

        if post_meta is None:
            raise ExpectedError(status_code=60500, message=f"未成功解析到信息；share_url: {share_url}")

        post_meta.share_url = share_url
        post_meta.final_url = resolved_final_url

        user_meta = self.get_user_meta_by_post_meta(post_meta)
        post_meta = self.apply_user_meta_to_post_meta(post_meta, user_meta)
        return post_meta.to_dict()

    def get_post_meta_from_html(self, html: str) -> Optional[PostMeta]:
        aweme = self.get_aweme_by_html(html)
        if aweme is not None:
            post_meta = self.build_post_meta_from_aweme_branch_1(aweme)
            if post_meta is not None:
                return post_meta

        router_data = self.get_router_data_by_html(html)
        if router_data is not None:
            post_meta = self.build_post_meta_from_router_data_branch_1(router_data)
            if post_meta is not None:
                return post_meta
            post_meta = self.build_post_meta_from_router_data_branch_2(router_data)
            if post_meta is not None:
                return post_meta
        return None

    @when_error(return_value=None)
    def get_post_meta_from_aweme_detail_api(self, aweme_id: str, referer: str) -> Optional[PostMeta]:
        js = self.get_aweme_detail_api_json(aweme_id=aweme_id, referer=referer)
        if "aweme_detail" in js:
            aweme = js["aweme_detail"]
        else:
            aweme = js["aweme"]
        if not isinstance(aweme, dict):
            return None
        return self.build_post_meta_from_aweme_detail_api_branch_1(aweme)

    @when_error(return_value=None)
    def build_post_meta_from_router_data_branch_1(self, router_data: dict) -> PostMeta:
        """
        轮播图。
        6.43 03/31 ChB:/ M@J.vs :4pm # 迈从# 迈从A7V2  https://v.douyin.com/RBdz7bIx6f4/ 复制此链接，打开Dou音搜索，直接观看视频！

        视频。
        9.23 e@b.Ag :0pm YZM:/ 02/01 新键盘# 迈从# 迈从Ace68v2  https://v.douyin.com/FfKNyQ5-Ymc/ 复制此链接，打开Dou音搜索，直接观看视频！

        https://v.douyin.com/1uPUI8rT3BA/

        # 你观看的图文不存在。
        https://v.douyin.com/9Ucbd_kd-JI/

        """
        # print(f"router_data: {json.dumps(router_data, ensure_ascii=False, indent=2)}")

        loader_data: dict = router_data.get("loaderData")
        if loader_data is None:
            return None
        # print(json.dumps(loader_data, ensure_ascii=False, indent=2))

        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_router_data_for_slides_branch_1"

        item = None
        for _, v in loader_data.items():
            if not isinstance(v, dict):
                continue
            video_info_res: dict = v.get("videoInfoRes")
            if video_info_res is None:
                continue
            item_list = video_info_res["item_list"]
            if len(item_list) == 0:
                filter_list = video_info_res["filter_list"]
                if len(filter_list) != 0:
                    f = filter_list[0]
                    # print(f"f: {json.dumps(f, ensure_ascii=False, indent=2)}")

                    msg = f.get("detail_msg") or f.get("filter_reason")
                    # post_meta.post_id = f.get("aweme_id") or ""
                    post_meta.post_id = f["aweme_id"]
                    post_meta.title = msg
                    post_meta.desc = msg
                    return post_meta
            item = video_info_res["item_list"][0]

        # print(json.dumps(item, ensure_ascii=False, indent=2))
        aweme_type = item["aweme_type"]
        # aweme_type, 2 轮播图， 4 视频，
        # print(f"aweme_type: {aweme_type}")

        desc = item["desc"]
        tags = [e["hashtag_name"] for e in item["text_extra"]]
        tags = [tag for tag in tags if len(str(tag).strip()) > 0]
        tags = list(sorted(tags, key=len, reverse=True))
        for tag in tags:
            desc = desc.lower().replace(f"#{str(tag).lower()}", "").strip()

        post_meta.post_id = item["aweme_id"]
        post_meta.title = ""
        post_meta.desc = desc
        post_meta.tags = tags

        author = item["author"]
        post_meta.author_user_id = str(author["uid"])
        post_meta.sec_user_id = str(author["sec_uid"])
        post_meta.short_id = str(author["short_id"])
        post_meta.nickname = str(author["nickname"])

        post_meta.liked_count = item["statistics"]["digg_count"]
        post_meta.collected_count = item["statistics"]["collect_count"]
        post_meta.comment_count = item["statistics"]["comment_count"]
        post_meta.share_count = item["statistics"]["share_count"]

        if aweme_type not in (4,):
            image_urls = list()
            for image in item["images"]:
                image_urls.append(image["url_list"][0])
            post_meta.image_urls = image_urls

        if aweme_type not in (2,):
            video_url = item["video"]["play_addr"]["url_list"][0]
            video_url = video_url.replace("playwm", "play")
            cover_url = item["video"]["cover"]["url_list"][0]
            video_urls = [
                VideoMeta(cover_url=cover_url, video_url=video_url),
            ]
            post_meta.video_urls = video_urls

        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_router_data_branch_2(self, router_data: dict) -> PostMeta:
        """
        iesdouyin 移动端 _ROUTER_DATA；author 无 uid，仅有 sec_uid。
        https://v.douyin.com/bex4cW-lzxw/
        """
        loader_data: dict = router_data.get("loaderData")
        if loader_data is None:
            return None

        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_router_data_branch_2"

        item = None
        for _, v in loader_data.items():
            if not isinstance(v, dict):
                continue
            video_info_res: dict = v.get("videoInfoRes")
            if video_info_res is None:
                continue
            item_list = video_info_res["item_list"]
            if len(item_list) == 0:
                filter_list = video_info_res["filter_list"]
                if len(filter_list) != 0:
                    f = filter_list[0]
                    msg = f.get("detail_msg") or f.get("filter_reason")
                    post_meta.post_id = f["aweme_id"]
                    post_meta.title = msg
                    post_meta.desc = msg
                    return post_meta
            item = video_info_res["item_list"][0]

        aweme_type = item["aweme_type"]
        desc = item["desc"]
        tags = [e["hashtag_name"] for e in item["text_extra"]]
        tags = [tag for tag in tags if len(str(tag).strip()) > 0]
        tags = list(sorted(tags, key=len, reverse=True))
        for tag in tags:
            desc = desc.lower().replace(f"#{str(tag).lower()}", "").strip()

        post_meta.post_id = item["aweme_id"]
        post_meta.title = ""
        post_meta.desc = desc
        post_meta.tags = tags

        author = item["author"]
        post_meta.sec_user_id = str(author["sec_uid"])
        post_meta.short_id = str(author["short_id"])
        post_meta.nickname = str(author["nickname"])

        post_meta.liked_count = item["statistics"]["digg_count"]
        post_meta.collected_count = item["statistics"]["collect_count"]
        post_meta.comment_count = item["statistics"]["comment_count"]
        post_meta.share_count = item["statistics"]["share_count"]

        if aweme_type not in (4,):
            image_urls = list()
            for image in item["images"]:
                image_urls.append(image["url_list"][0])
            post_meta.image_urls = image_urls

        if aweme_type not in (2,):
            video_url = item["video"]["play_addr"]["url_list"][0]
            video_url = video_url.replace("playwm", "play")
            cover_url = item["video"]["cover"]["url_list"][0]
            post_meta.video_urls = [
                VideoMeta(cover_url=cover_url, video_url=video_url),
            ]

        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_aweme_detail_api_branch_1(self, aweme: dict) -> PostMeta:
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_aweme_detail_api_branch_1"

        aweme_type = aweme["aweme_type"]
        desc = aweme["desc"]
        tags = [
            e["hashtag_name"]
            for e in aweme["text_extra"]
            if e.get("hashtag_name")
        ]
        tags = [tag for tag in tags if len(str(tag).strip()) > 0]
        tags = list(sorted(tags, key=len, reverse=True))
        for tag in tags:
            desc = desc.lower().replace(f"#{str(tag).lower()}", "").strip()

        post_meta.post_id = str(aweme["aweme_id"])
        post_meta.title = ""
        post_meta.desc = desc
        post_meta.tags = tags

        author = aweme["author"]
        post_meta.author_user_id = str(author["uid"])
        post_meta.sec_user_id = str(author["sec_uid"])
        post_meta.short_id = str(author["short_id"])
        post_meta.nickname = str(author["nickname"])

        statistics = aweme["statistics"]
        post_meta.liked_count = statistics["digg_count"]
        post_meta.collected_count = statistics["collect_count"]
        post_meta.comment_count = statistics["comment_count"]
        post_meta.share_count = statistics["share_count"]

        images = aweme.get("images")
        if images:
            image_urls = list()
            for image in images:
                image_urls.append(image["url_list"][0])
            post_meta.image_urls = image_urls

        video = aweme.get("video")
        if video is not None:
            video_url = video["play_addr"]["url_list"][0]
            video_url = video_url.replace("playwm", "play")
            cover_url = video["cover"]["url_list"][0]
            post_meta.video_urls = [
                VideoMeta(cover_url=cover_url, video_url=video_url),
            ]

        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_aweme_branch_1(self, aweme: dict) -> PostMeta:
        """
        https://v.douyin.com/Eay4JAHX-8M/
        """
        # print(f"aweme: {json.dumps(aweme, ensure_ascii=False, indent=2)}")

        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_aweme_branch_1"

        aweme_type = aweme["awemeType"]
        # aweme_type, 68 轮播图
        # print(f"aweme_type: {aweme_type}")

        desc = aweme["desc"]
        tags = [e["hashtagName"] for e in aweme["textExtra"]]
        tags = [tag for tag in tags if len(str(tag).strip()) > 0]
        tags = list(sorted(tags, key=len, reverse=True))
        for tag in tags:
            desc = desc.lower().replace(f"#{str(tag).lower()}", "").strip()

        post_meta.post_id = aweme["awemeId"]
        post_meta.title = ""
        post_meta.desc = desc
        post_meta.tags = tags

        author_info = aweme["authorInfo"]
        post_meta.author_user_id = str(author_info["uid"])
        post_meta.sec_user_id = str(author_info["secUid"])
        post_meta.short_id = str(author_info["shortId"])
        post_meta.nickname = str(author_info["nickname"])

        post_meta.liked_count = aweme["stats"]["diggCount"]
        post_meta.collected_count = aweme["stats"]["collectCount"]
        post_meta.comment_count = aweme["stats"]["commentCount"]
        post_meta.share_count = aweme["stats"]["shareCount"]

        if aweme_type not in (4,):
            image_urls = list()
            for image in aweme["images"]:
                image_urls.append(image["urlList"][0])
            post_meta.image_urls = image_urls

        if aweme_type not in (68,):
            video_url = aweme["video"]["playAddr"]["urlList"][0]
            video_url = video_url.replace("playwm", "play")
            cover_url = aweme["video"]["cover"]["urlList"][0]
            video_urls = [
                VideoMeta(cover_url=cover_url, video_url=video_url),
            ]
            post_meta.video_urls = video_urls

        return post_meta


def main() -> None:
    client = ShareMediaDownload()

    share_text = """

9.79 # 迈从ace68 v2超竟版  https://v.douyin.com/URlpJmI78MI/ 复制此链接，打开抖音搜索，直接观看视频！ trR:/ :8pm 04/02 b@a.an

"""
    post_meta = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    sys.stdout.buffer.write(
        (json.dumps(post_meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


if __name__ == "__main__":
    main()
