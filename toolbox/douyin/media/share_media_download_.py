#!/usr/bin/python3
# -*- coding: utf-8 -*-
import logging
import re
import json
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional, Union

import requests

from toolbox.utils.utils import when_error

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
    # 桌面 Chrome UA：抖音对移动端 UA 更容易跳到 App 唤起页或风控质询页，
    # 桌面 UA 直出 SSR HTML（含 `_ROUTER_DATA`）的概率更高。
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.douyin.com/",
    }

    # 抖音 share 页面的 PoW 反爬质询页特征：
    # 页面只有 2~3KB，没有 `_ROUTER_DATA`，含 "Please wait..." 与 argus-csp-token 内联脚本，
    # 浏览器侧需要计算 SHA256 工作量证明并写 cookie 才能 reload 拿到真页面，
    # `requests` 无法执行 JS，命中即视为不可解析。
    _ANTI_CRAWL_KEYWORDS: List[str] = [
        "argus-csp-token",
        "Please wait...",
    ]

    def __init__(self) -> None:
        # 用 Session 复用 cookie：预热 douyin.com 拿到 ttwid 等 cookie 后，
        # 后续对 iesdouyin.com/share/... 的请求风险评分会显著降低。
        self._session: Optional[requests.Session] = None
        self._session_warmed: bool = False

    def _ensure_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(self.headers)
        if not self._session_warmed:
            self._warmup_session(self._session)
            self._session_warmed = True
        return self._session

    @classmethod
    def _warmup_session(cls, session: requests.Session) -> None:
        """预热 session：访问抖音主站，让服务端下发 ttwid 等 cookie。

        预热失败不视为致命错误：仅记录 warning，后续仍按"无 cookie"请求继续尝试。
        """
        try:
            session.get("https://www.douyin.com/", timeout=30)
        except requests.RequestException as exc:
            logger.warning(f"douyin warmup session failed: {exc}")

    @classmethod
    def is_anti_crawl_page(cls, html: str) -> bool:
        if not html:
            return True
        if "_ROUTER_DATA" in html:
            return False
        return any(key in html for key in cls._ANTI_CRAWL_KEYWORDS)

    def get_final_url_by_share_url(self, share_url: str) -> str:
        session = self._ensure_session()
        response = session.get(share_url, allow_redirects=True, timeout=30)
        return response.url

    def get_text_by_url(self, url: str) -> str:
        session = self._ensure_session()
        response = session.get(url, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {url}")
        return response.text


class ShareMediaDownload(ShareMediaDownloadRestful):
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
        raise AssertionError(f"no share url found; text: {text}")

    def get_router_data_by_final_url(self, final_url: str) -> Dict[str, Any]:
        html = self.get_text_by_url(final_url)
        if self.is_anti_crawl_page(html):
            logger.warning(f"douyin 命中反爬质询页（Please wait...），无法解析 SSR HTML； url: {final_url}")
            return {}
        pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
        match = pattern.search(html)
        if not match:
            return {}
        raw = (match.group(1) or "").strip()
        if not raw:
            return {}
        try:
            js = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(js, dict):
            return js
        return {}

    def get_aweme_type_and_id_by_final_url(self, final_url: str):
        match = re.search(r"/(video|note|slides)/(\d+)", final_url)
        if match is not None:
            aweme_type = match.group(1)
            aweme_id = match.group(2)
        else:
            # https://www.douyin.com/user/self?modal_id=7641810785078360165
            match = re.search(r"/self?modal_id=(\d+)", final_url)
            aweme_type = "note"
            aweme_id = match.group(1)
        if match is None:
            raise AssertionError(f"can not parse aweme_type and aweme_id; final_url: {final_url}")

        return aweme_type, aweme_id

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        # print(f"share_url: {share_url}")
        final_url = self.get_final_url_by_share_url(share_url)
        # print(f"final_url: {final_url}")

        aweme_type, aweme_id = self.get_aweme_type_and_id_by_final_url(final_url)

        if aweme_type == "slides":
            aweme_type_ = "note"
        else:
            aweme_type_ = aweme_type
        base_url = f"https://www.iesdouyin.com/share/{aweme_type_}/{aweme_id}"
        # 按"最容易直接拿到 SSR HTML"的形态由前到后排，便于在前面就命中并跳出循环。
        # 经验：无尾斜杠 + 无 query 的 base_url 触发反爬质询页的概率最低。
        ordered_candidates = [
            base_url,
            f"{base_url}/",
            final_url.split("?", 1)[0].rstrip("/"),
            final_url.split("?", 1)[0],
            final_url,
        ]
        seen: set = set()
        candidate_urls: List[str] = []
        for url in ordered_candidates:
            if url and url not in seen:
                seen.add(url)
                candidate_urls.append(url)

        post_meta = None
        for url in candidate_urls:
            router_data = self.get_router_data_by_final_url(url)
            if len(router_data) == 0:
                continue
            post_meta = self.build_post_meta_from_router_data_branch_1(router_data)
            if post_meta is not None:
                final_url = url
                break

        if post_meta is None:
            raise AssertionError(f"未成功解析到信息；share_url: {share_url}")
        post_meta.share_url = share_url
        post_meta.final_url = final_url
        return post_meta.to_dict()

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
        # print(json.dumps(router_data, ensure_ascii=False, indent=2))

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

        post_meta.user_id = item["author"]["unique_id"] or item["author"]["short_id"]
        post_meta.nickname = item["author"]["nickname"]

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


def main() -> None:
    client = ShareMediaDownload()

    share_text = """

https://v.douyin.com/Eay4JAHX-8M/

"""
    result = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
