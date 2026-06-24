#!/usr/bin/python3
# -*- coding: utf-8 -*-
from typing import ClassVar, List


class DouyinHtmlUtils(object):
    ANTI_CRAWL_KEYWORDS: ClassVar[List[str]] = [
        "argus-csp-token",
        "Please wait...",
    ]

    @classmethod
    def has_user_profile_data(cls, html: str) -> bool:
        return any(
            marker in html
            for marker in ("secUid", "followerCount", "follower_count")
        )

    @classmethod
    def has_embedded_aweme_data(cls, html: str) -> bool:
        if not html:
            return False
        if "_ROUTER_DATA" in html:
            return True
        if "awemeId" in html and "authorInfo" in html:
            return True
        if "videoInfoRes" in html:
            return True
        return False

    @classmethod
    def is_anti_crawl_user_page(cls, html: str) -> bool:
        if not html:
            return True
        if cls.has_user_profile_data(html):
            return False
        return any(key in html for key in cls.ANTI_CRAWL_KEYWORDS)

    @classmethod
    def is_anti_crawl_aweme_page(cls, html: str) -> bool:
        if not html:
            return True
        if cls.has_embedded_aweme_data(html):
            return False
        if cls.has_user_profile_data(html):
            return False
        if "window.location.reload()" in html and "byted_acrawler" in html:
            return True
        if any(key in html for key in cls.ANTI_CRAWL_KEYWORDS):
            return True
        if len(html) < 20000 and "__pace_f" not in html and "_ROUTER_DATA" not in html:
            return True
        return False
