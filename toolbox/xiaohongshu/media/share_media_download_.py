#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
小红书分享解析（与 toolbox/weibo/media/share_media_download_.py、
toolbox/kuaishou/media/share_media_download_.py、
toolbox/douyin/media/share_media_download_.py 风格对齐）。

逻辑参考 toolbox/xiaohongshu/media/share_media_download.py：

1. 从分享文案中抓出一条小红书分享入口链接
   （xhslink.com 短链 / xiaohongshu.com / rednote.com）；
2. 跟跳到落地页（一般是 ``discovery/item`` 或 ``explore``）；
3. 从 HTML 内嵌 ``window.__INITIAL_STATE__`` 取笔记数据：
   - PC ``explore``：``note.noteDetailMap[note_id].note``（分支 1 / 2）；
   - 移动端 H5 ``discovery/item``：``noteData.data.noteData``（分支 3 / 4）；
4. 映射到统一的 ``PostMeta``。

说明：同一链接在无痕/未登录场景下，PC 侧可能间歇性落到 ``/404``，
移动端 H5 相对稳定，但也不是 100% 成功。本模块只做单次解析尝试
（含 PC/移动端 UA 与若干 URL 候选，属于不同抓取路径而非重试），
若失败由调用方自行决定何时再次调用。
"""
import json
import re
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlparse, urljoin

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
    windows_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.xiaohongshu.com/",
    }
    iphone_headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.xiaohongshu.com/",
    }

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(self.windows_headers)

    def _request_headers(self, use_iphone: bool) -> Dict[str, str]:
        return self.iphone_headers if use_iphone else self.windows_headers

    def warmup_session(self) -> None:
        self._session.get("https://www.xiaohongshu.com/", allow_redirects=True, timeout=30)

    def fetch_html_by_url(self, url: str, use_iphone: bool = False) -> Tuple[str, str]:
        response = requests.get(
            url,
            headers=self._request_headers(use_iphone),
            allow_redirects=True,
            timeout=30,
        )
        return response.text, response.url

    def get_html_and_final_url_by_share_url(self, share_url: str) -> Tuple[str, str]:
        self.warmup_session()
        return self.fetch_html_by_url(share_url)

    def get_text_by_url(self, url: str) -> str:
        self.warmup_session()
        html, _ = self.fetch_html_by_url(url)
        return html

    def trace_redirect_urls(self, url: str, max_hops: int = 10, use_iphone: bool = False) -> List[str]:
        headers = self._request_headers(use_iphone)
        urls: List[str] = []
        cur = url
        for _ in range(max_hops):
            urls.append(cur)
            response = requests.get(
                cur,
                headers=headers,
                allow_redirects=False,
                timeout=30,
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    break
                cur = urljoin(cur, location)
                continue
            break
        return urls


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
    def pick_unique_id_from_note_user(user: dict) -> str:
        if not isinstance(user, dict):
            return ""
        for key in ("redId", "red_id"):
            value = str(user.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def apply_note_user_to_post_meta(post_meta: PostMeta, user: dict) -> PostMeta:
        unique_id = ShareMediaDownload.pick_unique_id_from_note_user(user)
        if unique_id:
            post_meta.unique_id = unique_id
            post_meta.user_id = unique_id
        return post_meta

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
        if post_meta.user_id:
            return None
        self.user_info.adopt_session_cookies(self._session.cookies)
        self.user_info.warmup_session()
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

    @staticmethod
    def parse_initial_state(html: str) -> Optional[Dict[str, Any]]:
        marker = "window.__INITIAL_STATE__="
        start = html.find(marker)
        if start < 0:
            return None
        start += len(marker)
        end = html.find("</script>", start)
        if end < 0:
            return None
        raw = html[start:end].strip()
        if not raw:
            return None
        raw = re.sub(r"\bundefined\b", "null", raw)
        raw = re.sub(r"\bNaN\b", "null", raw)
        raw = re.sub(r"\bInfinity\b", "null", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    @classmethod
    def pick_note_from_state(cls, state: Dict[str, Any], note_id: str) -> Optional[dict]:
        note_section = state.get("note")
        if isinstance(note_section, dict):
            note_detail_map = note_section.get("noteDetailMap")
            if isinstance(note_detail_map, dict):
                if note_id in note_detail_map:
                    note = note_detail_map[note_id]["note"]
                    if note.get("noteId"):
                        return note
                for key, block in note_detail_map.items():
                    if key in ("null", ""):
                        continue
                    note = block["note"]
                    if note.get("noteId"):
                        return note

        note_data_root = state.get("noteData")
        if isinstance(note_data_root, dict):
            data = note_data_root.get("data")
            if isinstance(data, dict):
                mobile_note = data.get("noteData")
                if isinstance(mobile_note, dict) and mobile_note.get("noteId"):
                    return mobile_note

        return None

    @staticmethod
    def is_mobile_h5_note(note: dict) -> bool:
        user = note.get("user")
        return isinstance(user, dict) and "nickName" in user

    @classmethod
    def has_valid_note_in_state(cls, state: Dict[str, Any], note_id: str = "") -> bool:
        return cls.pick_note_from_state(state, note_id) is not None

    @classmethod
    def is_blocked_page(cls, html: str, final_url: str = "") -> bool:
        if not html:
            return True
        if "website-login/captcha" in final_url:
            return True
        if "/404" in final_url:
            return True
        state = cls.parse_initial_state(html)
        if state is None:
            return len(html) < 50000
        return not cls.has_valid_note_in_state(state)

    @classmethod
    def build_note_page_url_candidates(
        cls,
        share_url: str,
        final_url: str,
        note_id: str,
        redirect_urls: Optional[List[str]] = None,
    ) -> List[str]:
        candidates: List[str] = []

        def add(url: str) -> None:
            url = str(url or "").strip()
            if url and url not in candidates:
                candidates.append(url)

        add(final_url)
        add(share_url)
        for redirect_url in redirect_urls or []:
            add(redirect_url)

        query_keys = ["xsec_token", "xsec_source", "source", "xhsshare"]
        query: Dict[str, str] = {}
        source_urls = [share_url, final_url, *(redirect_urls or [])]
        for key in query_keys:
            for source_url in source_urls:
                value = cls.extract_query_param(source_url, key)
                if value:
                    query[key] = value
                    break
        if "xsec_source" not in query:
            query["xsec_source"] = "pc_share"

        if note_id:
            add(f"https://www.xiaohongshu.com/explore/{note_id}?{urlencode(query)}")
            add(f"https://www.xiaohongshu.com/discovery/item/{note_id}?{urlencode(query)}")

        return candidates

    def iter_page_html_candidates(self, share_url: str) -> List[Tuple[str, str]]:
        self.warmup_session()
        redirect_urls_pc = self.trace_redirect_urls(share_url, use_iphone=False)
        redirect_urls_iphone = self.trace_redirect_urls(share_url, use_iphone=True)
        redirect_urls: List[str] = []
        for redirect_url in redirect_urls_pc + redirect_urls_iphone:
            if redirect_url not in redirect_urls:
                redirect_urls.append(redirect_url)

        first_html, first_final_url = self.fetch_html_by_url(share_url, use_iphone=True)
        note_id = self.parse_note_id_from_urls(share_url, first_final_url, *redirect_urls)

        candidates: List[Tuple[str, str]] = []
        seen: set[Tuple[int, str]] = set()

        def add_candidate(html: str, final_url: str) -> None:
            key = (len(html), final_url)
            if key in seen:
                return
            seen.add(key)
            candidates.append((html, final_url))

        for page_url in self.build_note_page_url_candidates(
            share_url,
            first_final_url,
            note_id,
            redirect_urls=redirect_urls,
        ):
            resolved = False
            for use_iphone in (True, False):
                html, landed_url = self.fetch_html_by_url(page_url, use_iphone=use_iphone)
                add_candidate(html, landed_url)
                if not self.is_blocked_page(html, landed_url):
                    resolved = True
                    break
            if resolved:
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
            state = self.parse_initial_state(html)
            if state is None:
                continue

            note_id = self.parse_note_id_from_urls(landed_url, share_url)
            note = self.pick_note_from_state(state, note_id)
            if note is None:
                continue

            note_type = note["type"]
            if self.is_mobile_h5_note(note):
                if note_type == "normal":
                    post_meta = self.build_post_meta_from_note_branch_3(note)
                elif note_type == "video":
                    post_meta = self.build_post_meta_from_mobile_video_branch_4(note)
                else:
                    raise NotImplementedError(f"unknown note type: {note_type}")
            elif note_type == "normal":
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
        post_meta = self.apply_note_user_to_post_meta(post_meta, note["user"])

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
        post_meta = self.apply_note_user_to_post_meta(post_meta, note["user"])

        post_meta.liked_count = note["interactInfo"]["likedCount"]
        post_meta.collected_count = note["interactInfo"]["collectedCount"]
        post_meta.comment_count = note["interactInfo"]["commentCount"]
        post_meta.share_count = note["interactInfo"]["shareCount"]

        cover_url = note["imageList"][0]["urlDefault"]
        video_url = note["video"]["media"]["stream"]["h264"][0]["masterUrl"]
        post_meta.video_urls = [VideoMeta(cover_url=cover_url, video_url=video_url)]
        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_note_branch_3(self, note: dict) -> Optional[PostMeta]:
        """
        移动端 H5 discovery/item；数据在 noteData.data.noteData。
        http://xhslink.com/o/3ELE15UPkMy
        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_note_branch_3"

        post_meta.post_id = note["noteId"]
        post_meta.title = note["title"]
        post_meta.desc = re.sub(r"#([^#\[]+)\[[^\]]*\]#", "", note["desc"]).strip()
        post_meta.tags = [t["name"] for t in note["tagList"]]

        post_meta.author_user_id = note["user"]["userId"]
        post_meta.nickname = note["user"]["nickName"]
        post_meta = self.apply_note_user_to_post_meta(post_meta, note["user"])

        interact = note["interactInfo"]
        post_meta.liked_count = interact["likedCount"]
        post_meta.collected_count = interact["collectedCount"]
        post_meta.comment_count = interact["commentCount"]
        post_meta.share_count = interact["shareCount"]

        post_meta.image_urls = [image["url"] for image in note["imageList"]]
        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_mobile_video_branch_4(self, note: dict) -> Optional[PostMeta]:
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_mobile_video_branch_4"

        post_meta.post_id = note["noteId"]
        post_meta.title = note["title"]
        post_meta.desc = re.sub(r"#([^#\[]+)\[[^\]]*\]#", "", note["desc"]).strip()
        post_meta.tags = [t["name"] for t in note["tagList"]]

        post_meta.author_user_id = note["user"]["userId"]
        post_meta.nickname = note["user"]["nickName"]
        post_meta = self.apply_note_user_to_post_meta(post_meta, note["user"])

        interact = note["interactInfo"]
        post_meta.liked_count = interact["likedCount"]
        post_meta.collected_count = interact["collectedCount"]
        post_meta.comment_count = interact["commentCount"]
        post_meta.share_count = interact["shareCount"]

        cover_url = note["imageList"][0]["url"]
        video_url = note["video"]["media"]["stream"]["h264"][0]["masterUrl"]
        post_meta.video_urls = [VideoMeta(cover_url=cover_url, video_url=video_url)]
        return post_meta


def main() -> None:
    """
    示例：
    - 短链：http://xhslink.com/o/3ELE15UPkMy
    - 长链：https://www.xiaohongshu.com/explore/<note_id>?xsec_token=...&xsec_source=pc_share

    若偶发解析失败（平台间歇性返回 /404），由调用方稍后重试即可。
    """
    client = ShareMediaDownload()

    share_text = """

http://xhslink.com/o/8v8r0Keqsk4 把这段复制下来，打开【小红书】就能看到精彩笔记。

"""
    post_meta = client.get_post_meta_by_share_text(share_text)

    print("post_meta:")
    print(json.dumps(post_meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
