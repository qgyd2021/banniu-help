#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
https://pypi.org/project/biliupload/

https://github.com/SocialSisterYi/bilibili-API-collect

"""
import argparse
import hashlib
import json
import logging
import subprocess
import time
from urllib.parse import urlencode, urlparse

logger = logging.getLogger("toolbox")

import httpx
import qrcode
import requests
import requests.utils
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from project_settings import project_path
from toolbox.design_patterns.singleton import ParamsSingleton


class BilibiliUtils(object):
    app_key = "4409e2ce8ffd12b8"
    app_sec = "59b43e04ad6965f34319062b478f83dd"

    @classmethod
    def signature(cls, params):
        params["appkey"] = cls.app_key
        keys = sorted(params.keys())
        query = "&".join(f"{k}={params[k]}" for k in keys)
        query += cls.app_sec
        md5_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
        params["sign"] = md5_hash

    @staticmethod
    def map_to_string(params):
        return urlencode(params)

    @classmethod
    def execute_curl_command(cls, api, data):
        data_string = cls.map_to_string(data)
        headers = "Content-Type: application/x-www-form-urlencoded"
        curl_command = f"curl -X POST -H \"{headers}\" -d \"{data_string}\" {api}"
        result = subprocess.run(
            curl_command, shell=True, capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode != 0:
            raise Exception(f"curl command failed: {result.stderr}")
        return json.loads(result.stdout)


class BilibiliClient(BilibiliUtils, ParamsSingleton):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }

    def __init__(self):
        if not self._initialized:
            self.credentials = None
            self.cookies = None

            self._session = requests.Session()

            self._initialized = True

    @property
    def session(self):
        if not self._session.cookies:
            self._session.headers = self.headers
            self._session.cookies = requests.utils.cookiejar_from_dict(self.cookies)
        return self._session

    def get_new_async_session(self):
        session = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=100, keepalive_expiry=100),
            headers=self.headers,
            trust_env=False,
        )
        return session

    @classmethod
    def get_tv_qrcode_url_and_auth_code(cls):
        api = "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
        data = {
            "local_id": "0",
            "ts": str(int(time.time()))
        }
        cls.signature(data)
        body = cls.execute_curl_command(api, data)
        if body["code"] == 0:
            qrcode_url = body["data"]["url"]
            auth_code = body["data"]["auth_code"]
            return qrcode_url, auth_code
        else:
            raise Exception("get_tv_qrcode_url_and_auth_code error")

    @classmethod
    def verify_login(cls, auth_code):
        api = "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll"
        data = {
            "auth_code": auth_code,
            "local_id": "0",
            "ts": str(int(time.time()))
        }
        cls.signature(data)
        while True:
            body = cls.execute_curl_command(api, data)
            if body["code"] == 0:
                print("Login success!")
                return body
            else:
                time.sleep(3)

    def set_cookies(self, credentials: dict):
        access_token = credentials["data"]["access_token"]
        sessdata_value = credentials["data"]["cookie_info"]["cookies"][0]["value"]
        bili_jct_value = credentials["data"]["cookie_info"]["cookies"][1]["value"]
        dede_user_id_value = credentials["data"]["cookie_info"]["cookies"][2]["value"]
        dede_user_id_ckmd5_value = credentials["data"]["cookie_info"]["cookies"][3]["value"]
        sid_value = credentials["data"]["cookie_info"]["cookies"][4]["value"]
        cookies = {
            # "access_token": access_token,
            "SESSDATA": sessdata_value,
            "bili_jct": bili_jct_value,
            "DedeUserID": dede_user_id_value,
            "DedeUserID__ckMd5": dede_user_id_ckmd5_value,
            # "sid": sid_value,
        }
        self.cookies = cookies
        return self.cookies

    def login_with_qrcode_url(self):
        input("Please maximize the window to ensure the QR code is fully displayed, press Enter to continue: ")
        login_url, auth_code = self.get_tv_qrcode_url_and_auth_code()
        qr = qrcode.QRCode()
        qr.add_data(login_url)
        qr.print_ascii()
        print("Or copy this link to your phone Bilibili:", login_url)
        credentials = self.verify_login(auth_code)
        self.credentials = credentials
        self.set_cookies(credentials)
        return True

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
        url = "https://api.bilibili.com/x/web-interface/nav"
        with requests.Session() as session:
            session.headers = self.headers
            session.cookies = requests.utils.cookiejar_from_dict(self.cookies)
            response = session.get(url)
            if response.status_code == 200:
                response_data = json.loads(response.text)
                if response_data["data"]["isLogin"] is True:
                    return True
                else:
                    return False
            else:
                logger.error(f"Check failed, please check the info; status_code: {response.status_code}, text: {response.text}")
                return False

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def get_now(self):
        url = "https://api.bilibili.com/x/report/click/now"

        response = self.session.get(
            url,
            headers=self.headers,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def get_version(self):
        url = "https://api.live.bilibili.com/xlive/app-blink/v1/liveVersionInfo/getHomePageLiveVersion"

        js = self.get_now()
        ts = js["data"]["now"]

        params = {
            "system_version": 2,
            "ts": ts,
        }
        self.signature(params)

        response = self.session.get(
            url,
            headers=self.headers,
            params=params,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--credentials_file",
        default=(project_path / "dotenv/bilibili_chenjiesen_credentials.json").as_posix(),
        type=str
    )
    args = parser.parse_args()
    return args


def main():
    import log
    from project_settings import project_path, log_directory

    log.setup_size_rotating(log_directory=log_directory)

    args = get_args()

    client = BilibiliClient()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    print(json.dumps(client.credentials, ensure_ascii=False, indent=2))
    print(json.dumps(client.credentials, ensure_ascii=False))
    flag = client.check_login()
    print(f"flag: {flag}")

    # result = client.get_room_id()
    # result = client.get_now()
    # result = client.get_version()
    # print(result)
    return


if __name__ == "__main__":
    main()
