#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
参考 bilibili_client.py 风格实现的小红书登录客户端。

功能：
1. 扫码登录（终端打印二维码）
2. 凭据文件登录
3. Cookie 登录态校验
"""
import argparse
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
import requests.utils

from project_settings import project_path
from toolbox.design_patterns.singleton import ParamsSingleton

logger = logging.getLogger("toolbox")

QR_WAITING = 0
QR_SCANNED = 1
QR_CONFIRMED = 2


class XiaoHongShuUtils(object):
    api_host = "https://edith.xiaohongshu.com"
    www_host = "https://www.xiaohongshu.com"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    }

    @staticmethod
    def generate_a1() -> str:
        prefix = "".join(random.choices("0123456789abcdef", k=24))
        ts = str(int(time.time() * 1000))
        suffix = "".join(random.choices("0123456789abcdef", k=15))
        return prefix + ts + suffix

    @staticmethod
    def generate_webid() -> str:
        return "".join(random.choices("0123456789abcdef", k=32))

    @staticmethod
    def dict_to_cookie_str(cookies: Dict[str, str]) -> str:
        return "; ".join(f"{k}={v}" for k, v in cookies.items() if v is not None and str(v) != "")

    @classmethod
    def get_xhshow_pair(cls) -> Tuple[Any, Any]:
        """
        小红书 edith 登录接口需要签名。
        """
        try:
            from xhshow import CryptoConfig, SessionManager, Xhshow
        except ImportError as e:
            raise AssertionError("扫码登录依赖 xhshow，请先安装: pip install xhshow") from e

        cfg = CryptoConfig().with_overrides(PUBLIC_USERAGENT=cls.headers["User-Agent"])
        return Xhshow(cfg), SessionManager(cfg)

    @classmethod
    def _parse_api_response(cls, response: requests.Response, uri: str) -> dict:
        """
        小红书部分登录接口会返回非常规状态码（如 471），但 body 里的 success 仍为 true。
        因此这里优先按 JSON 业务字段判定，不仅依赖 HTTP 状态码。
        """
        try:
            js = response.json()
        except ValueError as e:
            raise AssertionError(
                f"request failed; status_code: {response.status_code}, uri: {uri}, text: {response.text[:600]}"
            ) from e

        if js.get("success"):
            data = js.get("data", {})
            return data if isinstance(data, dict) else {}

        raise AssertionError(
            f"xhs api failed; status_code: {response.status_code}, uri: {uri}, body: "
            f"{json.dumps(js, ensure_ascii=False)[:800]}"
        )

    @classmethod
    def signed_post(
        cls,
        uri: str,
        cookies: Dict[str, str],
        payload: dict,
        xh: Any,
        sm: Any,
        header_overrides: Optional[Dict[str, str]] = None,
    ) -> dict:
        sign_headers = xh.sign_headers_post(uri, cookies, payload=payload, session=sm)
        headers = {
            **cls.headers,
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": cls.www_host,
            "Referer": f"{cls.www_host}/",
            "Cookie": cls.dict_to_cookie_str(cookies),
            **sign_headers,
        }
        if header_overrides:
            headers.update(header_overrides)

        response = requests.post(
            f"{cls.api_host}{uri}",
            headers=headers,
            data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            timeout=60,
        )
        for name, value in response.cookies.items():
            if value is not None and str(value) != "":
                cookies[str(name)] = str(value)
        return cls._parse_api_response(response=response, uri=uri)

    @classmethod
    def signed_get(
        cls,
        uri: str,
        cookies: Dict[str, str],
        params: dict,
        xh: Any,
        sm: Any,
    ) -> dict:
        query_uri = xh.build_url(uri, params)
        sign_headers = xh.sign_headers_get(uri, cookies, params=params, session=sm)
        headers = {
            **cls.headers,
            "Origin": cls.www_host,
            "Referer": f"{cls.www_host}/",
            "Cookie": cls.dict_to_cookie_str(cookies),
            **sign_headers,
        }
        response = requests.get(f"{cls.api_host}{query_uri}", headers=headers, timeout=60)
        for name, value in response.cookies.items():
            if value is not None and str(value) != "":
                cookies[str(name)] = str(value)
        return cls._parse_api_response(response=response, uri=uri)


class XiaoHongShuClient(XiaoHongShuUtils, ParamsSingleton):
    def __init__(self):
        if not self._initialized:
            self.credentials = None
            self.cookies = None
            self._session = requests.Session()
            self._session.trust_env = False
            self._initialized = True

    @property
    def session(self):
        # 每次都同步最新 cookies，避免先匿名访问后再登录导致会话未刷新
        self._session.headers = self.headers
        self._session.cookies = requests.utils.cookiejar_from_dict(self.cookies or {})
        return self._session

    @staticmethod
    def _sanitize_initial_state_json(raw: str) -> str:
        s = re.sub(r"\bundefined\b", "null", raw)
        s = re.sub(r"\bNaN\b", "null", s)
        s = re.sub(r"\bInfinity\b", "null", s)
        return s

    @classmethod
    def parse_initial_state(cls, html: str) -> Optional[Dict[str, Any]]:
        needle = "window.__INITIAL_STATE__="
        pos = html.find(needle)
        if pos < 0:
            return None
        start = pos + len(needle)
        end = html.find("</script>", start)
        if end < 0:
            return None
        raw = html[start:end].strip()
        if not raw:
            return None
        try:
            return json.loads(cls._sanitize_initial_state_json(raw))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_user_id(data: dict) -> str:
        login_info = data.get("login_info")
        if isinstance(login_info, dict) and login_info.get("user_id"):
            return str(login_info["user_id"])
        if data.get("user_id"):
            return str(data["user_id"])
        if data.get("userid"):
            return str(data["userid"])
        return ""

    @staticmethod
    def _merge_cookies(dst: dict, response: requests.Response):
        for name, value in response.cookies.items():
            if value is not None and str(value) != "":
                dst[str(name)] = str(value)

    @staticmethod
    def _merge_login_session(cookies: dict, data: dict):
        login_info = data.get("login_info")
        if not isinstance(login_info, dict):
            login_info = {}
        session = data.get("session") or login_info.get("session")
        secure_session = data.get("secure_session") or login_info.get("secure_session")
        if session:
            cookies["web_session"] = str(session)
        if secure_session:
            cookies["web_session_sec"] = str(secure_session)

    def set_cookies(self, cookies: dict):
        self.cookies = cookies
        return self.cookies

    def login_with_qrcode_url(self, timeout_s: int = 240):
        """
        终端二维码登录流程（风格对齐 bilibili 的 login_with_qrcode_url）。
        """
        input("请先放大终端窗口，确保二维码完整展示；按回车继续: ")

        xh, sm = self.get_xhshow_pair()
        cookies = {
            "a1": self.generate_a1(),
            "webId": self.generate_webid(),
        }

        try:
            activate_data = self.signed_post("/api/sns/web/v1/login/activate", cookies, {}, xh, sm)
            self._merge_login_session(cookies, activate_data)
        except Exception:
            logger.debug("login activate failed (ignored)", exc_info=True)

        qrcode_data = self.signed_post(
            "/api/sns/web/v1/login/qrcode/create",
            cookies,
            {"qr_type": 1},
            xh,
            sm,
        )
        qrcode_url = qrcode_data["url"]
        qr_id = qrcode_data["qr_id"]
        code = qrcode_data["code"]

        try:
            import qrcode
        except ImportError as e:
            raise AssertionError("终端展示二维码依赖 qrcode，请先安装: pip install qrcode") from e

        qr = qrcode.QRCode()
        qr.add_data(qrcode_url)
        qr.print_ascii()
        print("Or copy this link to your phone XiaoHongShu:", qrcode_url)

        deadline = time.time() + timeout_s
        last_status = -1
        while time.time() < deadline:
            time.sleep(3)
            status_data = self.signed_post(
                "/api/qrcode/userinfo",
                cookies,
                {"qrId": qr_id, "code": code},
                xh,
                sm,
                header_overrides={"service-tag": "webcn"},
            )
            code_status = int(status_data.get("codeStatus", -1))
            if code_status != last_status:
                last_status = code_status
                if code_status == QR_SCANNED:
                    print("已扫码，请确认登录！")
                elif code_status == QR_CONFIRMED:
                    print("登录已确认，正在拉取会话…")

            if code_status == QR_CONFIRMED:
                expected_user_id = str(status_data.get("userId", "")).strip()
                completion_data = {}
                for _ in range(5):
                    completion_data = self.signed_get(
                        "/api/sns/web/v1/login/qrcode/status",
                        cookies,
                        {"qr_id": qr_id, "code": code},
                        xh,
                        sm,
                    )
                    self._merge_login_session(cookies, completion_data)
                    if cookies.get("web_session"):
                        break
                    time.sleep(1)

                if expected_user_id:
                    got_user_id = self._extract_user_id(completion_data)
                    if got_user_id and got_user_id != expected_user_id:
                        raise AssertionError(
                            f"login user mismatch; expected={expected_user_id}, got={got_user_id}"
                        )

                if not cookies.get("web_session"):
                    raise AssertionError(
                        "扫码已确认，但未获取到 web_session，请重试登录。"
                    )

                self.credentials = completion_data
                self.set_cookies(cookies)
                return True

        raise AssertionError(f"二维码登录超时（{timeout_s}s）")

    def login_with_credentials_file(self, credentials_file: str):
        with open(credentials_file, "r", encoding="utf-8") as f:
            credentials = json.load(f)
        self.credentials = credentials
        self.set_cookies(credentials)
        return True

    def login_with_credentials_info(self, credentials_info: dict):
        self.credentials = credentials_info
        self.set_cookies(credentials_info)
        return True

    def check_login(self):
        """
        优先使用接口判断，失败时回退到 cookie 形态判断。
        """
        if not self.cookies:
            return False
        has_login_cookies = bool(
            self.cookies.get("web_session")
            and self.cookies.get("web_session_sec")
            and self.cookies.get("a1")
        )
        # 优先用签名接口判断登录态（更稳定）
        try:
            xh, sm = self.get_xhshow_pair()
            data = self.signed_get(
                "/api/sns/web/v1/user/selfinfo",
                self.cookies,
                {},
                xh,
                sm,
            )
            if (data.get("result") or {}).get("success") is True:
                return True
            # 有些账号该接口字段不稳定，但只要 cookie 形态完整就判为已登录
            if has_login_cookies:
                return True
        except Exception as e:
            logger.debug("check_login by selfinfo failed; fallback, err=%s", e, exc_info=True)
            if has_login_cookies:
                return True

        # 回退：解析 explore 页的初始状态
        response = self.session.get(
            f"{self.www_host}/explore",
            headers={
                **self.headers,
                "Origin": self.www_host,
                "Referer": f"{self.www_host}/",
            },
        )
        if response.status_code != 200:
            logger.error(
                f"Check failed, please check the info; status_code: {response.status_code}, text: {response.text}"
            )
            return False
        state = self.parse_initial_state(response.text)
        user = ((state or {}).get("global") or {}).get("user") or {}
        if not user:
            return False
        if user.get("userInfo"):
            return True
        if user.get("loggedIn"):
            return True
        if user.get("user_id") or user.get("userId"):
            return True
        # 最终回退：登录 cookie 存在即视作登录成功（适用于接口权限受限账号）
        return has_login_cookies


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--credentials_file",
        default=(project_path / "dotenv/xiaohongshu_login_credentials.json").as_posix(),
        type=str,
    )
    args = parser.parse_args()
    return args


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    args = get_args()
    client = XiaoHongShuClient()

    flag = client.check_login()
    print(f"flag: {flag}")

    # client.login_with_qrcode_url()
    # credentials_path = Path(args.credentials_file)
    # credentials_path.parent.mkdir(parents=True, exist_ok=True)
    # with open(credentials_path, "w", encoding="utf-8") as f:
    #     json.dump(client.cookies or {}, f, ensure_ascii=False, indent=2)
    # print(f"credentials saved to: {credentials_path.as_posix()}")

    client.login_with_credentials_file(args.credentials_file)
    flag = client.check_login()
    print(f"flag: {flag}")
    return


if __name__ == "__main__":
    main()
