#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
小黑盒分享解析（与 toolbox/douyin/media/share_media_download_.py、
toolbox/kuaishou/media/share_media_download_.py、
toolbox/weibo/media/share_media_download_.py 风格对齐）。

逻辑参考 toolbox/xiaoheihe/media/share_media_download.py：
1. 把分享文案 / URL 收敛到一条小黑盒链接，解析出 ``link_id``；
2. 调用前端真正使用的 ``api.xiaoheihe.cn/bbs/app/link/tree`` 接口（无需登录），
   返回值里有标题、正文、作者、点赞 / 评论 / 收藏 / 分享 / 实际媒体 URL。
   该接口需要 ``hkey/nonce/_time`` 签名，签名算法已从 web bundle
   ``static.max-c.com/static/heybox-website-nuxt/2.5.6/_nuxt/DYl6Iotr.js`` 中
   逆向出来，见 ``_hkey``。
3. 备用：调用 ``api/web/share`` 拿 302 ``redirect_data``（无需登录就能给出
   ``title`` / ``description``），并从详情页 HTML 中尽力收图片；
4. 映射到统一的 ``PostMeta``。
"""
import hashlib
import json
import re
import secrets
import time
from xmlrpc.client import Fault

from hyperframe.frame import Priority
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from toolbox.utils.utils import when_error

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

    platform: str = Field(default="xiaoheihe", description="平台标识，如 xiaohongshu/bilibili/douyin 等")
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


# ----- 小黑盒 hkey 签名算法（逆向自 _nuxt/DYl6Iotr.js, 已用浏览器抓包样本对齐验证）----

_HKEY_TABLE = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"


def _hkey_rn(e: int) -> int:
    return (((e << 1) ^ 27) & 0xff) if (128 & e) else (e << 1) & 0xff


def _hkey_on(e: int) -> int:
    return _hkey_rn(e) ^ e


def _hkey_an(e: int) -> int:
    return _hkey_on(_hkey_rn(e))


def _hkey_sn(e: int) -> int:
    return _hkey_an(_hkey_on(_hkey_rn(e)))


def _hkey_un(e: int) -> int:
    return _hkey_sn(e) ^ _hkey_an(e) ^ _hkey_on(e)


def _hkey_ln(s: str, table: str, n: int) -> str:
    sub = table[:n]
    return "".join(sub[ord(c) % len(sub)] for c in s)


def _hkey_dn(s: str, table: str) -> str:
    return "".join(table[ord(c) % len(table)] for c in s)


def _hkey(path: str, _time: int, nonce: str) -> str:
    """7 字符 hkey 签名。算法对应 JS 的 ``fn['g'](path, _time, nonce) = cn(path, _time + 1, nonce)``。"""
    t_val = _time + 1
    parts = [p for p in path.split("/") if p]
    path = "/" + "/".join(parts) + "/"
    table = _HKEY_TABLE

    arr = [_hkey_ln(str(t_val), table, -2), _hkey_dn(path, table), _hkey_dn(nonce, table)]
    max_len = max(len(x) for x in arr)
    inter: List[str] = []
    for k in range(max_len):
        for x in arr:
            if k < len(x):
                inter.append(x[k])
    inter_str = "".join(inter)[:20]

    a = hashlib.md5(inter_str.encode("utf-8")).hexdigest()
    chars = [ord(c) for c in a[-6:]]
    e0, e1, e2, e3 = chars[0], chars[1], chars[2], chars[3]
    t0 = _hkey_un(e0) ^ _hkey_sn(e1) ^ _hkey_an(e2) ^ _hkey_on(e3)
    t1 = _hkey_on(e0) ^ _hkey_un(e1) ^ _hkey_sn(e2) ^ _hkey_an(e3)
    t2 = _hkey_an(e0) ^ _hkey_on(e1) ^ _hkey_un(e2) ^ _hkey_sn(e3)
    t3 = _hkey_sn(e0) ^ _hkey_an(e1) ^ _hkey_on(e2) ^ _hkey_un(e3)
    chars[0], chars[1], chars[2], chars[3] = t0, t1, t2, t3
    s_val = sum(chars) % 100
    front = _hkey_ln(a[:5], table, -4)
    return f"{front}{s_val:02d}"


class ShareMediaDownloadRestful(object):
    api_host = "https://api.xiaoheihe.cn"
    www_host = "https://www.xiaoheihe.cn"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        ),
    }
    _COMMON_PARAMS: List[Tuple[str, str]] = [
        ("os_type", "web"),
        ("app", "heybox"),
        ("client_type", "web"),
        ("version", "999.0.4"),
        ("web_version", "2.5"),
        ("x_client_type", "web"),
        ("x_app", "heybox_website"),
        ("heybox_id", ""),
        ("x_os_type", "Windows"),
        ("device_info", "Chrome"),
        ("device_id", "92f308ff6e98d5b959365585fecd9079"),
    ]

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.headers.update(self.headers)

    def get_link_tree_by_link_id(self, link_id: str) -> Dict[str, Any]:
        """调用 ``bbs/app/link/tree``，拿到完整的 link 详情（含图片 / 视频 URL）。"""
        path = "/bbs/app/link/tree"
        _time = int(time.time())
        nonce = secrets.token_hex(16).upper()
        hkey = _hkey(path, _time, nonce)

        extra: List[Tuple[str, str]] = [
            ("hkey", hkey),
            ("_time", str(_time)),
            ("nonce", nonce),
            ("link_id", link_id),
            ("is_first", "1"),
            ("page", "1"),
            ("index", "1"),
            ("limit", "20"),
            ("owner_only", "0"),
        ]
        url = f"{self.api_host}{path}?" + urlencode(self._COMMON_PARAMS + extra)
        headers = {
            **self.headers,
            "Accept": "application/json, text/plain, */*",
            "Origin": self.www_host,
            "Referer": f"{self.www_host}/app/bbs/link/{link_id}",
        }
        response = self._session.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            raise AssertionError(
                f"link/tree failed; status_code: {response.status_code}, link_id: {link_id}"
            )
        js = response.json()
        if js.get("status") != "ok":
            raise AssertionError(
                f"link/tree returned status={js.get('status')}, text: {response.text.strip()}, link_id: {link_id}"
            )
        return js

    def get_redirect_data_by_link_id(self, link_id: str) -> Dict[str, Any]:
        """备用通道：``api/web/share`` 在禁止跟跳时把 ``link.title`` / ``link.description``
        放在 302 ``Location`` 的 ``redirect_data`` 里，无需登录即可拿到。"""
        url = (
            f"{self.api_host}/v3/bbs/app/api/web/share"
            f"?h_camp=link&h_src=YXBwX3NoYXJl&link_id={link_id}"
        )
        response = self._session.get(url, allow_redirects=False, timeout=30)
        if response.status_code not in (301, 302, 303, 307, 308):
            raise AssertionError(
                f"share redirect failed; status_code: {response.status_code}, link_id: {link_id}"
            )
        location = response.headers.get("Location") or ""
        q = parse_qs(urlparse(location).query)
        raw_list = q.get("redirect_data") or []
        if not raw_list:
            return {}
        try:
            return json.loads(raw_list[0])
        except json.JSONDecodeError:
            return {}

    def get_html_by_link_id(self, link_id: str) -> str:
        url = f"{self.www_host}/app/bbs/link/{link_id}"
        response = self._session.get(url, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(
                f"link page failed; status_code: {response.status_code}, link_id: {link_id}"
            )
        return response.text or ""


class ShareMediaDownload(ShareMediaDownloadRestful):
    _SHARE_ENTRY_URL_PATTERNS: List[str] = [
        r"https?://api\.xiaoheihe\.cn/v3/bbs/app/api/web/share\?[^\s]+",
        r"https?://www\.xiaoheihe\.cn/app/bbs/link/[0-9a-f]+[^\s]*",
        r"https?://(?:[a-z0-9.-]+\.)?xiaoheihe\.cn/[^\s]+",
    ]

    @classmethod
    def get_share_url_by_share_text(cls, share_text: str) -> str:
        """
        从分享文案或单独 URL 中取出一条小黑盒分享入口链接。
        若文案中只有裸 link_id，则拼回 share API URL。
        """
        if share_text.startswith("http") and "\n" not in share_text:
            single = share_text.split()[0].rstrip(".,;)")
            if re.search(r"xiaoheihe\.cn", single, re.I):
                return single
        for pattern in cls._SHARE_ENTRY_URL_PATTERNS:
            m = re.search(pattern, share_text, flags=re.IGNORECASE)
            if m is not None:
                return m.group(0).rstrip(".,;)")
        m = re.search(r"\b([0-9a-f]{10,})\b", share_text, flags=re.IGNORECASE)
        if m is not None:
            link_id = m.group(1).lower()
            return (
                f"https://api.xiaoheihe.cn/v3/bbs/app/api/web/share"
                f"?h_camp=link&h_src=YXBwX3NoYXJl&link_id={link_id}"
            )
        raise AssertionError(f"未识别到小黑盒分享链接; text: {share_text!r}")

    @staticmethod
    def parse_link_id_by_url(url: str) -> str:
        patterns = [
            r"[?&]link_id=([0-9a-f]+)",
            r"/app/bbs/link/([0-9a-f]+)",
            r"/link/([0-9a-f]+)",
        ]
        for pat in patterns:
            m = re.search(pat, url, flags=re.IGNORECASE)
            if m is not None:
                return m.group(1).lower()
        raise AssertionError(f"cannot parse link_id from url: {url}")

    @staticmethod
    def extract_tags_and_desc(caption: str) -> Tuple[List[str], str]:
        if not caption:
            return [], ""
        tags = re.findall(r"#([^#\s]+)#?", caption)
        desc = caption
        for tag in sorted(tags, key=len, reverse=True):
            desc = desc.replace(f"#{tag}#", "")
            desc = desc.replace(f"#{tag}", "")
        desc = re.sub(r"[ \t]+", " ", desc).strip()
        return tags, desc

    @staticmethod
    def parse_og_meta(html: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for m in re.finditer(
            r'<meta[^>]+property="og:([^"]+)"[^>]+content="([^"]*)"',
            html, flags=re.IGNORECASE,
        ):
            out[m.group(1).strip()] = m.group(2).strip()
        return out

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        # print(f"share_url: {share_url}")
        link_id = self.parse_link_id_by_url(share_url)
        # print(f"link_id: {link_id}")
        final_url = f"{self.www_host}/app/bbs/link/{link_id}"

        link_tree = self.get_link_tree_by_link_id(link_id)
        post_meta = self.build_post_meta_from_link_tree_branch_1(link_tree)

        if post_meta is None:
            raise AssertionError(f"未成功解析到信息；share_url: {share_url};")

        post_meta.share_url = share_url
        post_meta.final_url = final_url
        return post_meta.to_dict()

    @when_error(return_value=None)
    def build_post_meta_from_link_tree_branch_1(self, link_tree: dict) -> Optional[PostMeta]:
        """
        https://www.xiaoheihe.cn/app/bbs/link/14f971c83d09

        需要验证码
        https://www.xiaoheihe.cn/app/bbs/link/179343470

        """
        link = link_tree["result"]["link"]
        print(f"link: {json.dumps(link, ensure_ascii=False, indent=2)}")

        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_tree_branch_1"

        post_meta.post_id = str(link["linkid"])

        post_meta.title = link["title"]
        post_meta.desc = link["description"]
        post_meta.tags = [h["name"] for h in link["hashtags"]]

        user = link["user"]
        post_meta.user_id = str(user["userid"])
        post_meta.nickname = user["username"]

        post_meta.liked_count = link["link_award_num"]
        post_meta.collected_count = link["favour_count"]
        post_meta.comment_count = link["comment_num"]
        post_meta.share_count = link["forward_num"]

        image_urls = list()
        video_urls = list()
        text = link["text"]
        text = json.loads(text)
        print(f"text: {json.dumps(text, ensure_ascii=False, indent=2)}")
        for item in text:
            item_type = item["type"]
            if item_type in ("text", "html"):
                continue
            elif item_type == "img":
                image_urls.append(item["url"])
            else:
                raise NotImplementedError(f"item_type: {item_type}")

        post_meta.image_urls = image_urls
        post_meta.video_urls = video_urls
        return post_meta


def main() -> None:
    client = ShareMediaDownload()

    share_text = """

https://www.xiaoheihe.cn/app/bbs/link/179344791


"""
    result = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
