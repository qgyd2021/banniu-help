#!/usr/bin/python3
# -*- coding: utf-8 -*-
import hashlib
import logging
import re
import json
import time
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import cacheout
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

    platform: str = Field(default="bilibili", description="平台标识，如 xiaohongshu/bilibili/douyin 等")
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
        "Origin": "https://www.bilibili.com",
        # "Referer": "https://www.bilibili.com",
    }

    # B 站 web 端 WBI 签名所用的固定 mixin 表（来自 Nuxt 前端打包）。
    _WBI_MIXIN_KEY_TABLE: List[int] = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5,
        49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24,
        55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63,
        57, 62, 11, 36, 20, 34, 44, 52,
    ]
    _wbi_mixin_key_cache: Optional[str] = None

    # 风控/验证码页常见特征：HTTP 412、bilibili security control 提示、跳到 passport 验证页等。
    _RISK_PAGE_BODY_KEYWORDS: List[str] = [
        "bilibili security control policy",
        "gcaptcha4.geetest.com",
        "api.geevisit.com",
    ]
    _RISK_PAGE_TITLE_RE = re.compile(r"<title>[^<]*(?:出错啦|验证码)[^<]*</title>", flags=re.IGNORECASE)
    _RISK_PAGE_URL_KEYWORDS: List[str] = [
        "passport.bilibili.com",
        "/h5/project-verify",
    ]

    @classmethod
    def is_risk_page_response(cls, response: requests.Response) -> bool:
        """B 站风控/验证码页统一识别（HTTP 412、出错啦、跳 passport 等）。"""
        if response.status_code == 412:
            return True
        landed_url = (response.url or "").lower()
        if any(key in landed_url for key in cls._RISK_PAGE_URL_KEYWORDS):
            return True
        body = response.text or ""
        if any(key in body for key in cls._RISK_PAGE_BODY_KEYWORDS):
            return True
        if cls._RISK_PAGE_TITLE_RE.search(body):
            return True
        return False

    @cacheout.memoize(ttl=10)
    def get_final_url_by_share_url(self, share_url: str) -> str:
        response = requests.get(share_url, headers=self.headers, timeout=30)
        return response.url

    @cacheout.memoize(ttl=10)
    def get_text_by_url(self, url: str) -> Optional[str]:
        response = requests.get(url, headers=self.headers, timeout=30)
        if self.is_risk_page_response(response):
            raise AssertionError(f"bilibili 命中风控/验证码页，跳过 HTML 解析； status_code: {response.status_code}, url: {url}")
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}, url: {url}")
        return response.text

    @cacheout.memoize(ttl=10)
    def get_play_url(self, bvid: str, cid: int) -> str:
        url = "https://api.bilibili.com/x/player/playurl"
        headers = {
            **self.headers,
            "Referer": f"https://www.bilibili.com/video/{bvid}/",
        }
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": 120,
            "fnval": 1,
            "fourk": 1,
        }
        response = requests.get(
            url=url,
            headers=headers,
            params=params,
            timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        # print(json.dumps(js, ensure_ascii=False, indent=2))
        if js.get("code") != 0:
            raise AssertionError(f"get playurl failed; code: {js['code']}, message: {js['message']}")
        return js

    @classmethod
    @cacheout.memoize(ttl=10)
    def _get_wbi_mixin_key(cls) -> str:
        """
        请求 ``x/web-interface/nav`` 拿到 ``wbi_img.img_url`` / ``sub_url``，
        按固定 mixin 表重排出 32 位 ``mixin_key``，给 ``x/polymer/web-dynamic/v1/detail``
        等接口的 ``w_rid`` 签名用。
        """
        if cls._wbi_mixin_key_cache:
            return cls._wbi_mixin_key_cache
        response = requests.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=cls.headers, timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(f"nav request failed; status_code: {response.status_code}")
        js = response.json()
        wbi_img = js["data"]["wbi_img"]
        img_key = wbi_img["img_url"].rsplit("/", 1)[1].split(".")[0]
        sub_key = wbi_img["sub_url"].rsplit("/", 1)[1].split(".")[0]
        raw = img_key + sub_key
        cls._wbi_mixin_key_cache = "".join(raw[i] for i in cls._WBI_MIXIN_KEY_TABLE)[:32]
        return cls._wbi_mixin_key_cache

    def _wbi_sign_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        signed = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in params.items()}
        signed["wts"] = int(time.time())
        qs = urlencode(sorted(signed.items()))
        mixin = self._get_wbi_mixin_key()
        signed["w_rid"] = hashlib.md5((qs + mixin).encode()).hexdigest()
        return signed

    @cacheout.memoize(ttl=10)
    def get_web_dynamic_by_dynamic_id(self, dynamic_id: str) -> dict:
        """
        ``t.bilibili.com/<dynamic_id>`` 落地页的 HTML 不再带 ``__INITIAL_STATE__``，
        必须走带 WBI 签名的 ``x/polymer/web-dynamic/v1/detail`` 拿到完整数据。
        """
        params = {
            "timezone_offset": "-480",
            "platform": "web",
            "gaia_source": "main_web",
            "id": dynamic_id,
            "features": (
                "itemOpusStyle,opusBigCover,onlyfansVote,endFooterHidden,decorationCard,"
                "onlyfansAssetsV2,ugcDelete,onlyfansQaCard,editable,opusPrivateVisible,"
                "avatarAutoTheme,sunflowerStyle,cardsEnhance,eva3CardOpus,eva3CardVideo,"
                "eva3CardComment,eva3CardVote,eva3CardUser"
            ),
            "web_location": "333.1368",
            "x-bili-device-req-json": '{"platform":"web","device":"pc","spmid":"333.1368"}',
        }
        params = self._wbi_sign_params(params)
        headers = {**self.headers, "Referer": f"https://t.bilibili.com/{dynamic_id}"}
        response = requests.get(
            "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail",
            headers=headers, params=params, timeout=30,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"web-dynamic detail failed; status_code: {response.status_code}, dynamic_id: {dynamic_id}"
            )
        js = response.json()
        if js.get("code") != 0:
            raise AssertionError(
                f"web-dynamic detail api error; code: {js.get('code')}, message: {js.get('message')}, dynamic_id: {dynamic_id}"
            )
        return js


class ShareMediaDownload(ShareMediaDownloadRestful):
    _SHARE_ENTRY_URL_PATTERNS: List[str] = [
        r"https?://b23\.tv/[A-Za-z0-9]+(?:\?[^\s]*)?",
        r"https?://(?:www\.|m\.)?bilibili\.com/opus/\d+(?:\?[^\s]*)?",
        r"https?://(?:www\.)?bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)(?:/|\?[^\s]*)?",
        r"https?://m\.bilibili\.com/video/(?:BV[a-zA-Z0-9]{10}|av\d+)(?:/|\?[^\s]*)?",
        r"https?://t\.bilibili\.com/\d+(?:\?[^\s]*)?",
    ]

    @classmethod
    def get_share_url_by_share_text(cls, share_text: str) -> str:
        """
        从分享文案或单独 URL 中取出一条 B 站分享入口链接（b23 / 视频页 / Opus / 动态）。
        """
        if share_text.startswith("http") and "\n" not in share_text:
            single = share_text.split()[0].rstrip(".,;)")
            if re.search(r"(?:b23\.tv|bilibili\.com)", single, re.I):
                return single
        for pattern in cls._SHARE_ENTRY_URL_PATTERNS:
            match = re.search(pattern, share_text, flags=re.IGNORECASE)
            if match is not None:
                return match.group(0).rstrip(".,;)")
        raise AssertionError(f"未识别到 B 站分享链接; text: {share_text!r}")

    @cacheout.memoize(ttl=10)
    def get_init_state_by_final_url(self, final_url: str) -> Optional[dict]:
        html = self.get_text_by_url(final_url)

        patterns = [
            r"__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;\s*\(function",
            # r"__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;\s*</script>",
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.DOTALL)
            if not match:
                continue
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def parse_dynamic_id_by_url(url: str) -> Optional[str]:
        """
        ``https://t.bilibili.com/<dynamic_id>?...`` -> ``<dynamic_id>``。
        ``https://m.bilibili.com/opus/<dynamic_id>?...`` 移动端页常返回 412，
        也直接视作动态 ID 走 web-dynamic API。
        """
        match = re.search(r"t\.bilibili\.com/(\d+)", url, flags=re.IGNORECASE)
        if match is not None:
            return match.group(1)
        match = re.search(r"bilibili\.com/opus/(\d+)", url, flags=re.IGNORECASE)
        if match is not None:
            return match.group(1)
        return None

    def get_post_meta_by_share_text(self, share_text: str) -> dict:
        share_url = self.get_share_url_by_share_text(share_text)
        final_url = self.get_final_url_by_share_url(share_url)

        post_meta: Optional[PostMeta] = None

        # 分支 3：t.bilibili.com / m.bilibili.com/opus 走带 WBI 签名的 web-dynamic 接口。
        dynamic_id = self.parse_dynamic_id_by_url(final_url)
        if dynamic_id is not None:
            web_dynamic = self.get_web_dynamic_by_dynamic_id(dynamic_id)
            post_meta = self.build_post_meta_from_web_dynamic_opus_branch_1(web_dynamic, dynamic_id)

        if post_meta is None:
            init_state = self.get_init_state_by_final_url(final_url)
            post_meta = self.build_post_meta_from_init_state_branch_2(init_state)
        if post_meta is None:
            init_state = self.get_init_state_by_final_url(final_url)
            post_meta = self.build_post_meta_from_init_state_branch_3(init_state)

        if post_meta is None:
            raise AssertionError(f"未成功解析到信息；share_url: {share_url}")

        post_meta.share_url = share_url
        post_meta.final_url = final_url
        return post_meta.to_dict()

    @when_error(return_value=None)
    def build_post_meta_from_web_dynamic_opus_branch_1(
        self, web_dynamic: dict, dynamic_id: str,
    ) -> PostMeta:
        """
        ``t.bilibili.com/<dynamic_id>`` 跟跳后落到旧动态页（HTML 不再带
        ``__INITIAL_STATE__``），改用带 WBI 签名的
        ``x/polymer/web-dynamic/v1/detail`` 返回的 item 构建 PostMeta。

        当前仅覆盖 ``DYNAMIC_TYPE_DRAW`` / ``MAJOR_TYPE_OPUS`` 这种图文动态：
        - ``module_dynamic.major.opus.{title, pics[*].url, summary.rich_text_nodes}``
        - ``module_author.{mid, name}``
        - ``module_stat.{like.count, comment.count, forward.count}``

        示例：
            https://b23.tv/WSdPCoP
            -> https://t.bilibili.com/1204343142349799432
        """
        item = web_dynamic["data"]["item"]
        modules = item["modules"]

        author = modules["module_author"]
        dynamic = modules["module_dynamic"]
        major = dynamic["major"]
        opus = major["opus"]
        stat = modules["module_stat"]

        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_web_dynamic_opus_branch_3"
        post_meta.post_id = item["id_str"]

        post_meta.title = opus["title"] or ""

        tags = list()
        desc_parts = list()
        for node in (opus["summary"] or {}).get("rich_text_nodes") or []:
            node_type = node["type"]
            text = node.get("orig_text") or node.get("text") or ""
            if node_type == "RICH_TEXT_NODE_TYPE_TOPIC":
                tags.append(text.strip("#"))
            else:
                desc_parts.append(text)
        post_meta.desc = "".join(desc_parts).strip()
        post_meta.tags = tags

        post_meta.user_id = str(author["mid"])
        post_meta.nickname = author["name"]

        post_meta.liked_count = stat["like"]["count"]
        post_meta.comment_count = stat["comment"]["count"]
        post_meta.share_count = stat["forward"]["count"]

        image_urls = list()
        for pic in opus["pics"]:
            url = pic["url"]
            if isinstance(url, str) and url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            image_urls.append(url)
        post_meta.image_urls = image_urls
        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_init_state_branch_2(self, init_state: dict) -> PostMeta:
        """
        https://www.bilibili.com/video/BV1Me411R79f/?spm_id_from=333.788.recommend_more_video.-1&trackid=web_related_0.router-related-2589621-cb5r7.1779346981141.985
        """
        # print(json.dumps(init_state, ensure_ascii=False, indent=2))

        video_data: dict = init_state.get("videoData")
        if video_data is None:
            return None
        tags: list = init_state.get("tags")
        if tags is None:
            return None

        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_init_state_branch_2"

        if len(video_data) == 2:
            stat = video_data.get("stat", dict())
            owner = video_data.get("owner", dict())
            if len(stat) == 0 and len(owner) == 0:
                error_msg = init_state["error"]["message"]
                post_meta.title = error_msg
                post_meta.desc = error_msg
                return post_meta

        # print(json.dumps(video_data, ensure_ascii=False, indent=2))

        bvid = video_data["bvid"]
        aid = video_data["aid"]
        cid = video_data["cid"]

        post_meta.post_id = bvid
        post_meta.title = video_data["title"]
        post_meta.desc = video_data["desc"]
        post_meta.tags = [item["tag_name"] for item in tags]

        post_meta.user_id = str(video_data["owner"]["mid"])
        post_meta.nickname = video_data["owner"]["name"]

        post_meta.liked_count = video_data["stat"]["like"]
        post_meta.collected_count = video_data["stat"]["favorite"]
        post_meta.comment_count = video_data["stat"]["reply"]
        post_meta.share_count = video_data["stat"]["share"]

        # video_urls
        pages = video_data["pages"]
        video_urls = list()
        for page in pages:
            cid = page["cid"]
            first_frame = page["first_frame"]
            js = self.get_play_url(bvid, cid)
            # print(json.dumps(js, ensure_ascii=False, indent=2))
            video_url = js["data"]["durl"][0]["url"]
            video_urls.append(VideoMeta(
                cover_url=first_frame,
                video_url=video_url,
            ))
        post_meta.video_urls = video_urls
        return post_meta

    @when_error(return_value=None)
    def build_post_meta_from_init_state_branch_3(self, init_state: dict) -> PostMeta:
        """
        https://b23.tv/6UGNFEQ
        https://b23.tv/2s11JkL
        https://b23.tv/tHq7BEg
        :param init_state:
        :return:
        """
        detail: dict = init_state.get("detail")
        if detail is None:
            return None
        modules: list = detail.get("modules")
        if modules is None:
            return None

        post_meta = PostMeta()
        post_meta.post_type = "build_post_meta_from_init_state_branch_2"
        # print(json.dumps(init_state, ensure_ascii=False, indent=2))

        tags = list()
        desc = list()
        image_urls = list()
        for module in modules:
            if not isinstance(module, dict):
                continue
            if module.get("module_type") == "MODULE_TYPE_TOP":
                block = module["module_top"]
                display = block["display"]
                if display["type"] == 1:
                    for item in display["album"]["pics"]:
                        image_urls.append(item["url"])
            if module.get("module_type") == "MODULE_TYPE_TITLE":
                block = module["module_title"]
                post_meta.title = block["text"]
            if module.get("module_type") == "MODULE_TYPE_AUTHOR":
                block = module["module_author"]
                post_meta.user_id = str(block["mid"])
                post_meta.nickname = block["name"]
            if module.get("module_type") == "MODULE_TYPE_TOPIC":
                block = module["module_topic"]
                tags.append(block["name"])
            if module.get("module_type") == "MODULE_TYPE_CONTENT":
                block = module["module_content"]
                for paragraph in block["paragraphs"] or []:
                    if not isinstance(paragraph, dict):
                        continue
                    paragraph_type = paragraph["para_type"]
                    if paragraph_type == 1:
                        # 文本
                        for node in paragraph["text"]["nodes"]:
                            node_type = node["type"]
                            if node_type == "TEXT_NODE_TYPE_WORD":
                                desc.append(node["word"]["words"])
                            elif node_type == "TEXT_NODE_TYPE_RICH":
                                node_rich_type = node["rich"]["type"]
                                if node_rich_type == "RICH_TEXT_NODE_TYPE_TOPIC":
                                    tags.append(node["rich"]["text"])
                    elif paragraph_type == 2:
                        # 图片
                        pic = paragraph["pic"]
                        if pic["style"] == 1:
                            for item in pic["pics"]:
                                image_urls.append(item["url"])
            if module.get("module_type") == "MODULE_TYPE_STAT":
                block = module["module_stat"]
                post_meta.liked_count = block["like"]["count"]
                post_meta.collected_count = block["favorite"]["count"]
                post_meta.comment_count = block["comment"]["count"]
                post_meta.share_count = block["forward"]["count"]

        post_meta.post_id = detail["id_str"]
        post_meta.desc = "\n".join(desc)
        post_meta.tags = tags
        post_meta.image_urls = image_urls

        return post_meta


def main():
    """
    https://b23.tv/rr6HPsb

    :return:
    """
    client = ShareMediaDownload()
    share_text = """
https://www.bilibili.com/video/BV1k9Gv6TEpD/?spm_id_from=333.1387.homepage.video_card.click&vd_source=85f2139356764e5ada5e12e67794b1ae

"""
    post_meta = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(post_meta, ensure_ascii=False, indent=2))

    # post_meta = client.download_media_by_share_text(share_text)
    # print("post_meta:")
    # print(json.dumps(post_meta, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
