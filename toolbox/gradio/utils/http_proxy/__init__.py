#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
HF Space `/http_proxy` 的客户端封装。

设计成 `requests` 的 drop-in 替代品，方便测试时最小化代码改动：

    from toolbox.gradio.utils import http_proxy as requests

    resp = requests.get("https://httpbin.org/get", params={"q": "hi"})
    resp.raise_for_status()
    print(resp.status_code, resp.json())

    with requests.Session() as session:
        session.headers["User-Agent"] = "demo"
        session.get("https://www.douyin.com/")

    try:
        requests.get(url, timeout=5)
    except requests.exceptions.RequestException as exc:
        ...

公开 API：

  - 类：`HttpProxyClient` / `HttpProxySession` / `HttpProxyResponse` / `HttpProxyError`
  - `requests` 同名别名：`Session` / `Response` / `RequestException` / `ConnectionError` / `HTTPError` / `Timeout`
  - 模块级函数：`request / get / post / put / patch / delete / head / options`
  - `exceptions` 子模块：与 `requests.exceptions` 对齐
  - `codes`：常用 HTTP 状态码常量集
"""

from types import SimpleNamespace

from . import exceptions, utils
from .api import (
    DEFAULT_API_NAME,
    DEFAULT_SPACE_URL,
    HttpProxyClient,
    HttpProxyError,
    HttpProxyResponse,
    JSONType,
    delete,
    get,
    head,
    options,
    patch,
    post,
    put,
    request,
)
from .sessions import HttpProxySession

# ----------------------------------------------------------------------------
# 与 `requests` 顶层 API 同名的别名（drop-in 用）
# ----------------------------------------------------------------------------
Session = HttpProxySession
Response = HttpProxyResponse
RequestException = HttpProxyError
ConnectionError = HttpProxyError  # noqa: A001 与 requests 一致，shadow 内置
HTTPError = HttpProxyError
Timeout = HttpProxyError

# 常用 HTTP 状态码，对齐 `requests.codes.ok / requests.codes.not_found` 用法
codes = SimpleNamespace(
    ok=200,
    created=201,
    accepted=202,
    no_content=204,
    moved_permanently=301,
    found=302,
    see_other=303,
    not_modified=304,
    temporary_redirect=307,
    permanent_redirect=308,
    bad_request=400,
    unauthorized=401,
    forbidden=403,
    not_found=404,
    method_not_allowed=405,
    not_acceptable=406,
    request_timeout=408,
    conflict=409,
    gone=410,
    too_many_requests=429,
    internal_server_error=500,
    bad_gateway=502,
    service_unavailable=503,
    gateway_timeout=504,
)


__all__ = [
    # 工具自家命名（清晰）
    "HttpProxyClient",
    "HttpProxySession",
    "HttpProxyResponse",
    "HttpProxyError",
    "JSONType",
    "DEFAULT_SPACE_URL",
    "DEFAULT_API_NAME",
    # requests 兼容命名（drop-in）
    "Session",
    "Response",
    "RequestException",
    "ConnectionError",
    "HTTPError",
    "Timeout",
    "codes",
    "exceptions",
    "utils",
    # 模块级方法
    "request",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
]
