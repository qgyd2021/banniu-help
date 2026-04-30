#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
得物 Web 请求客户端（结构对齐其它平台 client）。
"""
import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import requests.utils

from project_settings import project_path
from toolbox.design_patterns.singleton import ParamsSingleton


class DewuUtils(object):
    api_host = "https://app.dewu.com"
    www_host = "https://m.dewu.com"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    @staticmethod
    def dict_to_cookie_str(cookies: Dict[str, str]) -> str:
        return "; ".join(f"{k}={v}" for k, v in (cookies or {}).items() if v is not None and str(v) != "")


class DewuClient(DewuUtils, ParamsSingleton):
    def __init__(self) -> None:
        if not self._initialized:
            self.credentials: Optional[Dict[str, Any]] = None
            self.cookies: Optional[Dict[str, str]] = None
            self._session = requests.Session()
            self._session.trust_env = False
            self._initialized = True

    @property
    def session(self) -> requests.Session:
        self._session.headers.update(self.headers)
        if self.cookies:
            self._session.cookies = requests.utils.cookiejar_from_dict(self.cookies)
        return self._session

    def set_cookies(self, cookies: Optional[Dict[str, str]]) -> Dict[str, str]:
        self.cookies = cookies or {}
        return self.cookies

    def check_login(self) -> bool:
        return bool(self.cookies)


def get_args():
    parser = argparse.ArgumentParser(description="得物客户端示例")
    parser.add_argument(
        "--credentials_file",
        default=(project_path / "dotenv/dewu_login_credentials.json").as_posix(),
        type=str,
    )
    return parser.parse_args()


def main() -> None:
    args = get_args()
    client = DewuClient()
    path = Path(args.credentials_file)
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            client.set_cookies(json.load(f))
    print("check_login:", client.check_login())
    r = client.session.get(client.www_host + "/", timeout=15)
    print("home status:", r.status_code)


if __name__ == "__main__":
    main()
