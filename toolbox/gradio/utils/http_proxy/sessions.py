#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
`HttpProxySession`：与 `requests.Session` 鸭子兼容的会话对象。

在多次请求之间保留：
  - `session.headers`   ：默认请求头（每次请求都会带）
  - `session.cookies`   ：RequestsCookieJar，自动解析响应的 Set-Cookie 并在
                          后续请求里按 RFC 6265 简化规则带上 Cookie 头
  - `session.params`    ：默认查询参数
  - `session.timeout / verify / allow_redirects`：默认请求级参数

典型用例（先拿一次 Set-Cookie，再用 cookie 访问后续接口）：

    with HttpProxySession() as session:
        session.headers["User-Agent"] = "..."
        session.get("https://www.douyin.com/")              # 自动入袋 __ac_nonce
        # ... 本地算出 __ac_signature ...
        session.cookies.set("__ac_signature", sig,
                            domain=".douyin.com", path="/")
        session.get("https://www.douyin.com/aweme/...")     # 会自动带三件套
"""

import time
from http.cookies import SimpleCookie
from typing import Any, Dict, List, Mapping, Optional, Union
from urllib.parse import urlparse

from requests.cookies import RequestsCookieJar

from .api import HttpProxyClient, HttpProxyResponse, JSONType, _get_default_client


class HttpProxySession(object):
    """与 `requests.Session` 鸭子兼容的会话对象。

    底层 HTTP 转发器（`HttpProxyClient` -> `gradio_client.Client`）的实例化
    比较贵（一次实例化会触发 Space 的 API schema 请求），因此默认会与模块级
    `get/post/...` 共用同一个进程内 `_default_client`，避免每次 `Session()`
    都重新加载 Space。每个 session 仅独享自己的 `headers/cookies/params`。

    若需要使用独立的 client（例如指定不同的 Space URL / hf_token），可以
    显式传入：

        # 方式 1：传 client_kwargs，会新建一个独立 client
        session = HttpProxySession(space_url="https://my.hf.space/")

        # 方式 2：传一个已构造好的 client，多个 session 共享它
        my_client = HttpProxyClient(space_url="https://my.hf.space/")
        s1 = HttpProxySession(client=my_client)
        s2 = HttpProxySession(client=my_client)
    """

    def __init__(
        self,
        client: Optional[HttpProxyClient] = None,
        **client_kwargs: Any,
    ) -> None:
        if client is not None:
            if client_kwargs:
                raise TypeError("传入 client 时不能再传 client 构造参数")
        elif client_kwargs:
            # 用户给出自定义构造参数，需要一个独立 client，不复用进程内默认 client
            client = HttpProxyClient(**client_kwargs)
        else:
            # 默认共用进程内 _default_client，避免重复实例化 gradio_client.Client
            client = _get_default_client()
        self._client = client

        self.headers: Dict[str, str] = {}
        self.cookies: RequestsCookieJar = RequestsCookieJar()
        self.params: Dict[str, Any] = {}
        self.timeout: Optional[float] = None
        self.verify: Optional[bool] = None
        self.allow_redirects: Optional[bool] = None

    # ----- 上下文管理器 -----

    def __enter__(self) -> "HttpProxySession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.cookies.clear()
        self.headers.clear()
        self.params.clear()

    # ----- requests 风格便捷方法 -----

    def get(self, url: str, **kwargs: Any) -> HttpProxyResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> HttpProxyResponse:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> HttpProxyResponse:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> HttpProxyResponse:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> HttpProxyResponse:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> HttpProxyResponse:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> HttpProxyResponse:
        return self.request("OPTIONS", url, **kwargs)

    # ----- 核心方法 -----

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[JSONType] = None,
        data: Optional[Union[Mapping[str, Any], str, bytes]] = None,
        json: Optional[JSONType] = None,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Union[Mapping[str, str], RequestsCookieJar]] = None,
        timeout: Optional[float] = None,
        allow_redirects: Optional[bool] = None,
        verify: Optional[bool] = None,
    ) -> HttpProxyResponse:
        merged_headers: Dict[str, str] = {
            str(k): str(v) for k, v in self.headers.items()
        }
        if headers:
            merged_headers.update({str(k): str(v) for k, v in headers.items()})

        merged_params = self._merge_params(self.params, params)

        request_jar = self._build_request_jar(cookies)
        cookie_header = self._build_cookie_header(request_jar, url)
        if cookie_header:
            existing = merged_headers.get("Cookie")
            merged_headers["Cookie"] = (
                f"{existing}; {cookie_header}" if existing else cookie_header
            )

        response = self._client.request(
            method,
            url,
            params=merged_params,
            data=data,
            json=json,
            headers=merged_headers,
            timeout=timeout if timeout is not None else self.timeout,
            allow_redirects=(
                allow_redirects
                if allow_redirects is not None
                else self.allow_redirects
            ),
            verify=verify if verify is not None else self.verify,
        )

        self._extract_set_cookie(response.headers, url)
        return response

    # ----- 内部工具：cookies / params / 域名 / 路径匹配 -----

    def _build_request_jar(
        self, extra: Optional[Union[Mapping[str, str], RequestsCookieJar]]
    ) -> RequestsCookieJar:
        jar = RequestsCookieJar()
        jar.update(self.cookies)
        if not extra:
            return jar
        if isinstance(extra, RequestsCookieJar):
            jar.update(extra)
        elif isinstance(extra, Mapping):
            for k, v in extra.items():
                jar.set(str(k), str(v))
        return jar

    def _build_cookie_header(self, jar: RequestsCookieJar, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"
        is_secure = parsed.scheme.lower() == "https"
        now = time.time()
        parts: List[str] = []
        for cookie in jar:
            if not self._domain_matches(host, cookie.domain or ""):
                continue
            if not self._path_matches(path, cookie.path or "/"):
                continue
            if getattr(cookie, "secure", False) and not is_secure:
                continue
            expires = getattr(cookie, "expires", None)
            if expires is not None and expires < now:
                continue
            parts.append(f"{cookie.name}={cookie.value}")
        return "; ".join(parts)

    def _extract_set_cookie(
        self, response_headers: Dict[str, str], url: str
    ) -> None:
        raw = response_headers.get("set-cookie") or response_headers.get("Set-Cookie")
        if not raw:
            return
        parsed_host = (urlparse(url).hostname or "").lower()
        try:
            simple = SimpleCookie()
            simple.load(raw)
        except Exception:
            return
        for key, morsel in simple.items():
            domain = (morsel.get("domain") or parsed_host or "").lstrip(".")
            path = morsel.get("path") or "/"
            secure = bool(morsel.get("secure"))
            kwargs: Dict[str, Any] = {
                "domain": domain or None,
                "path": path,
                "secure": secure,
            }
            expires_ts = self._parse_expires(morsel)
            if expires_ts is not None:
                kwargs["expires"] = expires_ts
            self.cookies.set(key, morsel.value, **kwargs)

    # ----- 辅助函数 -----

    @staticmethod
    def _merge_params(
        default: Mapping[str, Any], override: Optional[JSONType]
    ) -> Optional[JSONType]:
        if not default and override is None:
            return None
        if override is None:
            return dict(default) if default else None
        if isinstance(override, Mapping):
            merged: Dict[str, Any] = dict(default or {})
            merged.update(override)
            return merged
        return override  # 字符串 / 列表等直接透传

    @staticmethod
    def _domain_matches(request_host: str, cookie_domain: str) -> bool:
        if not cookie_domain:
            return True
        host = request_host.lower().lstrip(".")
        domain = cookie_domain.lower().lstrip(".")
        return host == domain or host.endswith("." + domain)

    @staticmethod
    def _path_matches(request_path: str, cookie_path: str) -> bool:
        if not cookie_path or cookie_path == "/":
            return True
        if request_path == cookie_path:
            return True
        if request_path.startswith(cookie_path):
            if cookie_path.endswith("/"):
                return True
            tail = len(cookie_path)
            if len(request_path) > tail and request_path[tail] == "/":
                return True
        return False

    @staticmethod
    def _parse_expires(morsel: Any) -> Optional[float]:
        max_age = morsel.get("max-age")
        if max_age:
            try:
                return time.time() + int(max_age)
            except (TypeError, ValueError):
                pass
        expires = morsel.get("expires")
        if expires:
            for fmt in (
                "%a, %d %b %Y %H:%M:%S GMT",
                "%a, %d-%b-%Y %H:%M:%S GMT",
                "%a, %d-%b-%y %H:%M:%S GMT",
            ):
                try:
                    return time.mktime(time.strptime(expires, fmt))
                except (TypeError, ValueError):
                    continue
        return None


def main() -> None:
    print("=== HttpProxySession：默认 headers/params + cookie 自动持久化 ===")
    with HttpProxySession() as session:
        session.headers.update({"User-Agent": "banniu-help/session-demo"})
        session.params.update({"trace": "session-demo"})

        response = session.get(
            "https://httpbin.org/cookies/set",
            params={"foo": "bar"},
            allow_redirects=False,
        )
        print("set-cookie status:", response.status_code)
        print("session.cookies after set:", dict(session.cookies))

        response = session.get("https://httpbin.org/cookies")
        print("cookies echo:", response.text[:200])

        response = session.get("https://httpbin.org/get")
        print("headers echo:", response.text[:300])


if __name__ == "__main__":
    main()
