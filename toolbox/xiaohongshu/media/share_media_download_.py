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
from urllib.parse import parse_qs, urlparse

import requests

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
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }

    def get_html_and_final_url_by_share_url(self, share_url: str) -> Tuple[str, str]:
        response = requests.get(share_url, headers=self.headers,
                                allow_redirects=True,
                                timeout=30)
        return response.text, response.url

    def get_text_by_url(self, url: str) -> str:
        response = requests.get(url, headers=self.headers, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {url}")
        return response.text


class ShareMediaDownload(ShareMediaDownloadRestful):
    _SHARE_ENTRY_URL_PATTERNS: List[str] = [
        r"https?://xhslink\.com/[A-Za-z0-9/_\-]+",
        r"https?://(?:www\.)?xiaohongshu\.com/[^\s]+",
        r"https?://(?:www\.)?rednote\.com/[^\s]+",
    ]

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
    def parse_note_id_by_url(url: str) -> str:
        """
        从落地页 URL 还原 ``note_id``。常见形式：
        - ``https://www.xiaohongshu.com/discovery/item/<note_id>?...``
        - ``https://www.xiaohongshu.com/explore/<note_id>?...``
        - 失效/拒绝时跳到 ``/404?noteId=<note_id>``。
        """
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        note_id = (qs.get("noteId") or [""])[0]
        if note_id:
            return note_id
        return parsed.path.strip("/").split("/")[-1]

    @staticmethod
    def parse_initial_state(html: str) -> Dict[str, Any]:
        """
        从落地页 HTML 抽 ``window.__INITIAL_STATE__`` JSON。
        ``undefined`` / ``NaN`` / ``Infinity`` 不是合法 JSON 值，需替换。
        """
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

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        result = self.get_post_meta_by_share_url(share_url)
        return result

    @when_expected_error(return_value=None)
    def get_post_meta_by_share_url(self, share_url: str) -> dict:
        html, final_url = self.get_html_and_final_url_by_share_url(share_url)
        # print(f"final_url: {final_url}")

        note_id = self.parse_note_id_by_url(final_url)
        # print(f"note_id: {note_id}")

        state = self.parse_initial_state(html)
        note = state["note"]["noteDetailMap"][note_id]["note"]
        # print(json.dumps(note, ensure_ascii=False, indent=2))

        note_type = note["type"]
        if note_type == "normal":
            post_meta: PostMeta = self.build_post_meta_from_note_branch_1(note)
        elif note_type == "video":
            post_meta: PostMeta = self.build_post_meta_from_note_branch_2(note)
        else:
            raise NotImplementedError(f"unknown note type: {note_type}")

        if post_meta is None:
            raise ExpectedError(status_code=60500, message="未成功解析到信息；share_url: {share_url}")

        post_meta.share_url = share_url
        post_meta.final_url = final_url
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

        post_meta.user_id = note["user"]["userId"]
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

        post_meta.user_id = note["user"]["userId"]
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
    result = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
