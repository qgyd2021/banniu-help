#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
小黑盒社区「分享链接」元信息与媒体下载。

分享接口 ``/v3/bbs/app/api/web/share`` 在 **禁止自动跟跳** 时，会在 ``302 Location`` 的
``redirect_data`` 中带出 ``title`` / ``description``（无需登录）。

正文里的图片、视频由前端再请求 ``link/tree`` 等接口拉取，未登录时首屏 HTML 往往不含这些 URL，
因此 ``image_urls`` / ``video_urls`` 可能为空；若页面内嵌图链会被尽力收集。
"""
import json
import re
import secrets
import time
import string
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from toolbox.xiaoheihe.xiaoheihe_client import XiaoHeiHeClient

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - optional dependency
    sync_playwright = None
    PlaywrightTimeoutError = Exception


class ShareMediaMeta(XiaoHeiHeClient):
    _DEFAULT_SHARE_H_SRC = "YXBwX3NoYXJl"
    _STATIC_IMG_SUBSTR = (
        "/oa/2024/11/25/94d49a74068aa645772ebeb65ba2f107.png",
        "/oa/2024/11/27/3912834da32296bd985281f8944e75fc.ico",
        "/oa/2024/11/27/4b39f1ec118c4bc0b384a47306163325.png",
        "imgheybox.max-c.com/dev/",
    )
    # 线上网页请求参数（通过网页实际请求抓取）；用于拉取 link/tree 的公开内容
    _TREE_WEB_BOOTSTRAP_PARAMS = {
        "os_type": "web",
        "app": "heybox",
        "client_type": "web",
        "version": "999.0.4",
        "web_version": "2.5",
        "x_client_type": "web",
        "x_app": "heybox_website",
        "heybox_id": "",
        "x_os_type": "Windows",
        "device_info": "Electron",
        "device_id": "36ee1abf745feec644a0c090005ec2e5",
        "hkey": "",
        "_time": "",
        "nonce": "",
        "is_first": 1,
        "page": 1,
        "index": 1,
        "limit": 20,
        "owner_only": 0,
    }
    _TREE_HKEY_CANDIDATES = ("ZIWDX75", "X7ZVD77")

    def __init__(self) -> None:
        super().__init__()
        self._tree_params_override: Dict[str, Any] = {}
        self._tree_headers_override: Dict[str, str] = {}
        self._tree_cookie_override: Dict[str, str] = {}
        self._try_load_default_cookies()

    def _try_load_default_cookies(self) -> None:
        if self.cookies:
            return
        cred_path = Path(__file__).resolve().parents[3] / "dotenv/xiaoheihe_login_credentials.json"
        if not cred_path.is_file():
            return
        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                self.set_cookies(json.load(f))
        except Exception:
            return

    def set_tree_request_overrides(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        注入从浏览器 F12 抓到的 tree 请求参数/请求头/cookie，提高命中率。
        """
        self._tree_params_override = dict(params or {})
        self._tree_headers_override = dict(headers or {})
        self._tree_cookie_override = dict(cookies or {})

    def set_tree_request_from_curl(self, curl_text: str) -> Dict[str, Any]:
        """
        从浏览器复制的 curl 文本中提取 tree 请求参数，自动注入 overrides。
        返回解析后的 params/headers/cookies，便于调用方确认。
        """
        raw = (curl_text or "").strip()
        if not raw:
            raise AssertionError("curl 文本为空")

        url_match = re.search(r"curl\s+['\"](https?://[^'\"]+)['\"]", raw, flags=re.IGNORECASE)
        if not url_match:
            raise AssertionError("未在 curl 中识别到 URL")
        req_url = url_match.group(1)

        parsed = urlparse(req_url)
        query_map = parse_qs(parsed.query, keep_blank_values=True)
        params: Dict[str, Any] = {k: (v[0] if isinstance(v, list) and v else "") for k, v in query_map.items()}
        # 兼容裸键 heybox_id（URL 中可能为 ...&heybox_id&...）
        if "heybox_id" not in params and re.search(r"(?:\?|&)heybox_id(?:&|$)", req_url):
            params["heybox_id"] = ""

        header_pairs = re.findall(r"(?:-H|--header)\s+['\"]([^'\"]+)['\"]", raw)
        headers: Dict[str, str] = {}
        cookies: Dict[str, str] = {}
        for row in header_pairs:
            if ":" not in row:
                continue
            k, v = row.split(":", 1)
            key = k.strip()
            val = v.strip()
            if not key:
                continue
            if key.lower() == "cookie":
                for piece in val.split(";"):
                    piece = piece.strip()
                    if not piece or "=" not in piece:
                        continue
                    ck, cv = piece.split("=", 1)
                    cookies[ck.strip()] = cv.strip()
            else:
                headers[key] = val

        self.set_tree_request_overrides(params=params, headers=headers, cookies=cookies)
        return {"params": params, "headers": headers, "cookies": cookies}

    @staticmethod
    def sanitize_filename(name: str, max_len: int = 80) -> str:
        name = re.sub(r'[\\/:*?"<>|]', "_", (name or "").strip())
        name = re.sub(r"\s+", " ", name).strip(" .")
        if not name:
            name = "untitled"
        return name[:max_len]

    @staticmethod
    def extract_link_id(text_or_url: str) -> str:
        raw = (text_or_url or "").strip()
        patterns = [
            r"[?&]link_id=([0-9a-f]+)",
            r"/app/bbs/link/([0-9a-f]+)",
        ]
        for pat in patterns:
            m = re.search(pat, raw, flags=re.IGNORECASE)
            if m:
                return m.group(1).lower()
        raise AssertionError(f"未识别到 link_id; text: {raw!r}")

    @classmethod
    def build_share_api_url(cls, link_id: str, h_src: Optional[str] = None) -> str:
        hs = h_src or cls._DEFAULT_SHARE_H_SRC
        return (
            f"{cls.api_host}/v3/bbs/app/api/web/share"
            f"?h_camp=link&h_src={hs}&link_id={link_id}"
        )

    @classmethod
    def canonical_web_link_url(cls, link_id: str) -> str:
        return f"{cls.www_host}/app/bbs/link/{link_id}"

    @classmethod
    def _is_noise_img_url(cls, url: str) -> bool:
        u = url.lower()
        if any(s.lower() in u for s in cls._STATIC_IMG_SUBSTR):
            return True
        if u.endswith(".ico"):
            return True
        return False

    @classmethod
    def _parse_redirect_data(cls, location: str) -> Dict[str, Any]:
        if not location:
            return {}
        q = parse_qs(urlparse(location).query)
        raw_list = q.get("redirect_data") or []
        if not raw_list:
            return {}
        raw = raw_list[0]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    @classmethod
    def _parse_og_meta(cls, html: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for m in re.finditer(
            r'<meta[^>]+property="og:([^"]+)"[^>]+content="([^"]*)"', html, flags=re.IGNORECASE
        ):
            out[m.group(1).strip()] = m.group(2).strip()
        return out

    @classmethod
    def _parse_user_from_html(cls, html: str) -> Tuple[str, str]:
        """
        从页面 HTML 中提取用户名和用户 ID。
        优先从 Pinia store 数据中提取登录用户信息。
        """
        username = ""
        user_id = ""

        # 尝试从 Pinia/Nuxt 数据中提取
        # Nuxt/Pinia 使用索引引用格式:
        # [{"UserStore": 14, ...}, {"is_logined": 15, "username": 16, ...}, "actual_username"]
        # 其中 "username": 16 表示 username 字符串在索引 16 处
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
        for script in scripts:
            if "UserStore" not in script:
                continue

            try:
                data = json.loads(script)
            except json.JSONDecodeError:
                continue

            if not isinstance(data, list):
                continue

            # 查找 UserStore 索引
            user_store_idx = None
            for i, element in enumerate(data):
                if isinstance(element, dict) and "UserStore" in element:
                    user_store_idx = element["UserStore"]
                    break

            if user_store_idx is None or user_store_idx >= len(data):
                continue

            user_store = data[user_store_idx]
            if not isinstance(user_store, dict):
                continue

            def resolve_value(idx):
                if idx < 0 or idx >= len(data):
                    return None
                element = data[idx]
                if isinstance(element, str):
                    return element
                if isinstance(element, (int, float)):
                    return element
                if element is None or isinstance(element, bool):
                    return element
                if isinstance(element, list) and len(element) == 2:
                    _, val = element
                    if isinstance(val, str):
                        return val
                    if isinstance(val, (int, float)):
                        return resolve_value(val)
                return None

            # 提取 username
            if "username" in user_store:
                username = resolve_value(user_store["username"]) or ""

            # 提取 heybox_id
            if "heybox_id" in user_store:
                heybox_id = resolve_value(user_store["heybox_id"])
                if heybox_id and isinstance(heybox_id, str):
                    user_id = heybox_id

        # 如果仍未获取到 user_id，尝试从 URL 中提取
        if not user_id:
            uid_match = re.search(r"/user/([0-9a-f]{8,})", html)
            if uid_match:
                user_id = uid_match.group(1)

        return username, user_id

    @classmethod
    def _parse_user_from_redirect(cls, redirect_data: Dict[str, Any]) -> Tuple[str, str]:
        """
        从重定向数据中提取用户信息。
        """
        username = ""
        user_id = ""

        link_block = redirect_data.get("link") if isinstance(redirect_data, dict) else {}
        if isinstance(link_block, dict):
            # 某些情况下 link_block 可能包含用户信息
            username = (link_block.get("username") or link_block.get("nick_name") or link_block.get("user_name") or "").strip()
            user_id = (link_block.get("user_id") or link_block.get("heybox_id") or link_block.get("uid") or "").strip()
            if not username:
                username = cls._parse_username_from_link_title(link_block.get("title") or "")

        return username, user_id

    @classmethod
    def _parse_username_from_link_title(cls, title: str) -> str:
        """
        从小黑盒分享标题中提取用户名（可追溯来源：redirect_data.link.title）。
        仅支持明确格式，避免误识别。
        """
        raw = (title or "").strip()
        if not raw:
            return ""
        patterns = [
            # 示例: "xxx  ace68  使用分享"
            r"^\S+\s+([A-Za-z0-9_][A-Za-z0-9_\-]{1,31})\s+使用",
            # 示例: "作者: 某某"
            r"(?:作者|来自)[：:\s]+([A-Za-z0-9_\-\u4e00-\u9fa5]{2,32})",
        ]
        for pat in patterns:
            m = re.search(pat, raw)
            if m:
                return (m.group(1) or "").strip()
        return ""

    @classmethod
    def _extract_user_from_tree_result(cls, tree_result: Dict[str, Any]) -> Tuple[str, str]:
        """
        从 link/tree 返回中提取用户信息。
        优先读取 result.link.user，其次读取 result.link.userid。
        """
        if not isinstance(tree_result, dict):
            return "", ""
        link_detail = tree_result.get("link") or {}
        if not isinstance(link_detail, dict):
            return "", ""

        username = ""
        user_id = ""

        user_block = link_detail.get("user") or {}
        if isinstance(user_block, dict):
            username = (
                user_block.get("username")
                or user_block.get("nick_name")
                or user_block.get("nickname")
                or user_block.get("user_name")
                or user_block.get("name")
                or ""
            ).strip()
            user_id = str(
                user_block.get("userid")
                or user_block.get("user_id")
                or user_block.get("uid")
                or user_block.get("heybox_id")
                or ""
            ).strip()

        if not user_id:
            user_id = str(
                link_detail.get("userid")
                or link_detail.get("user_id")
                or link_detail.get("uid")
                or link_detail.get("heybox_id")
                or ""
            ).strip()

        if not username:
            # link/tree 常见情况：仅返回 userid，不返回昵称
            # 这时使用稳定占位名，避免误用标题中的分享昵称。
            if user_id:
                username = f"玩家{user_id}"
            else:
                username = cls._parse_username_from_link_title(link_detail.get("title") or "")

        return username, user_id

    @classmethod
    def _collect_media_from_html(cls, html: str) -> Tuple[List[str], List[str]]:
        images: List[str] = []
        videos: List[str] = []
        seen: set = set()

        for m in re.finditer(
            r"https://[^\s\"'<>]+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^\s\"'<>]*)?",
            html,
            flags=re.IGNORECASE,
        ):
            u = m.group(0).rstrip("\\),.;")
            if u in seen or cls._is_noise_img_url(u):
                continue
            if "imgheybox.max-c.com" in u or "heybox" in u.lower():
                seen.add(u)
                images.append(u)

        for m in re.finditer(r"https://[^\s\"'<>]+\.mp4[^\s\"'<>]*", html, flags=re.IGNORECASE):
            u = m.group(0).rstrip("\\),.;")
            if u not in seen:
                seen.add(u)
                videos.append(u)

        return images, videos

    def fetch_share_redirect_payload(self, share_api_url: str) -> Dict[str, Any]:
        response = self.session.get(share_api_url, allow_redirects=False, timeout=30)
        if response.status_code not in (301, 302, 303, 307, 308):
            raise AssertionError(
                f"分享接口未返回重定向; status_code: {response.status_code}, url: {share_api_url}"
            )
        location = response.headers.get("Location") or ""
        redirect_data = self._parse_redirect_data(location)
        link_block = redirect_data.get("link") if isinstance(redirect_data, dict) else None
        if not isinstance(link_block, dict):
            link_block = {}
        return {
            "location": location,
            "redirect_data": redirect_data,
            "link": link_block,
        }

    def fetch_link_page_html(self, link_id: str) -> str:
        url = self.canonical_web_link_url(link_id)
        response = self.session.get(url, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"拉取 Web 页失败; status_code: {response.status_code}, url: {url}")
        return response.text or ""

    @classmethod
    def _collect_media_from_link_text(cls, link_text: str) -> Tuple[List[str], List[str]]:
        """
        link/tree 返回的 result.link.text 是 JSON 字符串数组，元素可能为 text/img/video。
        """
        images: List[str] = []
        videos: List[str] = []
        if not link_text:
            return images, videos
        try:
            blocks = json.loads(link_text)
        except json.JSONDecodeError:
            return images, videos
        if not isinstance(blocks, list):
            return images, videos
        seen_img: set = set()
        seen_vid: set = set()
        for row in blocks:
            if not isinstance(row, dict):
                continue
            row_type = (row.get("type") or "").lower()
            u = row.get("url")
            if not (isinstance(u, str) and u.startswith("http")):
                continue
            if row_type == "img":
                if not cls._is_noise_img_url(u) and u not in seen_img:
                    seen_img.add(u)
                    images.append(u)
            elif row_type in ("video", "mp4"):
                if u not in seen_vid:
                    seen_vid.add(u)
                    videos.append(u)
        return images, videos

    def fetch_link_tree_payload(self, link_id: str) -> Dict[str, Any]:
        """
        从 bbs/app/link/tree 拉取帖子正文结构（含图片块）。
        """
        api = f"{self.api_host}/bbs/app/link/tree"
        base_headers = {
            **self.headers,
            "Accept": "application/json, text/plain, */*",
            "Origin": self.www_host,
            "Referer": self.canonical_web_link_url(link_id),
        }
        if self._tree_headers_override:
            base_headers.update(self._tree_headers_override)
        if self.cookies:
            cookie_str = self.dict_to_cookie_str(self.cookies)
            if cookie_str:
                base_headers["Cookie"] = cookie_str
        if self._tree_cookie_override:
            override_cookie = self.dict_to_cookie_str(self._tree_cookie_override)
            if override_cookie:
                base_headers["Cookie"] = override_cookie

        def random_hkey() -> str:
            chars = string.ascii_uppercase + string.digits
            return "".join(secrets.choice(chars) for _ in range(7))

        static_params = {**self._TREE_WEB_BOOTSTRAP_PARAMS, "link_id": link_id}
        if self._tree_params_override:
            static_params.update(self._tree_params_override)
        static_params["link_id"] = link_id
        dynamic_params = {
            **self._TREE_WEB_BOOTSTRAP_PARAMS,
            "link_id": link_id,
            "_time": str(int(time.time())),
            "nonce": secrets.token_hex(16).upper(),
            "hkey": random_hkey(),
        }
        if self._tree_params_override:
            dynamic_params.update(self._tree_params_override)
        dynamic_params["link_id"] = link_id

        def build_url(params: Dict[str, Any]) -> str:
            # 小黑盒该接口对 heybox_id 的空值格式较敏感，使用裸键 "heybox_id"
            items: List[Tuple[str, str]] = []
            for k, v in params.items():
                if k == "heybox_id" and (v is None or str(v) == ""):
                    continue
                items.append((k, str(v)))
            query = urlencode(items)
            return f"{api}?{query}&heybox_id"

        for params_template in (static_params, dynamic_params):
            hkeys = [params_template.get("hkey")] if params_template.get("hkey") else []
            hkeys.extend(self._TREE_HKEY_CANDIDATES)
            hkeys.append(random_hkey())
            for hkey in hkeys:
                params = {**params_template, "hkey": hkey}
                url = build_url(params)
                for requester in (
                    lambda: self.session.get(url, headers=base_headers, timeout=30),
                    lambda: requests.get(url, headers=base_headers, timeout=30),
                ):
                    try:
                        response = requester()
                    except Exception:
                        continue
                    if response.status_code != 200:
                        continue
                    try:
                        js = response.json()
                    except ValueError:
                        continue
                    if js.get("status") != "ok":
                        continue
                    result = js.get("result") or {}
                    if isinstance(result, dict):
                        return result

        # 兜底：模拟浏览器访问页面，直接读取 link/tree 响应体。
        browser_result = self._fetch_link_tree_payload_via_browser(link_id)
        if isinstance(browser_result, dict) and browser_result:
            return browser_result
        return {}

    def _fetch_link_tree_payload_via_browser(self, link_id: str) -> Dict[str, Any]:
        """
        使用浏览器执行页面脚本并抓取 /bbs/app/link/tree 的真实响应。
        该方式可规避 hkey/nonce/_time 的时效问题。
        """
        if sync_playwright is None:
            return {}

        target_url = self.canonical_web_link_url(link_id)
        captured: Dict[str, Any] = {}

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=self.headers.get("User-Agent", "Mozilla/5.0"),
                    locale="zh-CN",
                )
                page = context.new_page()

                def on_response(resp):
                    if "/bbs/app/link/tree" not in resp.url:
                        return
                    if f"link_id={link_id}" not in resp.url:
                        return
                    try:
                        js = resp.json()
                    except Exception:
                        return
                    if js.get("status") != "ok":
                        return
                    result = js.get("result") or {}
                    if isinstance(result, dict) and result:
                        captured.update(result)

                page.on("response", on_response)
                try:
                    page.goto(target_url, wait_until="networkidle", timeout=30000)
                except PlaywrightTimeoutError:
                    pass

                # 给异步请求留短暂窗口
                page.wait_for_timeout(1500)

                context.close()
                browser.close()
        except Exception:
            return {}

        return captured

    def get_post_meta_by_share_url(self, share_url: str) -> Dict[str, Any]:
        link_id = self.extract_link_id(share_url)
        share_api = share_url if "api.xiaoheihe.cn" in share_url else self.build_share_api_url(link_id)
        redir = self.fetch_share_redirect_payload(share_api)
        link_block = redir["link"]
        title = (link_block.get("title") or "").strip()
        desc = (link_block.get("description") or "").strip()

        # 尝试从重定向数据中提取用户信息
        username, user_id = self._parse_user_from_redirect(redir.get("redirect_data", {}))

        html = self.fetch_link_page_html(link_id)
        img_extra, vid_extra = self._collect_media_from_html(html)
        tree_result = self.fetch_link_tree_payload(link_id)
        tree_username, tree_user_id = self._extract_user_from_tree_result(tree_result)
        if tree_user_id:
            user_id = tree_user_id
            # 以 tree 的用户体系为准：若无真实昵称则统一使用“玩家{userid}”
            username = tree_username or f"玩家{tree_user_id}"
        else:
            if not username:
                username = tree_username
            if not user_id:
                user_id = tree_user_id
        link_detail = (tree_result.get("link") or {}) if isinstance(tree_result, dict) else {}
        if isinstance(link_detail, dict):
            tree_images, tree_videos = self._collect_media_from_link_text(str(link_detail.get("text") or ""))
            if tree_images:
                img_extra = tree_images
            if tree_videos:
                vid_extra = tree_videos
            if not title:
                title = (link_detail.get("title") or "").strip()
            if not desc:
                desc = (link_detail.get("description") or "").strip()

            # 尝试从 link_detail 中提取用户信息（适用于小黑盒站内帖子）
            if not username:
                username = (link_detail.get("username") or link_detail.get("nick_name") or link_detail.get("user_name") or "").strip()
            if not user_id:
                user_id = (link_detail.get("user_id") or link_detail.get("heybox_id") or link_detail.get("uid") or "").strip()

        # 如果仍未获取到用户信息，尝试从 HTML 中提取
        if not username or not user_id:
            html_username, html_user_id = self._parse_user_from_html(html)
            username = username or html_username
            user_id = user_id or html_user_id

        if not title:
            og = self._parse_og_meta(html)
            title = (og.get("title") or "").split(" - ")[0].strip()
        if not desc:
            og = self._parse_og_meta(html)
            desc = (og.get("description") or "").strip()

        final_url = self.canonical_web_link_url(link_id)
        image_url_candidates = [[u] for u in img_extra]
        video_url_candidates = [[u] for u in vid_extra]
        media_type = "video" if vid_extra else ("image" if img_extra else "text")
        if vid_extra and img_extra:
            media_type = "mixed"

        return {
            "post_type": "xiaoheihe_link",
            "link_id": link_id,
            "title": title or link_id,
            "desc": desc,
            "caption": desc,
            "media_type": media_type,
            "final_url": final_url,
            "image_urls": list(img_extra),
            "image_url_candidates": image_url_candidates,
            "video_urls": list(vid_extra),
            "video_url_candidates": video_url_candidates,
            "username": username,
            "user_id": user_id,
        }

class ShareMediaDownload(ShareMediaMeta):
    @classmethod
    def get_share_url_by_share_text(cls, text: str) -> str:
        patterns = [
            r"https?://api\.xiaoheihe\.cn/v3/bbs/app/api/web/share\?[^\s]+",
            r"https?://www\.xiaoheihe\.cn/app/bbs/link/[0-9a-f]+[^\s]*",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                return m.group(0).rstrip(".,;)")
        if re.search(r"[0-9a-f]{10,}", text, re.I):
            lid = cls.extract_link_id(text)
            return cls.build_share_api_url(lid)
        raise AssertionError(f"未找到小黑盒分享链接; text: {text!r}")

    def get_post_meta_by_share_text(self, text: str) -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.get_post_meta_by_share_url(share_url)

    def download_file(self, url: str, filename: Path, referer: Optional[str] = None) -> Path:
        filename = Path(filename)
        filename.parent.mkdir(parents=True, exist_ok=True)
        headers = {
            **self.headers,
            "Referer": referer or self.www_host + "/",
        }
        response = self.session.get(url, headers=headers, stream=True, timeout=120)
        if response.status_code != 200:
            raise AssertionError(f"下载失败; status_code: {response.status_code}, url: {url}")
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return filename

    def download_media_by_share_url(
        self,
        share_url: str,
        output_dir: str = "output_xiaoheihe_media",
        post_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = post_meta or self.get_post_meta_by_share_url(share_url)
        referer = row.get("final_url") or self.www_host + "/"

        output_dir_path = Path(output_dir)
        key = row.get("link_id") or "link"
        title_slug = self.sanitize_filename(row.get("title") or key)
        save_dir = output_dir_path / f"{key}_{title_slug}"
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded_images: List[str] = []
        for idx, image_url in enumerate(row.get("image_urls") or [], start=1):
            ext = ".jpg"
            lower = image_url.split("?", 1)[0].lower()
            if lower.endswith(".png"):
                ext = ".png"
            elif lower.endswith(".webp"):
                ext = ".webp"
            elif lower.endswith(".gif"):
                ext = ".gif"
            path = save_dir / f"image_{idx:02d}{ext}"
            self.download_file(image_url, path, referer=referer)
            downloaded_images.append(path.as_posix())

        downloaded_videos: List[str] = []
        for idx, video_url in enumerate(row.get("video_urls") or [], start=1):
            group: List[str] = []
            cands = row.get("video_url_candidates") or []
            if idx - 1 < len(cands):
                group = cands[idx - 1] or []
            pick = group[0] if group else video_url
            path = save_dir / f"video_{idx:02d}.mp4"
            self.download_file(pick, path, referer=referer)
            downloaded_videos.append(path.as_posix())

        meta = {
            **row,
            "downloaded_images": downloaded_images,
            "downloaded_videos": downloaded_videos,
            "save_dir": save_dir.as_posix(),
        }
        with open(save_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    def download_media_by_share_text(self, text: str, output_dir: str = "output_xiaoheihe_media") -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.download_media_by_share_url(share_url=share_url, output_dir=output_dir)


def main() -> None:
    client = ShareMediaDownload()
    cred_path = Path(__file__).resolve().parents[3] / "dotenv/xiaoheihe_login_credentials.json"
    if cred_path.is_file():
        with open(cred_path, "r", encoding="utf-8") as f:
            client.set_cookies(json.load(f))

    share_text = """
https://api.xiaoheihe.cn/v3/bbs/app/api/web/share?h_camp=link&h_src=YXBwX3NoYXJl&link_id=14f971c83d09
"""
    result = client.get_post_meta_by_share_text(share_text)
    print("post_meta:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
