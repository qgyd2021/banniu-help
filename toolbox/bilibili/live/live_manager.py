#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
https://github.com/lateautumn233/Bilibili-Live-Stream/blob/main/bilibili-live.py

https://github.com/ChaceQC/bilibili_live_stream_code/blob/master/main/bilibili_live_stream_code.py

"""
import argparse
import json
import logging

from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_fixed

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.bilibili.bilibili_client import BilibiliClient


class RtmpPublishCMD(object):
    def __init__(self, cmd_list: list, cmd_str: str):
        self.cmd_list = cmd_list
        self.cmd_str = cmd_str


class BilibiliLiveManager(BilibiliClient):
    def __init__(self):
        super().__init__()

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def set_live_title(self, title: str):
        """
        :return
        {
            "code": 0,
            "msg": "ok",
            "message": "ok",
            "data": {
                "sub_session_key": "",
                "audit_info": {
                    "audit_title_reason": "进入审核",
                    "update_title": "",
                    "audit_title_status": 0,
                    "audit_title": "设置直播标题"
                }
            }
        }
        """
        url = "https://api.live.bilibili.com/room/v1/Room/update"

        js = self.get_room_id_by_uid()
        room_id = js["data"]["room_id"]

        bili_jct = self.cookies["bili_jct"]

        data = {
            "room_id": room_id,
            "platform": "pc_link",
            "title": title,
            "csrf_token": bili_jct,
            "csrf": bili_jct,
        }
        response = self.session.post(
            url,
            headers=self.headers,
            data=data,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        # print(json.dumps(js, ensure_ascii=False, indent=4))
        return js

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def get_room_id_by_uid(self):
        dede_user_id = self.cookies.get("DedeUserID")

        url = f"https://api.live.bilibili.com/room/v2/Room/room_id_by_uid?uid={dede_user_id}"
        response = self.session.get(
            url,
            headers=self.headers
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def get_rtmp_publish_cmd_by_flv_file(self, input_source: str, do_copy: bool = True):
        js = self.get_rtmp_info_by_room_id()
        # print(json.dumps(js, ensure_ascii=False, indent=4))
        rtmp_code = js["data"]["rtmp"]["code"]
        rtmp_addr = js["data"]["rtmp"]["addr"]

        rtmp_url = f"{rtmp_addr}{rtmp_code}"

        if do_copy:
            cmd_list = [
                "ffmpeg",
                "-rw_timeout", "5000000",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-reconnect_on_network_error", "1",

                "-i", input_source,
                "-c", "copy",
                "-f", "flv",
                "-flvflags", "no_duration_filesize",
                rtmp_url
            ]
            cmd_str = [
                "ffmpeg",
                "-rw_timeout", "5000000",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-reconnect_on_network_error", "1",

                '-i', f'"{input_source}"',
                "-c", "copy",
                "-f", "flv",
                "-flvflags", "no_duration_filesize",
                f'"{rtmp_url}"'
            ]
        else:
            cmd_list = [
                "ffmpeg",
                "-re",
                "-i", input_source,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-b:v", "1500k",
                "-c:a", "aac",
                "-b:a", "128k",
                "-f", "flv",
                rtmp_url
            ]
            cmd_str = [
                "ffmpeg",
                "-re",
                '-i', f'"{input_source}"',
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-b:v", "1500k",
                "-c:a", "aac",
                "-b:a", "128k",
                "-f", "flv",
                f'"{rtmp_url}"'
            ]

        cmd_str = " ".join(cmd_str)
        cmd = RtmpPublishCMD(
            cmd_list=cmd_list,
            cmd_str=cmd_str
        )
        return cmd

    def get_rtmp_info_by_room_id(self):
        """
        :return:
        {
            "code": 0,
            "data": {
                "change": 1,
                "status": "LIVE",
                "try_time": "0000-00-00 00:00:00",
                "room_type": 0,
                "live_key": "630309426298156613",
                "sub_session_key": "630309426298156613sub_time:1757133948",
                "rtmp": {
                    "type": 1,
                    "addr": "rtmp://txy2.live-push.bilivideo.com/live-bvc/",
                    "code": "?streamname=live_442286660_79175069&key=fd263bd4cad752a05c2e284adda16302&schedule=rtmp&pflag=2",
                    "new_link": "",
                    "provider": "txy2"
                },
                "protocols": [
                    {
                        "protocol": "rtmp",
                        "addr": "rtmp://txy2.live-push.bilivideo.com/live-bvc/",
                        "code": "?streamname=live_442286660_79175069&key=fd263bd4cad752a05c2e284adda16302&schedule=rtmp&pflag=2",
                        "new_link": "",
                        "provider": "txy"
                    }
                ],
                "notice": {
                    "type": 1,
                    "status": 0,
                    "title": "",
                    "msg": "",
                    "button_text": "",
                    "button_url": ""
                },
                "qr": "",
                "need_face_auth": false,
                "service_source": "live-streaming",
                "rtmp_backup": null,
                "up_stream_extra": {
                    "isp": "小运营商"
                },
                "collaboration_live_extra": null
            },
            "message": "",
            "msg": ""
        }
        """
        url = "https://api.live.bilibili.com/room/v1/Room/startLive"

        js = self.get_room_id_by_uid()
        room_id = js["data"]["room_id"]

        js = self.get_version()
        build = js["data"]["build"]
        curr_version = js["data"]["curr_version"]

        js = self.get_now()
        ts = js["data"]["now"]

        bili_jct = self.cookies["bili_jct"]
        data = {
            "room_id": room_id,
            "platform": "pc_link",
            "area_v2": "624",
            "backup_stream": "0",
            "csrf_token": bili_jct,
            "csrf": bili_jct,
            "build": build,
            "version": curr_version,
            "ts": ts,
        }
        self.signature(data)

        response = self.session.post(
            url,
            headers=self.headers,
            data=data,
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
    def stop_live(self):
        url = "https://api.live.bilibili.com/room/v1/Room/stopLive"

        js = self.get_room_id_by_uid()
        room_id = js["data"]["room_id"]

        bili_jct = self.cookies["bili_jct"]

        data = {
            "room_id": room_id,
            "platform": "pc_link",
            "csrf_token": bili_jct,
            "csrf": bili_jct,
        }
        response = self.session.post(
            url,
            headers=self.headers,
            data=data,
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
    def get_live_status(self):
        js = self.get_room_id_by_uid()
        room_id = js["data"]["room_id"]

        url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"

        response = self.session.get(
            url,
            headers=self.headers,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def is_living(self):
        js = self.get_live_status()
        live_status = js["data"]["live_status"]
        flag = live_status == 1
        return flag


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

    client = BilibiliLiveManager()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    flag = client.check_login()
    print(f"flag: {flag}")

    # result = client.get_room_id()
    # result = client.stop_live()
    # result = client.start_live_by_flv_file(args.room_id)
    # result = client.set_live_title("设置直播标题")
    result = client.is_living()
    print(result)
    return


if __name__ == "__main__":
    main()
