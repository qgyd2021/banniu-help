#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
参考 toolbox/xiaohongshu/xiaohongshu_client.py 的微博基础客户端。

职责：
1. 维护 requests Session 与 cookies
2. 支持凭据文件登录
3. 支持生成微博访客身份（SUB/SUBP）
4. 提供基础登录态检查
"""
import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import requests.utils

from project_settings import project_path
from toolbox.design_patterns.singleton import ParamsSingleton

logger = logging.getLogger("toolbox")


class WeiboClient(ParamsSingleton):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    }

    def __init__(self):
        if not self._initialized:
            self.credentials = None
            self.cookies = None
            self._session = requests.Session()
            self._session.trust_env = False
            self._initialized = True

    @property
    def session(self):
        # 每次都同步，避免 cookie 变更后仍沿用旧会话
        self._session.headers = self.headers
        self._session.cookies = requests.utils.cookiejar_from_dict(self.cookies or {})
        return self._session

    @staticmethod
    def _extract_json_from_callback(text: str) -> Dict[str, Any]:
        m = re.search(r"\((\{.*\})\)\s*;?\s*$", text, flags=re.DOTALL)
        if not m:
            raise AssertionError(f"callback json parse failed; text: {text[:300]}")
        return json.loads(m.group(1))

    def set_cookies(self, cookies: dict):
        self.cookies = cookies
        return self.cookies

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

    def save_credentials_file(self, credentials_file: str) -> str:
        path = Path(credentials_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.cookies or {}, f, ensure_ascii=False, indent=2)
        return path.as_posix()

    def login_as_visitor(self, return_url: str = "https://m.weibo.cn/") -> bool:
        """
        生成微博访客 cookie（SUB/SUBP），可用于公开内容访问。
        """
        request_id = str(int(time.time() * 1000))
        gen_resp = self._session.post(
            "https://visitor.passport.weibo.cn/visitor/genvisitor2",
            data={
                "cb": "visitor_gray_callback",
                "ver": "20250916",
                "request_id": request_id,
                "tid": "",
                "from": "weibo",
                "webdriver": "false",
                "rid": "",
                "return_url": return_url,
            },
            headers={
                **self.headers,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )
        if gen_resp.status_code != 200:
            raise AssertionError(f"genvisitor2 failed; status_code: {gen_resp.status_code}")

        gen_js = self._extract_json_from_callback(gen_resp.text)
        if gen_js.get("retcode") != 20000000:
            raise AssertionError(f"genvisitor2 failed: {json.dumps(gen_js, ensure_ascii=False)}")
        tid = (gen_js.get("data") or {}).get("tid")
        if not tid:
            raise AssertionError(f"genvisitor2 no tid: {json.dumps(gen_js, ensure_ascii=False)}")

        inc_resp = self._session.get(
            "https://visitor.passport.weibo.cn/visitor/visitor",
            params={
                "a": "incarnate",
                "t": tid,
                "w": "2",
                "c": "095",
                "cb": "cross_domain",
                "from": "weibo",
                "_rand": str(time.time()),
            },
            headers=self.headers,
            timeout=30,
        )
        if inc_resp.status_code != 200:
            raise AssertionError(f"visitor incarnate failed; status_code: {inc_resp.status_code}")
        inc_js = self._extract_json_from_callback(inc_resp.text)
        if inc_js.get("retcode") != 20000000:
            raise AssertionError(f"visitor incarnate failed: {json.dumps(inc_js, ensure_ascii=False)}")

        # 从 session cookiejar 同步到 dict
        cookies_dict = requests.utils.dict_from_cookiejar(self._session.cookies)
        self.set_cookies(cookies_dict)
        self.credentials = cookies_dict
        return True

    def check_login(self) -> bool:
        """
        微博公开抓取场景下，主要判断是否已具备可用访客身份 cookie。
        """
        if not self.cookies:
            return False
        if self.cookies.get("SUB") and self.cookies.get("SUBP"):
            return True

        # 回退：尝试访问 m.weibo 首页
        try:
            resp = self._session.get(
                "https://m.weibo.cn/",
                headers=self.headers,
                allow_redirects=True,
                timeout=30,
            )
            return resp.status_code == 200
        except Exception:
            return False


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--credentials_file",
        default=(project_path / "dotenv/weibo_login_credentials.json").as_posix(),
        type=str,
    )
    args = parser.parse_args()
    return args


def main():
    args = get_args()
    client = WeiboClient()

    try:
        client.login_with_credentials_file(args.credentials_file)
    except OSError:
        logger.info("credentials file not found: %s", args.credentials_file)
        client.login_as_visitor()
        save_path = client.save_credentials_file(args.credentials_file)
        print(f"visitor credentials saved to: {save_path}")

    print(f"check_login: {client.check_login()}")
    return


if __name__ == "__main__":
    main()
