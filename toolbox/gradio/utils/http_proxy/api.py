#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
通过 HuggingFace Space 上的 `/http_proxy` 接口做一次 HTTP 中转请求。

设计目标：把 gradio_client.Client 的"调一次 predict"封装成 `requests` 风格的
客户端，调用方几乎不用改代码就能从 `requests` 切到本代理：

    proxy = HttpProxyClient()
    resp = proxy.get("https://httpbin.org/get", params={"q": "hello"})
    print(resp.status_code, resp.json())

    resp = proxy.post("https://httpbin.org/post", json={"a": 1}, timeout=10)
    print(resp.text)

`HttpProxyClient` 内部持有一个 gradio_client.Client（构造较贵，会查询 Space
的 API schema），适合在进程内复用。`HttpProxyResponse` 提供与
`requests.Response` 兼容的常用属性：`status_code / headers / text / content /
json() / ok / raise_for_status() / url`。
"""

import json as _json
from typing import Any, Dict, Mapping, Optional, Union

from gradio_client import Client


DEFAULT_SPACE_URL = "https://miyuki2026-video-platform.hf.space/"
DEFAULT_API_NAME = "/http_proxy"

JSONType = Union[Dict[str, Any], list, str, int, float, bool, None]


class HttpProxyError(RuntimeError):
    """代理调用层面的异常（与目标 URL 自身的 HTTP 状态无关）。"""


class HttpProxyResponse:
    """与 `requests.Response` 鸭子兼容的响应对象。"""

    def __init__(
        self,
        status_code: int,
        headers: Optional[Mapping[str, str]],
        body: Union[str, bytes, None],
        url: str = "",
        request_method: str = "",
    ) -> None:
        self.status_code = int(status_code) if status_code is not None else 0
        self.headers: Dict[str, str] = self._normalize_headers(headers)
        self.url = url
        self.request_method = request_method
        self.encoding = self._guess_encoding(self.headers) or "utf-8"

        if body is None:
            self._content: bytes = b""
            self._text: str = ""
        elif isinstance(body, bytes):
            self._content = body
            self._text = body.decode(self.encoding, errors="replace")
        else:
            self._text = str(body)
            self._content = self._text.encode(self.encoding, errors="replace")

    # 与 requests.Response 对齐的属性 / 方法
    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def reason(self) -> str:
        return self.headers.get("status") or self.headers.get("reason") or ""

    def json(self, **kwargs: Any) -> Any:
        return _json.loads(self._text, **kwargs)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise HttpProxyError(
                f"{self.request_method or 'HTTP'} {self.url} -> "
                f"status_code={self.status_code}"
            )

    def __repr__(self) -> str:
        return f"<HttpProxyResponse [{self.status_code}] {self.url}>"

    @staticmethod
    def _guess_encoding(headers: Mapping[str, str]) -> Optional[str]:
        ct = headers.get("content-type") or headers.get("Content-Type") or ""
        marker = "charset="
        idx = ct.lower().find(marker)
        if idx < 0:
            return None
        return ct[idx + len(marker):].split(";", 1)[0].strip() or None

    @staticmethod
    def _normalize_headers(headers: Any) -> Dict[str, str]:
        """Space 返回的 response_headers 可能是 dict / JSON 字符串 / 键值对列表，
        统一规整为 Dict[str, str]。"""
        if headers is None:
            return {}
        if isinstance(headers, str):
            stripped = headers.strip()
            if not stripped:
                return {}
            try:
                parsed = _json.loads(stripped)
            except _json.JSONDecodeError:
                return {"raw": stripped}
            return HttpProxyResponse._normalize_headers(parsed)
        if isinstance(headers, Mapping):
            return {str(k): str(v) for k, v in headers.items()}
        if isinstance(headers, (list, tuple)):
            result: Dict[str, str] = {}
            for item in headers:
                if isinstance(item, Mapping):
                    for k, v in item.items():
                        result[str(k)] = str(v)
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    result[str(item[0])] = str(item[1])
            return result
        return {"raw": str(headers)}


class HttpProxyClient(object):
    """`requests`-style 客户端：转发到 HF Space 上的 `/http_proxy`。"""

    def __init__(
        self,
        space_url: str = DEFAULT_SPACE_URL,
        api_name: str = DEFAULT_API_NAME,
        default_timeout: float = 30.0,
        default_headers: Optional[Mapping[str, str]] = None,
        default_follow_redirects: bool = True,
        default_verify_ssl: bool = True,
        hf_token: Optional[str] = None,
        lazy: bool = True,
    ) -> None:
        self.space_url = space_url
        self.api_name = api_name
        self.default_timeout = default_timeout
        self.default_headers: Dict[str, str] = dict(default_headers or {})
        self.default_follow_redirects = default_follow_redirects
        self.default_verify_ssl = default_verify_ssl
        self.hf_token = hf_token
        self._client: Optional[Client] = None
        if not lazy:
            self._ensure_client()

    # ------------------------- requests 风格的便捷方法 -------------------------

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

    # ------------------------------- 核心方法 -------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[JSONType] = None,
        data: Optional[Union[Mapping[str, Any], str, bytes]] = None,
        json: Optional[JSONType] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        allow_redirects: Optional[bool] = None,
        verify: Optional[bool] = None,
    ) -> HttpProxyResponse:
        merged_headers: Dict[str, str] = {**self.default_headers}
        if headers:
            merged_headers.update({str(k): str(v) for k, v in headers.items()})

        body_str = self._encode_body(data=data, json=json, headers=merged_headers)
        params_str = self._encode_params(params)
        # Space 的 /http_proxy 把 headers 也声明成 Textbox(str)，必须 JSON 字符串
        headers_str = _json.dumps(merged_headers, ensure_ascii=False) if merged_headers else "{}"

        client = self._ensure_client()
        # 注意：gradio_client.Client.predict 自身有个 `headers` 关键字（给 gradio 自己的 HTTP 头用），
        # 跟 Space 接口同名位置参数冲突，因此这里必须按位置传 8 个参数。
        try:
            status_code, resp_headers, resp_body = client.predict(
                url,
                method.upper(),
                headers_str,
                params_str,
                body_str,
                float(timeout if timeout is not None else self.default_timeout),
                allow_redirects if allow_redirects is not None else self.default_follow_redirects,
                verify if verify is not None else self.default_verify_ssl,
                api_name=self.api_name,
            )
        except Exception as exc:
            raise HttpProxyError(
                f"代理请求失败: {method.upper()} {url} via {self.space_url}{self.api_name}; "
                f"原始错误: {exc}"
            ) from exc

        return HttpProxyResponse(
            status_code=status_code,
            headers=resp_headers,
            body=resp_body,
            url=url,
            request_method=method.upper(),
        )

    # ------------------------------- 内部工具 -------------------------------

    def _ensure_client(self) -> Client:
        if self._client is None:
            kwargs: Dict[str, Any] = {}
            if self.hf_token:
                kwargs["hf_token"] = self.hf_token
            self._client = Client(self.space_url, **kwargs)
        return self._client

    @staticmethod
    def _encode_params(params: Optional[JSONType]) -> str:
        if params is None:
            return "{}"
        if isinstance(params, str):
            return params
        return _json.dumps(params, ensure_ascii=False)

    @staticmethod
    def _encode_body(
        *,
        data: Optional[Union[Mapping[str, Any], str, bytes]],
        json: Optional[JSONType],
        headers: Dict[str, str],
    ) -> str:
        if json is not None:
            headers.setdefault("Content-Type", "application/json")
            return _json.dumps(json, ensure_ascii=False)
        if data is None:
            return "{}"
        if isinstance(data, (bytes, bytearray)):
            return data.decode("utf-8", errors="replace")
        if isinstance(data, str):
            return data
        if isinstance(data, Mapping):
            headers.setdefault("Content-Type", "application/json")
            return _json.dumps(dict(data), ensure_ascii=False)
        return str(data)


# 进程内共享一个默认实例，方便像 `requests.get(...)` 那样直接调用模块函数
_default_client: Optional[HttpProxyClient] = None


def _get_default_client() -> HttpProxyClient:
    global _default_client
    if _default_client is None:
        _default_client = HttpProxyClient()
    return _default_client


def request(method: str, url: str, **kwargs: Any) -> HttpProxyResponse:
    return _get_default_client().request(method, url, **kwargs)


def get(url: str, **kwargs: Any) -> HttpProxyResponse:
    return _get_default_client().get(url, **kwargs)


def post(url: str, **kwargs: Any) -> HttpProxyResponse:
    return _get_default_client().post(url, **kwargs)


def put(url: str, **kwargs: Any) -> HttpProxyResponse:
    return _get_default_client().put(url, **kwargs)


def patch(url: str, **kwargs: Any) -> HttpProxyResponse:
    return _get_default_client().patch(url, **kwargs)


def delete(url: str, **kwargs: Any) -> HttpProxyResponse:
    return _get_default_client().delete(url, **kwargs)


def head(url: str, **kwargs: Any) -> HttpProxyResponse:
    return _get_default_client().head(url, **kwargs)


def options(url: str, **kwargs: Any) -> HttpProxyResponse:
    return _get_default_client().options(url, **kwargs)


def main() -> None:
    proxy = HttpProxyClient()

    print("=== GET https://httpbin.org/get?q=hello ===")
    response = proxy.get("https://httpbin.org/get", params={"q": "hello"})
    print("status_code:", response.status_code)
    print("ok:", response.ok)
    print("headers (top 3):", dict(list(response.headers.items())[:3]))
    print("text[:200]:", response.text[:200])
    try:
        print("json.args:", response.json().get("args"))
    except Exception as exc:
        print("json parse failed:", exc)

    print("\n=== POST https://httpbin.org/post json={'a':1} ===")
    response = proxy.post("https://httpbin.org/post", json={"a": 1}, timeout=20)
    print("status_code:", response.status_code)
    print("text[:200]:", response.text[:200])

    print("\n=== 模块级 get（共享默认 client） ===")
    response = get("https://httpbin.org/headers", headers={"X-Test": "banniu-help"})
    print("status_code:", response.status_code)
    print("text[:200]:", response.text[:200])


if __name__ == "__main__":
    main()
