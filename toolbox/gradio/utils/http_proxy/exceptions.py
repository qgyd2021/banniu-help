#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
与 `requests.exceptions` 名字对齐的异常别名，便于直接用：

    from toolbox.gradio.utils import http_proxy as requests

    try:
        requests.get(url)
    except requests.exceptions.RequestException as exc:
        ...
"""

from .api import HttpProxyError

RequestException = HttpProxyError
ConnectionError = HttpProxyError  # noqa: A001  与 requests 对齐，确实会 shadow 内置
HTTPError = HttpProxyError
Timeout = HttpProxyError
ConnectTimeout = HttpProxyError
ReadTimeout = HttpProxyError
TooManyRedirects = HttpProxyError
URLRequired = HttpProxyError
InvalidURL = HttpProxyError
InvalidSchema = HttpProxyError
MissingSchema = HttpProxyError
ChunkedEncodingError = HttpProxyError
ContentDecodingError = HttpProxyError
StreamConsumedError = HttpProxyError
RetryError = HttpProxyError
UnrewindableBodyError = HttpProxyError
ProxyError = HttpProxyError
SSLError = HttpProxyError
JSONDecodeError = HttpProxyError

__all__ = [
    "RequestException",
    "ConnectionError",
    "HTTPError",
    "Timeout",
    "ConnectTimeout",
    "ReadTimeout",
    "TooManyRedirects",
    "URLRequired",
    "InvalidURL",
    "InvalidSchema",
    "MissingSchema",
    "ChunkedEncodingError",
    "ContentDecodingError",
    "StreamConsumedError",
    "RetryError",
    "UnrewindableBodyError",
    "ProxyError",
    "SSLError",
    "JSONDecodeError",
]
