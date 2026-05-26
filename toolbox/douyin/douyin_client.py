#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
https://blog.csdn.net/qq_18303993/article/details/114281349
"""
import argparse
import json
import logging
import time
import httpx

import qrcode
import requests
import requests.utils

from project_settings import project_path
from toolbox.design_patterns.singleton import ParamsSingleton


logger = logging.getLogger("toolbox")


class DouyinClient(ParamsSingleton):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    def __init__(self):
        if not self._initialized:
            self.credentials = None
            self.cookies = None

            self._session = requests.Session()
            self._session.trust_env = False
            self._async_session = httpx.AsyncClient(
                http2=True,
                limits=httpx.Limits(max_keepalive_connections=100, keepalive_expiry=100),
                headers=self.headers,
                cookies=self.cookies,
            )
            self._initialized = True

    @property
    def session(self):
        if not self._session.cookies:
            self._session.headers = self.headers
            self._session.cookies = requests.utils.cookiejar_from_dict(self.cookies)
        return self._session

    @staticmethod
    def get_new_session():
        return requests.Session()

    @property
    def async_session(self):
        if not self._async_session.cookies:
            self._async_session.headers = self.headers
            self._async_session.cookies = httpx.Cookies(self.cookies)
        return self._async_session

    def get_new_async_session(self):
        session = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=100, keepalive_expiry=100),
            headers=self.headers,
            cookies=self.cookies,
        )
        return session

    @classmethod
    def get_qrcode(cls):
        url = "https://login.douyin.com/passport/web/get_qrcode/"
        params = {
            "aid": "6383",
            "next": "https://www.douyin.com",
        }
        response = requests.get(url, params=params, headers=cls.headers)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    @classmethod
    def check_qr_connect(cls, token: str):
        url = "https://login.douyin.com/passport/web/check_qrconnect"

        params = {
            "aid": "6383",
            "next": "https://www.douyin.com",
        }
        data = {
            "need_logo": False,
            "need_short_url": False,
            "is_frontier": True,
            "token": token,
            "is_new_login": 1,
            "next": "https://www.douyin.com",
        }
        response = requests.post(
            url,
            headers=cls.headers,
            params=params,
            data=data,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        print(response.cookies)
        return js

    @classmethod
    def get_cookies(cls, url: str):
        response = requests.get(url, headers=cls.headers)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def check_login(self):
        url = "https://creator.douyin.com/web/api/media/user/info"
        response = self.session.get(url)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        # print(f"js: {json.dumps(js, ensure_ascii=False)}")

        status_code = js["status_code"]
        if status_code == 8:
            # js: {"extra": {"logid": "20250908143856B85220348FE83A18AA76", "now": 1757313536000}, "status_code": 8, "status_msg": "用户未登录"}
            return False
        elif status_code == 0:
            return True
        else:
            raise AssertionError(f"js: {json.dumps(js, ensure_ascii=False)}")

    def login_with_qrcode(self):
        js = self.get_qrcode()
        # print(f"js: {json.dumps(js, ensure_ascii=False, indent=4)}")

        qrcode_index_url = js["data"]["qrcode_index_url"]
        token = js["data"]["token"]
        # qr = qrcode.QRCode()
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(qrcode_index_url)
        qr.make(fit=True)
        qr.print_ascii()
        print("Or copy this link to your phone Douyin:", qrcode_index_url)

        cookies = None
        while True:
            time.sleep(3)
            js = self.check_qr_connect(token=token)
            message = js["message"]
            if message == "error":
                error_code = js["data"]["error_code"]
                description = js["data"]["description"]
                raise AssertionError(f"check qr connect error; error_code: {error_code}, description: {description}")
            status = js["data"]["status"]
            if status == "new":
                pass
            elif status == "expired":
                qrcode_index_url = js["data"]["qrcode_index_url"]
                token = js["data"]["token"]
                qr = qrcode.QRCode()
                qr.add_data(qrcode_index_url)
                qr.print_ascii()
                print("Or copy this link to your phone Douyin:", qrcode_index_url)
            elif status == "scanned":
                print('已扫码，请确认登录！')
                pass

        # js = self.check_login()
        # print(f"js: {json.dumps(js, ensure_ascii=False)}")
        return js

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

    def set_cookies(self, cookies: dict):
        self.cookies = cookies


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--credentials_file",
        default=(project_path / "dotenv/douyin_login_credentials.json").as_posix(),
        type=str
    )
    args = parser.parse_args()
    return args


def main():
    import log
    from project_settings import project_path, log_directory

    log.setup_size_rotating(log_directory=log_directory)

    args = get_args()

    client = DouyinClient()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    flag = client.check_login()
    print(f"flag: {flag}")

    # js = client.login_with_qrcode()
    # js = client.check_login()
    # print(js)
    return


if __name__ == "__main__":
    main()
