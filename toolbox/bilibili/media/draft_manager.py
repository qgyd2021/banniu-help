#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
https://pypi.org/project/biliupload/

https://github.com/SocialSisterYi/bilibili-API-collect

"""
import argparse
import logging

from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_fixed

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.bilibili.video.video_manager import BilibiliVideoUploader


class BilibiliVideoDraftUploader(BilibiliVideoUploader):
    def __init__(self):
        super().__init__()

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def list_draft(self):
        url = f"https://member.bilibili.com/x/vupre/web/draft/list"

        response = self.session.get(url)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def add_draft(self, biz_id: int, bilibili_filename, metadata: dict):
        csrf = self.cookies["bili_jct"]
        url = "https://member.bilibili.com/x/vupre/web/draft/add"

        params = {
            "csrf": csrf,
        }

        data = {
            "copyright": metadata["copyright"],
            "videos": [
                {
                    "filename": bilibili_filename,
                    "title": metadata["title"],
                    "desc": metadata["desc"],
                    "cid": biz_id,
                }
            ],

            "source": metadata["source"],
            "tid": metadata["tid"],
            "title": metadata["title"],
            "cover": metadata["cover"],
            "tag": metadata["tag"],
            "desc_format_id": 0,
            "desc": metadata["desc"],
            "dynamic": metadata["dynamic"],
            "subtitle": {"open": 0, "lan": ""},

        }

        response = self.session.post(
            url,
            params=params,
            json=data,
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
    def update_draft(self, draft_id: int, biz_id: int, bilibili_filename, metadata: dict):
        csrf = self.cookies["bili_jct"]
        url = "https://member.bilibili.com/x/vupre/web/draft/update"

        params = {
            "csrf": csrf,
        }

        data = {
            "id": draft_id,

            "copyright": metadata["copyright"],
            "videos": [
                {
                    "filename": bilibili_filename,
                    "title": metadata["title"],
                    "desc": metadata["desc"],
                    "cid": biz_id,
                }
            ],

            "source": metadata["source"],
            "tid": metadata["tid"],
            "title": metadata["title"],
            "cover": metadata["cover"],
            "tag": metadata["tag"],
            "desc_format_id": 0,
            "desc": metadata["desc"],
            "dynamic": metadata["dynamic"],
            "subtitle": {"open": 0, "lan": ""},

        }

        response = self.session.post(
            url,
            params=params,
            json=data,
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
    def publish_draft(self, draft_id: int, bilibili_filename: str, metadata: dict):
        csrf = self.cookies["bili_jct"]
        url = "https://member.bilibili.com/x/vu/web/add/v3"

        params = {
            "csrf": csrf,
        }

        data = {
            "draft_id": draft_id,
            "copyright": metadata["copyright"],
            "videos":[
                {
                    "filename": bilibili_filename,
                    "title": metadata["title"],
                    "desc": metadata["desc"],
                }
            ],
            "source": metadata["source"],
            "tid": metadata["tid"],
            "title": metadata["title"],
            "cover": metadata["cover"],
            "tag": metadata["tag"],
            "desc_format_id": 0,
            "desc": metadata["desc"],
            "dynamic": metadata["dynamic"],
            "subtitle": {"open": 0, "lan": ""},
        }

        if metadata["copyright"] != 2:
            del data["source"]
            # copyright: 1 original 2 reprint
            data["copyright"] = 1

        response = self.session.post(
            url,
            params=params,
            json=data,
            headers=self.headers,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def upload_video_draft_and_publish(self, filename: str, metadata: dict):
        biz_id, bilibili_filename = self.upload_video_file(filename)
        js = self.add_draft(biz_id, bilibili_filename, metadata)
        if js["code"] != 0:
            raise AssertionError(f"add draft; status_code: {js["code"]}, text: {js["message"]}")
        js = self.list_draft()
        if js["code"] != 0:
            raise AssertionError(f"add draft; status_code: {js["code"]}, text: {js["message"]}")
        draft_list = js["data"]

        draft_id = None
        for draft in draft_list:
            draft_id_ = draft["id"]
            draft_cid_ = draft["cid"]
            if draft_cid_ != biz_id:
                draft_id = draft_id_
                break

        if draft_id is None:
            raise AssertionError(f"add draft failed; biz_id not found, biz_id: {biz_id}")

        js = self.publish_draft(draft_id, bilibili_filename, metadata)

        bvid = None
        status_code = js["code"]
        if status_code == 137022:
            message = js["message"]
            logger.info(f"publish_video_draft failed; code: {status_code}, message: {message}")
        else:
            bvid = js["data"]["bvid"]
        return bvid


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--credentials_file",
        default=(project_path / "dotenv/bilibili_chenjiesen_credentials.json").as_posix(),
        type=str
    )
    parser.add_argument(
        "--filename",
        default=(project_path / "data/video/douyin/陈杰森/[7546905431348612362][20250906_172733]资本市场重大事件 。某行市值第一的隐秘故事。#易会满.mp4").as_posix(),
        type=str
    )
    args = parser.parse_args()
    return args


def main():
    import log
    from project_settings import project_path, log_directory

    log.setup_size_rotating(log_directory=log_directory)

    args = get_args()

    client = BilibiliVideoDraftUploader()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    flag = client.check_login()
    print(f"flag: {flag}")

    js = client.list_draft()
    print(f"js: {js}")

    tags = [
      "阅兵",
      "商机",
      "干货分享",
      "金融",
      "商业"
    ]
    metadata = {
        "title": "九三阅兵的意义有多重大。 为什么说这次阅兵是“雷军式BOSS直销”？来的是客户，更是未来的“合伙人”！",
        "desc": "九三阅兵的意义有多重大。 为什么说这次阅兵是“雷军式BOSS直销”？来的是客户，更是未来的“合伙人”！#阅兵 #金融 #商业 #商机 #干货分享",
        "tag": ",".join(tags),

        "copyright": 1,
        "source": None,
        "tid": 138,
        "cover": "https://archive.biliimg.com/bfs/archive/124bf16affdfc2260f9fa7e1794bf946f1ad4997.jpg",
        "dynamic": "",
    }
    js = client.upload_video_draft_and_publish(
        filename=args.filename,
        metadata=metadata
    )
    print(f"js: {js}")
    return


if __name__ == "__main__":
    main()
