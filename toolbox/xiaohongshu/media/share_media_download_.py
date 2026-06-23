#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
小红书分享解析（与 toolbox/weibo/media/share_media_download_.py、
toolbox/kuaishou/media/share_media_download_.py、
toolbox/douyin/media/share_media_download_.py 风格对齐）。

逻辑参考 toolbox/xiaohongshu/media/share_media_download.py：

1. 从分享文案中抓出一条小红书分享入口链接
   （xhslink.com 短链 / xiaohongshu.com / rednote.com）；
2. 跟跳到落地页（一般是 ``https://www.xiaohongshu.com/discovery/item/<note_id>?...``
   或 ``/explore/<note_id>?...``）；
3. 从 HTML 内嵌脚本中抽出 ``window.__INITIAL_STATE__`` JSON；
4. 在 ``note.noteDetailMap[note_id].note`` 中取该笔记数据；
5. 根据 ``note["type"]`` 分支：
   - ``normal``：图文笔记（分支 1）；
   - ``video``：视频笔记（分支 2）；
6. 映射到统一的 ``PostMeta``。
"""
import json
import re
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from toolbox.xiaohongshu.homepage.user_info import UserInfo, UserMeta
from toolbox.utils.utils import when_error, when_expected_error, ExpectedError

CountValue = Union[int, float, str]


class VideoMeta(BaseModel):
    cover_url: str = Field(default="", description="封面 URL")
    video_url: str = Field(default="", description="视频 URL")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoMeta":
        return cls.model_validate(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class PostMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    platform: str = Field(default="xiaohongshu", description="平台标识，如 xiaohongshu/bilibili/douyin 等")
    share_url: str = Field(default="", description="分享链接（短链或原链）")
    final_url: str = Field(default="", description="落地页最终 URL")

    post_id: str = Field(default="", description="贴子 ID")
    post_type: str = Field(default="", description="视频,图文,")

    title: str = Field(default="", description="标题")
    desc: str = Field(default="", description="正文/描述")
    tags: List[str] = Field(default_factory=list, description="标签列表")

    author_user_id: str = Field(default="", description="作者 userId")
    unique_id: str = Field(default="", description="作者小红书号（与 user_id 相同）")

    user_id: str = Field(default="", description="作者小红书号")
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
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.xiaohongshu.com/",
    }

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(self.headers)

    def warmup_session(self) -> None:
        self._session.get("https://www.xiaohongshu.com/", allow_redirects=True, timeout=30)

    def fetch_html_by_url(self, url: str) -> Tuple[str, str]:
        response = self._session.get(url, allow_redirects=True, timeout=30)
        return response.text, response.url

    def get_html_and_final_url_by_share_url(self, share_url: str) -> Tuple[str, str]:
        self.warmup_session()
        return self.fetch_html_by_url(share_url)

    def get_text_by_url(self, url: str) -> str:
        self.warmup_session()
        html, _ = self.fetch_html_by_url(url)
        return html


class ShareMediaDownload(ShareMediaDownloadRestful):
    _SHARE_ENTRY_URL_PATTERNS: List[str] = [
        r"https?://xhslink\.com/[A-Za-z0-9/_\-]+",
        r"https?://(?:www\.)?xiaohongshu\.com/[^\s]+",
        r"https?://(?:www\.)?rednote\.com/[^\s]+",
    ]

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
        if user_meta.nickname:
            post_meta.nickname = str(user_meta.nickname)
        if user_meta.unique_id:
            post_meta.user_id = str(user_meta.unique_id)
            post_meta.unique_id = str(user_meta.unique_id)
        return post_meta

    @when_error(return_value=None)
    def get_user_meta_by_post_meta(self, post_meta: PostMeta) -> Optional[UserMeta]:
        author_user_id = str(post_meta.author_user_id or "").strip()
        if not author_user_id:
            return None
        user_meta_dict = self.user_info.get_user_meta_by_author_user_id(author_user_id)
        if user_meta_dict is None:
            return None
        return UserMeta.from_dict(user_meta_dict)

    @classmethod
    def get_share_url_by_share_text(cls, share_text: str) -> str:
        """
        从分享文案或单独 URL 中取出一条小红书分享入口链接。
        """
        if share_text.startswith("http") and "\n" not in share_text:
            single = share_text.split()[0].rstrip(".,;)")
            if re.search(r"(?:xhslink\.com|xiaohongshu\.com|rednote\.com)", single, re.I):
                return single
        for pattern in cls._SHARE_ENTRY_URL_PATTERNS:
            m = re.search(pattern, share_text, flags=re.IGNORECASE)
            if m is not None:
                return m.group(0).rstrip(".,;)")
        raise AssertionError(f"未识别到小红书分享链接; text: {share_text!r}")

    @staticmethod
    def extract_query_param(url: str, key: str) -> str:
        return (parse_qs(urlparse(url).query).get(key) or [""])[0]

    @classmethod
    def is_blocked_page(cls, html: str, final_url: str = "") -> bool:
        if not html:
            return True
        if "website-login/captcha" in final_url:
            return True
        if UserInfo.try_parse_initial_state(html) is not None:
            return False
        if len(html) < 50000:
            return True
        return False

    @classmethod
    def build_note_page_url_candidates(cls, share_url: str, final_url: str, note_id: str) -> List[str]:
        candidates: List[str] = []

        def add(url: str) -> None:
            url = str(url or "").strip()
            if url and url not in candidates:
                candidates.append(url)

        add(final_url)
        add(share_url)

        query_keys = ["xsec_token", "xsec_source", "source", "xhsshare"]
        query: Dict[str, str] = {}
        for key in query_keys:
            value = cls.extract_query_param(share_url, key) or cls.extract_query_param(final_url, key)
            if value:
                query[key] = value
        if "xsec_source" not in query:
            query["xsec_source"] = "pc_share"

        if note_id:
            add(f"https://www.xiaohongshu.com/explore/{note_id}?{urlencode(query)}")
            add(f"https://www.xiaohongshu.com/discovery/item/{note_id}?{urlencode(query)}")

        return candidates

    def iter_page_html_candidates(self, share_url: str) -> List[Tuple[str, str]]:
        self.warmup_session()
        first_html, first_final_url = self.fetch_html_by_url(share_url)
        note_id = self.parse_note_id_from_urls(share_url, first_final_url)

        candidates: List[Tuple[str, str]] = []
        seen: set[Tuple[int, str]] = set()

        def add_candidate(html: str, final_url: str) -> None:
            key = (len(html), final_url)
            if key in seen:
                return
            seen.add(key)
            candidates.append((html, final_url))

        for page_url in self.build_note_page_url_candidates(share_url, first_final_url, note_id):
            html, landed_url = self.fetch_html_by_url(page_url)
            add_candidate(html, landed_url)
            if not self.is_blocked_page(html, landed_url):
                break

        if not candidates:
            add_candidate(first_html, first_final_url)
        return candidates

    @classmethod
    def parse_note_id_from_urls(cls, *urls: str) -> str:
        for url in urls:
            note_id = cls.parse_note_id_by_url(url)
            if cls._is_valid_note_id(note_id):
                return note_id
        return ""

    @staticmethod
    def _is_valid_note_id(note_id: str) -> bool:
        note_id = str(note_id or "").strip()
        if not note_id:
            return False
        if note_id in {"captcha", "404", "website-login"}:
            return False
        return bool(re.fullmatch(r"[0-9a-fA-F]+", note_id))

    @staticmethod
    def parse_note_id_by_url(url: str) -> str:
        """
        从落地页 URL 还原 ``note_id``。常见形式：
        - ``https://www.xiaohongshu.com/discovery/item/<note_id>?...``
        - ``https://www.xiaohongshu.com/explore/<note_id>?...``
        - 失效/拒绝时跳到 ``/404?noteId=<note_id>``。
        - 验证码页 ``redirectPath`` 参数里带原始笔记地址。
        """
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        note_id = (qs.get("noteId") or [""])[0]
        if note_id:
            return note_id

        redirect_path = (qs.get("redirectPath") or [""])[0]
        if redirect_path:
            return ShareMediaDownload.parse_note_id_by_url(redirect_path)

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if path_parts:
            return path_parts[-1]
        return ""

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        return self.get_post_meta_by_share_url(share_url)

    def _resolve_post_meta_by_share_url(self, share_url: str) -> Optional[PostMeta]:
        post_meta = None
        final_url = ""
        for html, landed_url in self.iter_page_html_candidates(share_url):
            if self.is_blocked_page(html, landed_url):
                continue
            state = UserInfo.try_parse_initial_state(html)
            if state is None:
                continue

            note_id = self.parse_note_id_from_urls(landed_url, share_url)
            if not note_id:
                continue

            note_detail_map = state["note"]["noteDetailMap"]
            if note_id not in note_detail_map:
                continue

            note = note_detail_map[note_id]["note"]
            note_type = note["type"]
            if note_type == "normal":
                post_meta = self.build_post_meta_from_note_branch_1(note)
            elif note_type == "video":
                post_meta = self.build_post_meta_from_note_branch_2(note)
            else:
                raise NotImplementedError(f"unknown note type: {note_type}")

            if post_meta is not None:
                final_url = landed_url
                break

        if post_meta is None:
            return None

        post_meta.share_url = share_url
        post_meta.final_url = final_url
        return post_meta

    @when_expected_error(return_value=None)
    def get_post_meta_by_share_url(self, share_url: str) -> dict:
        post_meta = self._resolve_post_meta_by_share_url(share_url)
        if post_meta is None:
            raise ExpectedError(status_code=60500, message=f"未成功解析到信息；share_url: {share_url}")

        user_meta = self.get_user_meta_by_post_meta(post_meta)
        post_meta = self.apply_user_meta_to_post_meta(post_meta, user_meta)
        return post_meta.to_dict()

    @when_error(return_value=None)
    def build_post_meta_from_note_branch_1(self, note: dict) -> Optional[PostMeta]:
        """
        https://www.xiaohongshu.com/explore/641ebb670000000013001f80?xsec_token=ABMJqb-M7W4_udyuIWceKl4rD2p2o2Fwf6fm-1Ana5d4Q=&xsec_source=pc_share

        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_note_branch_1"

        # print(f"note: {json.dumps(note, ensure_ascii=False, indent=4)}")

        post_meta.post_id = note["noteId"]
        post_meta.title = note["title"]
        post_meta.desc = re.sub(r"#([^#\[]+)\[[^\]]*\]#", "", note["desc"]).strip()
        post_meta.tags = [t["name"] for t in note["tagList"]]

        post_meta.author_user_id = note["user"]["userId"]
        post_meta.nickname = note["user"]["nickname"]

        post_meta.liked_count = note["interactInfo"]["likedCount"]
        post_meta.collected_count = note["interactInfo"]["collectedCount"]
        post_meta.comment_count = note["interactInfo"]["commentCount"]
        post_meta.share_count = note["interactInfo"]["shareCount"]

        post_meta.image_urls = [image["urlDefault"] for image in note["imageList"]]
        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_note_branch_2(self, note: dict) -> Optional[PostMeta]:
        """
        视频笔记（note["type"] == "video"）。

        https://www.xiaohongshu.com/discovery/item/69f5ce1f0000000023017c00?source=webshare&xhsshare=pc_web&xsec_token=ABlhx3-jH590AcirWbCOkw7vyiuwHKMJRzcp1BMFYIpfo=&xsec_source=pc_share

        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_note_branch_2"

        post_meta.post_id = note["noteId"]
        post_meta.title = note["title"]
        post_meta.desc = re.sub(r"#([^#\[]+)\[[^\]]*\]#", "", note["desc"]).strip()
        post_meta.tags = [t["name"] for t in note["tagList"]]

        post_meta.author_user_id = note["user"]["userId"]
        post_meta.nickname = note["user"]["nickname"]

        post_meta.liked_count = note["interactInfo"]["likedCount"]
        post_meta.collected_count = note["interactInfo"]["collectedCount"]
        post_meta.comment_count = note["interactInfo"]["commentCount"]
        post_meta.share_count = note["interactInfo"]["shareCount"]

        cover_url = note["imageList"][0]["urlDefault"]
        video_url = note["video"]["media"]["stream"]["h264"][0]["masterUrl"]
        post_meta.video_urls = [VideoMeta(cover_url=cover_url, video_url=video_url)]
        return post_meta


def main() -> None:
    """
    示例：
    - 短链：http://xhslink.com/o/8ekDPRNcz63
      （注：xhslink 短链对应的笔记下线后会重定向到 /404，导致解析失败，
       这种情况是数据本身的问题，不是代码问题。）
    - 长链：https://www.xiaohongshu.com/explore/<note_id>?xsec_token=...&xsec_source=pc_share
    """
    client = ShareMediaDownload()

    share_text = """

        https://www.xiaohongshu.com/discovery/item/69f5ce1f0000000023017c00?source=webshare&xhsshare=pc_web&xsec_token=ABlhx3-jH590AcirWbCOkw7vyiuwHKMJRzcp1BMFYIpfo=&xsec_source=pc_share

"""
    post_meta = client.get_post_meta_by_share_text(share_text)

    print("post_meta:")
    print(json.dumps(post_meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
