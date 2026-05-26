#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
与 `requests.utils` 对齐的常用工具函数。

我们的 `HttpProxySession.cookies` 直接用的是 `requests.cookies.RequestsCookieJar`，
所以 cookie 相关工具可以直接 re-export `requests.utils` 的实现，
保证行为与 `requests` 完全一致：

    from toolbox.gradio.utils import http_proxy as requests

    session = requests.Session()
    session.cookies = requests.utils.cookiejar_from_dict({
        "__ac_nonce":     "06a13...",
        "__ac_signature": "_02B4...",
        "__ac_referer":   "__ac_blank",
    })
"""

from requests.utils import (
    add_dict_to_cookiejar,
    cookiejar_from_dict,
    dict_from_cookiejar,
    get_encoding_from_headers,
    parse_dict_header,
    parse_list_header,
    requote_uri,
    urldefragauth,
)

__all__ = [
    "cookiejar_from_dict",
    "dict_from_cookiejar",
    "add_dict_to_cookiejar",
    "get_encoding_from_headers",
    "parse_dict_header",
    "parse_list_header",
    "requote_uri",
    "urldefragauth",
]
