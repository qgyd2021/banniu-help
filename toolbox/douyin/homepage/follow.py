#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import asyncio
import json
import logging

import httpx
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from project_settings import project_path
from toolbox.douyin.douyin_client import DouyinClient
from toolbox.asyncio.cacheout import async_cache_decorator

logger = logging.getLogger("toolbox")


class FollowManager(DouyinClient):
    def __init__(self):
        super().__init__()

    @async_cache_decorator(600)
    async def get_living_list(self):
        url = "https://www.douyin.com/webcast/web/feed/follow/"

        params = {
            "device_platform": "webapp",
            "aid": 6383,
            "channel": "channel_pc_web",
            "scene": "aweme_pc_follow_top",
            "update_version_code": 170400,
            "pc_client_type": 1,
            "pc_libra_divert": "Mac",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",

        }

        response = await self.async_session.request("GET", url, params=params)
        if response.status_code != 200:
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")

        js = response.json()

        status_code = js["status_code"]
        if status_code == 20003:
            # 请登录后进入直播间
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")

        data = js["data"]["data"]

        result = list()
        for row in data:
            # print(json.dumps(row, ensure_ascii=False, indent=4))
            room = row["room"]
            title = room["title"]
            stream_url = room["stream_url"]
            paid_live_data = room["paid_live_data"]
            owner = room["owner"]
            sec_uid = owner["sec_uid"]
            nickname = owner["nickname"]
            room_id = row["web_rid"]

            try:
                live_core_sdk_data = stream_url["live_core_sdk_data"]
            except KeyError as error:
                print(stream_url)
                raise error
            pull_data = live_core_sdk_data["pull_data"]
            stream_data = pull_data["stream_data"]

            stream_data = json.loads(stream_data)
            stream_data = stream_data["data"]

            row_ = {
                "nickname": nickname,
                "sec_uid": sec_uid,
                "room_id": room_id,

                "status": 2,
                "title": title,
                "stream_data": stream_data,

                "paid_live_data": paid_live_data,

            }
            result.append(row_)

        return result

    async def check_user_live_status_by_user_id(self, user_id: str):
        url = "https://live.douyin.com/webcast/distribution/check_user_live_status/"

        params = {
            # "user_ids": "1450989587539357",
            "user_ids": user_id,
            "aid": "6383",
        }

        async_session = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=100, keepalive_expiry=100),
            headers=self.headers,
        )
        response = await async_session.request("GET", url, params=params)
        if response.status_code != 200:
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")

        js = response.json()
        return js

    async def get_room_info_by_scene_by_room_id(self, room_id: str):
        url = "https://live.douyin.com/webcast/room/info_by_scene/"

        params = {
            "aid": "6383",
            "app_name": "douyin_web",
            "live_id": "1",
            "device_platform": "web",
            "language": "zh-CN",
            "enter_from": "web_homepage_hot",
            "cookie_enabled": "true",
            "browser_name": "Chrome",
            "browser_version": "141.0.0.0",
            "room_id": room_id,
            # "room_id": "7560205524554320680",
            "scene": "pc_profile_struct",

        }

        async_session = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=100, keepalive_expiry=100),
            headers=self.headers,
        )
        response = await async_session.request("GET", url, params=params)
        if response.status_code != 200:
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")

        js = response.json()
        return js

    @async_cache_decorator(600)
    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    async def get_user_info_by_sec_user_id(self, sec_user_id: str):
        url = "https://www.douyin.com/aweme/v1/web/user/profile/other/"

        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "sec_user_id": sec_user_id,
        }

        # 需要登录cookies
        response = await self.async_session.request(
            "GET", url,
            headers={
                **self.headers,
                "referer": "https://www.douyin.com/user"
            },
            params=params,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")

        js = response.json()
        return js


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--credentials_file",
        default=(project_path / "dotenv/douyin_wentao_credentials.json").as_posix(),
        type=str
    )
    args = parser.parse_args()
    return args


async def main():
    import log
    from project_settings import project_path, log_directory

    log.setup_size_rotating(log_directory=log_directory)

    args = get_args()

    client = FollowManager()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    flag = client.check_login()
    print(f"flag: {flag}")

    # js = await client.get_living_list()

    # js = await client.get_room_info_by_scene()

    js = await client.get_user_info_by_sec_user_id(
        sec_user_id="MS4wLjABAAAAf0qOK8d42d4y5nAFzm-MOI31El_mtLMIR6M-TmewcZDtJOM54w9gx9cmIDDpByFJ"
    )
    print(f"js: {json.dumps(js, ensure_ascii=False, indent=4)}")
    return


if __name__ == "__main__":
    asyncio.run(main())
