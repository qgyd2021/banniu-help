#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
微博分享解析（与 toolbox/douyin/media/share_media_download_.py、
toolbox/bilibili/media/share_media_download_.py、
toolbox/kuaishou/media/share_media_download_.py 风格对齐）。

逻辑参考 toolbox/weibo/media/share_media_download.py：
1. 把分享文案 / URL 收敛到一条 weibo 链接；
2. 跟跳后从 URL 里抽出 ``status_id`` （若被引导到 passport 访客页则从 query 还原）；
3. 优先调用 m 站 JSON 接口 ``m.weibo.cn/statuses/show?id={id}`` 拿全字段
   （免访客 cookie，分支 1，最稳）；
4. 备用：申请访客身份后请求 ``m.weibo.cn/detail/{id}``，从 HTML 内嵌
   ``render_data = [...]`` 抽 ``status`` 对象（分支 2）；
5. 映射到统一的 ``PostMeta``。
"""
import re
import json
import time
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, unquote, urlparse

import cacheout
import requests
import requests.utils

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

    platform: str = Field(default="weibo", description="平台标识，如 xiaohongshu/bilibili/douyin 等")
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
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
    }

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.headers.update(self.headers)
        self._visitor_ready: bool = False

    @staticmethod
    def _extract_json_from_callback(text: str) -> Dict[str, Any]:
        m = re.search(r"\((\{.*\})\)\s*;?\s*$", text, flags=re.DOTALL)
        if not m:
            raise AssertionError(f"callback json parse failed; text: {text[:300]}")
        return json.loads(m.group(1))

    def login_as_visitor(self, return_url: str = "https://m.weibo.cn/") -> bool:
        """生成微博访客 cookie（SUB/SUBP），用于访问需要登录态的 H5 页面（如 detail）。"""
        # 先清空已有 cookie，避免之前访问 passport 跳转页留下的脏值导致 incarnate 被风控（status_code 432）
        self._session.cookies.clear()
        request_id = str(int(time.time() * 1000))
        gen_resp = self._session.post(
            "https://visitor.passport.weibo.cn/visitor/genvisitor2",
            data={
                "cb": "visitor_gray_callback",
                "ver": "20250916",
                "request_id": request_id,
                "tid": "",
                "from": "weibo",
                "webdriver": "false",
                "rid": "",
                "return_url": return_url,
            },
            headers={
                **self.headers,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )
        if gen_resp.status_code != 200:
            raise AssertionError(f"genvisitor2 failed; status_code: {gen_resp.status_code}")
        gen_js = self._extract_json_from_callback(gen_resp.text)
        if gen_js.get("retcode") != 20000000:
            raise AssertionError(f"genvisitor2 failed: {json.dumps(gen_js, ensure_ascii=False)}")
        tid = (gen_js.get("data") or {}).get("tid")
        if not tid:
            raise AssertionError(f"genvisitor2 no tid: {json.dumps(gen_js, ensure_ascii=False)}")

        # 2026-05 观察：genvisitor2 已经通过 Set-Cookie 写入可用的 SUB/SUBP。
        # 继续调用 visitor?a=incarnate 会稳定返回 432，反而导致 detail 抓取失败。
        data = gen_js.get("data") or {}
        if data.get("sub"):
            self._session.cookies.set("SUB", data["sub"], domain=".weibo.cn")
        if data.get("subp"):
            self._session.cookies.set("SUBP", data["subp"], domain=".weibo.cn")
        self._visitor_ready = True
        return True

    def get_final_url_by_share_url(self, share_url: str) -> str:
        response = self._session.get(share_url, headers=self.headers, allow_redirects=True, timeout=30)
        return response.url

    @cacheout.memoize(ttl=60)
    def get_statuses(self, status_id: str) -> Dict[str, Any]:
        """``m.weibo.cn/statuses/show?id={id}`` 免 visitor cookie，可直接拿到完整字段。"""
        url = "https://m.weibo.cn/statuses/show"
        headers = {
            **self.headers,
            "Referer": f"https://m.weibo.cn/detail/{status_id}",
            "MWeibo-Pwa": "1",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        }
        response = self._session.get(
            url,
            headers=headers,
            params={"id": status_id},
            allow_redirects=False, timeout=30
        )
        if response.status_code != 200:
            raise AssertionError(
                f"statuses/show failed; status_code: {response.status_code}, status_id: {status_id}"
            )
        js = response.json()
        if not isinstance(js, dict) or js.get("ok") != 1:
            # {'ok': 0, 'errno': '20101', 'msg': '该微博不存在', 'error_type': 'alert', 'extra': 'target weibo does not exist!'}
            # {'ok': 0, 'errno': '20174', 'msg': '请前往微博客户端登录查看完整内容', 'title': '微博', 'btn': {'color': 'red', 'text': '微博内打开', 'url': '/feature/download/index'}, 'error_type': 'confirm', 'extra': 'Sorry, current status can only be seen by login user in official client/website! '}
            # {'ok': 0, 'errno': '20112', 'msg': '暂无查看权限', 'error_type': 'alert', 'extra': 'Permission Denied!'}
            raise ExpectedError(status_code=f'{js["errno"]}', message=f'statuses/show invalid; body: {js["msg"]}')
        data = js.get("data") or {}
        if not data:
            raise AssertionError(f"statuses/show empty data; status_id: {status_id}")
        return js

    @cacheout.memoize(ttl=10)
    def get_h5_video_component_by_oid(self, oid: str) -> Dict[str, Any]:
        """``h5.video.weibo.com/show/<oid>`` 的数据来自 ``api/component``。"""
        url = "https://h5.video.weibo.com/api/component"
        page = f"/show/{oid}"
        headers = {
            **self.headers,
            "Referer": f"https://h5.video.weibo.com/show/{oid}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self._session.post(
            url,
            headers=headers,
            params={"page": page},
            data={
                "data": json.dumps({
                    "Component_Play_Playinfo": {
                        "oid": oid,
                    },
                }, separators=(",", ":"), ensure_ascii=False),
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"h5 video component failed; status_code: {response.status_code}, oid: {oid}"
            )
        js = response.json()
        if js.get("code") != "100000":
            raise AssertionError(f"h5 video component invalid; body: {response.text[:300]}")
        data = ((js.get("data") or {}).get("Component_Play_Playinfo") or {})
        if not data:
            raise AssertionError(f"h5 video component empty data; oid: {oid}")
        return data

    def get_html_by_status_id(self, status_id: str) -> str:
        url = f"https://m.weibo.cn/detail/{status_id}"
        if not self._visitor_ready:
            self.login_as_visitor(return_url=url)
        response = self._session.get(
            url, headers=self.headers,
            allow_redirects=True, timeout=30
        )
        if response.status_code != 200:
            raise AssertionError(
                f"detail request failed; status_code: {response.status_code}, url: {url}"
            )
        return response.text


class ShareMediaDownload(ShareMediaDownloadRestful):
    _SHARE_ENTRY_URL_PATTERNS: List[str] = [
        r"https?://h5\.video\.weibo\.com/show/[^\s]+",
        r"https?://weibo\.com/[^\s]+",
        r"https?://m\.weibo\.cn/[^\s]+",
        r"https?://t\.cn/[A-Za-z0-9]+",
    ]

    @classmethod
    def get_share_url_by_share_text(cls, share_text: str) -> str:
        """
        从分享文案或单独 URL 中取出一条微博分享入口链接。
        """
        if share_text.startswith("http") and "\n" not in share_text:
            single = share_text.split()[0].rstrip(".,;)")
            if re.search(r"(?:weibo\.com|weibo\.cn|t\.cn)", single, re.I):
                return single
        for pattern in cls._SHARE_ENTRY_URL_PATTERNS:
            m = re.search(pattern, share_text, flags=re.IGNORECASE)
            if m is not None:
                return m.group(0).rstrip(".,;)")
        raise AssertionError(f"未识别到微博分享链接; text: {share_text!r}")

    @staticmethod
    def parse_h5_video_oid_by_url(url: str) -> Optional[str]:
        match = re.search(r"h5\.video\.weibo\.com/show/([^?\s#]+)", url, flags=re.IGNORECASE)
        if match is not None:
            return unquote(match.group(1))
        return None

    @staticmethod
    def parse_status_id_by_url(url: str) -> Optional[str]:
        path = urlparse(url).path.strip("/")
        parts = [x for x in path.split("/") if x]
        for part in reversed(parts):
            if re.fullmatch(r"\d{10,}", part):
                return part
        return None

    @staticmethod
    @when_error(return_value=None)
    def parse_render_data(html: str) -> Dict[str, Any]:
        marker = "render_data = "
        start = html.find(marker)
        if start < 0:
            raise AssertionError("render_data marker not found")
        start += len(marker)
        end = html.find("][0] || {};", start)
        if end < 0:
            raise AssertionError("render_data tail not found")
        arr_text = html[start:end + 1]
        arr = json.loads(arr_text)
        if not arr or not isinstance(arr[0], dict):
            raise AssertionError("render_data array invalid")
        return arr[0]

    def get_status_id_by_share_url(self, share_url: str, final_url: str) -> str:
        status_id = self.parse_status_id_by_url(share_url)
        if status_id is None:
            status_id = self.parse_status_id_by_url(final_url)

        if status_id is None and "passport.weibo." in final_url and "/visitor/visitor" in final_url:
            qs = parse_qs(urlparse(final_url).query)
            origin_url = unquote((qs.get("url") or [""])[0])
            status_id = self.parse_status_id_by_url(origin_url)
        if not status_id:
            return None
        return status_id

    @staticmethod
    def when_expected_error_return_post_meta(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ExpectedError as error:
            if error.status_code in (20101, 20112, 20174):
                post_meta = PostMeta()
                post_meta.title = error.message
                post_meta.desc = error.message
                return post_meta
            else:
                raise error

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        result = self.get_post_meta_by_share_url(share_url)
        return result

    @when_expected_error(return_value=None)
    def get_post_meta_by_share_url(self, share_url: str) -> dict:
        final_url = self.get_final_url_by_share_url(share_url)
        # print(f"final_url: {final_url}")

        post_meta = None

        status_id: str = self.get_status_id_by_share_url(share_url, final_url)

        if post_meta is None and status_id is not None:
            statuses = self.when_expected_error_return_post_meta(self.get_statuses, status_id)
            # print(f"statuses: {json.dumps(statuses, ensure_ascii=False, indent=4)}")
            post_meta = self.build_post_meta_from_statuses_branch_2(statuses)

        if post_meta is None and status_id is not None:
            statuses = self.when_expected_error_return_post_meta(self.get_statuses, status_id)
            # print(f"statuses: {json.dumps(statuses, ensure_ascii=False, indent=4)}")
            post_meta = self.build_post_meta_from_statuses_branch_3(statuses)

        if post_meta is None and status_id is not None:
            html = self.get_html_by_status_id(status_id)
            render_data = self.parse_render_data(html)
            post_meta = self.build_post_meta_from_render_data_branch_1(render_data)

        if post_meta is None:
            h5_video_oid = self.parse_h5_video_oid_by_url(final_url) or self.parse_h5_video_oid_by_url(share_url)
            if h5_video_oid is not None:
                h5_video_data = self.get_h5_video_component_by_oid(h5_video_oid)
                post_meta = self.build_post_meta_from_h5_video_branch_4(h5_video_data)

        if post_meta is None:
            raise ExpectedError(status_code=60500, message="未成功解析到信息；share_url: {share_url};")

        post_meta.share_url = share_url
        post_meta.final_url = final_url
        return post_meta.to_dict()

    @when_error(return_value=None)
    def build_post_meta_from_render_data_branch_1(self, render_data: dict) -> Optional[PostMeta]:
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_status_branch_1"

        data = render_data["status"]
        post_meta.post_id = data["id"]
        post_meta.title = data["status_title"]
        text = data["text"]
        text = re.sub(r'<[^>]+>', "", text)
        post_meta.desc = re.sub(r'#([^#]+)#', "", text).strip()
        post_meta.tags = re.findall(r'#([^#]+)#', text)

        post_meta.user_id = str(data["user"]["id"])
        post_meta.nickname = data["user"]["screen_name"]

        post_meta.liked_count = data["attitudes_count"]
        post_meta.comment_count = data["comments_count"]
        post_meta.share_count = data["reposts_count"]

        # image_urls
        image_urls = list()
        video_urls = list()
        for pic in data["pics"]:
            pic_type = pic.get("type", "unknown")
            if pic_type in ("livephoto", "video"):
                cover_url = pic["url"]
                video_url = pic["videoSrc"]
                video_urls.append(VideoMeta(cover_url=cover_url, video_url=video_url))
            elif pic_type == "unknown":
                image_urls.append(pic["url"])
            else:
                raise AssertionError(f"pic_type: {pic_type}")

        post_meta.image_urls = image_urls
        post_meta.video_urls = video_urls

        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_statuses_branch_2(self, statuses: dict) -> Optional[PostMeta]:
        """
        多张实况图片。
        https://weibo.com/7281031190/5289820563702404

        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_status_branch_1"

        data = statuses["data"]
        post_meta.post_id = data["id"]
        post_meta.title = data["status_title"]
        text = data["text"]
        text = re.sub(r'<[^>]+>', "", text)
        post_meta.desc = re.sub(r'#([^#]+)#', "", text).strip()
        post_meta.tags = re.findall(r'#([^#]+)#', text)
        # print(f"statuses: {json.dumps(statuses, ensure_ascii=False, indent=4)}")

        post_meta.user_id = str(data["user"]["id"])
        post_meta.nickname = data["user"]["screen_name"]

        post_meta.liked_count = data["attitudes_count"]
        post_meta.comment_count = data["comments_count"]
        post_meta.share_count = data["reposts_count"]

        # print(f"data: {json.dumps(data, ensure_ascii=False, indent=4)}")

        # image_urls
        image_urls = list()
        video_urls = list()
        for pic in data["pics"]:
            pic_type = pic.get("type", "unknown")
            if pic_type in ("livephoto", "video"):
                cover_url = pic["url"]
                video_url = pic["videoSrc"]
                video_urls.append(VideoMeta(cover_url=cover_url, video_url=video_url))
            elif pic_type == "unknown":
                image_urls.append(pic["url"])
            else:
                raise AssertionError(f"pic_type: {pic_type}")

        post_meta.image_urls = image_urls
        post_meta.video_urls = video_urls

        return post_meta

    # @when_error(return_value=None)
    def build_post_meta_from_statuses_branch_3(self, statuses: dict) -> Optional[PostMeta]:
        """
        单个视频
        https://weibo.com/8004538993/5300913684350192

        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_statuses_branch_3"

        data = statuses["data"]
        post_meta.post_id = data["id"]
        post_meta.title = data["status_title"]
        text = data["text"]
        text = re.sub(r'<[^>]+>', "", text)
        post_meta.desc = re.sub(r'#([^#]+)#', "", text).strip()
        post_meta.tags = re.findall(r'#([^#]+)#', text)
        # print(f"statuses: {json.dumps(statuses, ensure_ascii=False, indent=4)}")

        post_meta.user_id = str(data["user"]["id"])
        post_meta.nickname = data["user"]["screen_name"]

        post_meta.liked_count = data["attitudes_count"]
        post_meta.comment_count = data["comments_count"]
        post_meta.share_count = data["reposts_count"]
        # print(f"data: {json.dumps(data, ensure_ascii=False, indent=4)}")

        video_urls = list()
        page_info = data["page_info"]
        cover_url = page_info["page_pic"]["url"]
        video_url = page_info["urls"]["mp4_720p_mp4"]

        post_meta.video_urls = [VideoMeta(cover_url=cover_url, video_url=video_url)]
        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_h5_video_branch_4(self, data: dict) -> Optional[PostMeta]:
        """
        微博视频 H5 页。
        https://h5.video.weibo.com/show/1034:5300673529446444
        """
        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_h5_video_branch_3"

        post_meta.post_id = str(data["id"])
        post_meta.title = data["title"]

        text = data["text"]
        text = re.sub(r'<[^>]+>', "", text)
        post_meta.desc = re.sub(r'#([^#]+)#', "", text).strip()
        post_meta.tags = [topic["content"] for topic in data["topics"]]

        post_meta.user_id = str(data["author_id"])
        post_meta.nickname = data["nickname"]

        post_meta.liked_count = data["attitudes_count"]
        post_meta.comment_count = data["comments_count"]
        post_meta.share_count = data["reposts_count"]

        cover_url = data["cover_image"]
        if cover_url.startswith("//"):
            cover_url = f"https:{cover_url}"

        urls = data["urls"]
        if "高清 1080P" in urls:
            video_url = urls["高清 1080P"]
        elif "高清 720P" in urls:
            video_url = urls["高清 720P"]
        elif "标清 480P" in urls:
            video_url = urls["标清 480P"]
        else:
            video_url = data["stream_url"]
        if video_url.startswith("//"):
            video_url = f"https:{video_url}"

        # post_meta.image_urls = [cover_url]
        post_meta.video_urls = [VideoMeta(cover_url=cover_url, video_url=video_url)]

        return post_meta


def main() -> None:
    client = ShareMediaDownload()

    share_text = """

https://mapp.api.weibo.cn/fx/24a3b09d91da822f662af20bc2d8c385.htmL;

"""
    result = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
