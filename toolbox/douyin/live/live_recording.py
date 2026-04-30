#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import asyncio
import httpx
import json
import logging
import random
import re
import string
from typing import List

from bs4 import BeautifulSoup
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from project_settings import project_path
from toolbox.douyin.homepage.follow import FollowManager
from toolbox.asyncio.cacheout import async_cache_decorator

logger = logging.getLogger("toolbox")


class LiveRecording(FollowManager):
    def __init__(self):
        super().__init__()

    @async_cache_decorator(10)
    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    async def get_live_info_by_web_enter(self, room_id: str):
        if not self.async_session.cookies:
            await self.async_session.request(
                method="GET",
                url="https://live.douyin.com/"
            )
        response = await self.async_session.request(
            method="GET",
            url="https://live.douyin.com/webcast/room/web/enter/",
            params={
                "aid": "6383",
                "device_platform": "web",
                "browser_language": "zh-CN",
                "browser_platform": "Win32",
                "browser_name": "Chrome",
                "browser_version": "100.0.0.0",
                "web_rid": room_id
            },
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code {response.status_code}, text: {response.text}")
        if len(response.text) == 0:
            self.async_session.cookies = httpx.Cookies()
            return None

        js = response.json()
        return js

    @async_cache_decorator(10)
    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    async def get_live_info_by_room_url(self, room_id: str):
        if not self.async_session.cookies:
            await self.async_session.request(
                method="GET",
                url="https://live.douyin.com/"
            )
        room_url = f"https://live.douyin.com/{room_id}"

        __ac_nonce = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        headers= {
            "Cookie": f"__ac_nonce={__ac_nonce}; ",
            **self.headers,
        }

        response = await self.async_session.request(
            method="GET",
            url=room_url,
            headers=headers,
        )
        if response.status_code == 444:
            return None
        elif response.status_code != 200:
            raise AssertionError(f"request failed; status_code {response.status_code}, text: {response.text}")
        else:
            pass
        html_text = response.text
        soup = BeautifulSoup(html_text, "html.parser")

        result = None
        for script in soup.find_all("script"):
            content = str(script)
            match = re.search(
                pattern=r"<script nonce=\"(?:.*?)\">self.__pace_f.push\(\[1,(.*?)\]\)</script>",
                string=content,
                flags=re.IGNORECASE
            )
            if match is not None:
                text = match.group(1)

                try:
                    text = json.loads(text)
                except json.JSONDecodeError:
                    continue

                if text[1:3] != ":[":
                    continue
                text = text[2:]

                try:
                    text = json.loads(text)
                except json.JSONDecodeError:
                    continue

                if not isinstance(text, list):
                    continue
                js = text
                if len(js) != 4:
                    continue
                js = js[3]
                if not isinstance(js, dict):
                    continue
                js = js.get("state")
                if js is None:
                    continue

                try:
                    room_info = js["roomStore"]["roomInfo"]
                    # 2 表示正在直播
                    room = room_info["room"]
                    alive_status = room["status"]
                    title = room["title"]
                    web_rid = room_info["web_rid"]
                    anchor = room_info["anchor"]
                    sec_uid = anchor["sec_uid"]
                    nickname = anchor["nickname"]
                    web_stream_url = room_info["web_stream_url"]

                    stream_store = js["streamStore"]
                    stream_data = stream_store["streamData"]
                    h265_stream_data = stream_data["H265_streamData"]["stream"]
                    h264_stream_data = stream_data["H264_streamData"]["stream"]

                    camera_store = js["cameraStore"]

                    paid_live_store = js["paidLiveStore"]
                    paid_live_data = paid_live_store.get("paidLiveData")

                    vip_store = js["vipStore"]
                    is_show_vip_panel = vip_store["isShowVipPanel"]
                    is_vip = vip_store["isVip"]

                except KeyError:
                    continue
                result = {
                    "status": alive_status,
                    "title": title,
                    "web_rid": web_rid,
                    "sec_uid": sec_uid,
                    "nickname": nickname,
                    # "web_stream_url": web_stream_url,
                    # "h265_stream_data": h265_stream_data,
                    # "h264_stream_data": h264_stream_data,
                    "stream_data": h264_stream_data,
                    # "camera_store": camera_store,

                    "paid_live_data": paid_live_data,

                    "is_show_vip_panel": is_show_vip_panel,
                    "is_vip": is_vip,
                }
                break
        return result

    async def get_live_info_by_sec_user_id(self, sec_user_id: str):
        js = await self.get_user_info_by_sec_user_id(sec_user_id)
        status_code = js["status_code"]
        if status_code != 0:
            raise AssertionError(f"request failed; status_code {status_code}, msg: {js['status_msg']}")

        user_info = js["user"]
        uid = user_info["uid"]

        result = await self.get_live_info_by_user_id(user_id=str(uid))
        return result

    @async_cache_decorator(10)
    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    async def get_live_info_by_user_id(self, user_id: str):
        js = await self.check_user_live_status_by_user_id(user_id=str(user_id))
        user_live = js["data"][0]["user_live"]
        if len(user_live) == 0:
            result = {
                "status": 4,  # 未开播
                "title": "",
                "stream_data": dict(),
                "paid_live_data": dict(),
            }
            return result

        data = user_live[0]
        room_id = data["room_id"]

        js = await self.get_room_info_by_scene_by_room_id(room_id)
        data = js["data"]
        status = data["status"]
        title = data["title"]
        stream_data = json.loads(data["stream_url"]["live_core_sdk_data"]["pull_data"]["stream_data"])
        stream_data = stream_data["data"]

        paid_live_data = data["paid_live_data"]

        result = {
            "status": status,
            "title": title,
            "stream_data": stream_data,

            "paid_live_data": paid_live_data,
        }
        return result

    @async_cache_decorator(600)
    @retry(
        wait=wait_fixed(60),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    async def get_live_info_by_follow(self, room_id: str):
        result = None
        live_info_list: List[dict] = await self.get_living_list()

        if live_info_list is None:
            return None
        for live_info in live_info_list:
            room_id_ = live_info["room_id"]
            if room_id_ == room_id:
                result = live_info
                break
        return result


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

    client = LiveRecording()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    flag = client.check_login()
    print(f"flag: {flag}")

    js = await client.get_live_info_by_web_enter(room_id="252921006343")
    # js = await client.get_live_info_by_room_url(room_id="252921006343")
    # js = await client.get_live_info_by_follow(room_id="876191604909")
    # js = await client.get_live_info_by_follow(room_id="572033528289")

    # js = await client.get_live_info_by_sec_user_id(
    #     # sec_user_id="MS4wLjABAAAA_vx5smDIz-u2d5o0vL3UPNVuznz_8Z9ZwGa0ULzj4rZfU5CsNoBhR_ltGF7pz7yi",
    #     # sec_user_id="MS4wLjABAAAAgd9H8yTMv9zn8AlgK5YXtqMi7PZMU2plnW7N1ZFA12_jsAuZL_NrBOUCwCYixRLx",
    #     sec_user_id="MS4wLjABAAAAf0qOK8d42d4y5nAFzm-MOI31El_mtLMIR6M-TmewcZDtJOM54w9gx9cmIDDpByFJ",
    # )
    # js = await client.get_live_info_by_user_id(user_id="1450989587539357")
    print(f"js: {json.dumps(js, ensure_ascii=False, indent=4)}")
    return


if __name__ == "__main__":
    asyncio.run(main())
