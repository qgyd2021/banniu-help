#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from project_settings import project_path, time_zone_info
from toolbox.douyin.douyin_client import DouyinClient
from exception import ExpectedError
from toolbox.asyncio.cacheout import async_cache_decorator

logger = logging.getLogger("toolbox")


class MediaDownload(DouyinClient):
    def __init__(self):
        super().__init__()

    @staticmethod
    def convert_aweme(aweme: dict):
        # aweme_type: 0: 普通视频; 2: 图片（单图）; 51: 视频（部分旧版本）; 55: 视频（新版本）; 68: 图文（图片集）;
        aweme_type = aweme["aweme_type"]
        media_type = aweme["media_type"]
        is_multi_content = aweme.get("is_multi_content")

        aweme_id = aweme["aweme_id"]
        desc = aweme["desc"]
        create_time = aweme["create_time"]
        create_time_ = datetime.fromtimestamp(
            create_time,
            tz=ZoneInfo(time_zone_info)
        )
        create_time_str = create_time_.strftime("%Y%m%dT%H%M%S")

        # video
        video = aweme["video"]
        url_list = video["play_addr"]["url_list"]
        width = video["play_addr"]["width"]
        height = video["play_addr"]["height"]
        video = {
            "url_list": url_list,
            "width": width,
            "height": height,
        }

        # images
        images = aweme["images"]
        if images is not None:
            images = [
                {
                    "url_list": image["url_list"],
                    "height": image["height"],
                    "width": image["width"],
                } for image in images
            ]
        else:
            images = list()

        # tags
        text_extra = aweme["text_extra"]
        tags = set()
        for t in text_extra:
            tag = t.get("hashtag_name")
            if tag is None:
                tag = t.get("search_text")
            if tag is None:
                # print(t)
                continue
            tags.add(tag)
        tags = list(tags)

        # title
        title: str = desc
        for tag in tags:
            title = title.replace(f"#{tag}", "")
            # title = title.replace(f"# {tag}", "")
        title = title.strip()

        duration = aweme["duration"]

        row = {
            "aweme_id": aweme_id,
            "create_time": create_time,
            "create_time_str": create_time_str,
            "title": title,
            "desc": desc,
            "tags": tags,
            "duration": duration,

            "video": video,
            "images": images,

            "aweme_type": aweme_type,
            "media_type": media_type,
            "is_multi_content": is_multi_content,
        }
        return row

    @async_cache_decorator(600)
    async def get_media_list_by_user_id(self, sec_user_id: str, max_cursor: int = 0, count: int = 18):
        url = "https://www.douyin.com/aweme/v1/web/aweme/post/"

        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "sec_user_id": sec_user_id,
            "max_cursor": max_cursor,
            "count": count,
            "publish_video_strategy_type": "2",
            "version_code": "290100",
            "version_name": "29.1.0",
        }

        response = await self.async_session.request(
            method="GET",
            url=url,
            headers={
                **self.headers,
                "referer": "https://www.douyin.com/",
            },
            params=params,
        )
        if response.status_code == 444:
            # Access Denied
            raise ExpectedError(status_code=60444, message=f"request failed, status_code: {response.status_code}, text: {response.text}")
        elif response.status_code == 200 and len(response.text) == 0:
            # Maybe Access Denied
            raise ExpectedError(status_code=60444, message=f"request failed, status_code: {response.status_code}, text: {response.text}")
        elif response.status_code != 200:
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")
        elif response.text == "blocked":
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        aweme_list = js["aweme_list"]
        max_cursor = js["max_cursor"]
        min_cursor = js["min_cursor"]
        has_more = js["has_more"]

        result = list()
        for aweme in aweme_list:
            # aweme_ = json.dumps(aweme, ensure_ascii=False, indent=4)
            # print(aweme_)
            # exit(0)

            row = self.convert_aweme(aweme)
            result.append(row)
        return result, max_cursor

    async def get_media_list_by_mix_id(self, mix_id: str, cursor: int = 0, count: int = 18):
        url = "https://www.douyin.com/aweme/v1/web/mix/aweme/"

        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "cursor": cursor,
            "count": count,
            "publish_video_strategy_type": "2",
            "version_code": "290100",
            "version_name": "29.1.0",

            "mix_id": mix_id,
        }

        response = await self.async_session.request(
            method="GET",
            url=url,
            headers={
                **self.headers,
                "referer": "https://www.douyin.com/",
            },
            params=params,
        )
        if response.status_code == 444:
            # Access Denied
            raise ExpectedError(status_code=60444, message=f"request failed, status_code: {response.status_code}, text: {response.text}")
        elif response.status_code == 200 and len(response.text) == 0:
            # Maybe Access Denied
            raise ExpectedError(status_code=60444, message=f"request failed, status_code: {response.status_code}, text: {response.text}")
        elif response.status_code != 200:
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")
        elif response.text == "blocked":
            raise AssertionError(f"request failed, status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        aweme_list = js["aweme_list"]
        if aweme_list is None:
            return list()

        result = list()
        for aweme in aweme_list:
            # aweme_ = json.dumps(aweme, ensure_ascii=False, indent=4)
            # print(aweme_)

            row = self.convert_aweme(aweme)
            result.append(row)
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

    client = MediaDownload()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    flag = client.check_login()
    print(f"flag: {flag}")

    js = await client.get_media_list_by_user_id(
        # sec_user_id="MS4wLjABAAAAb0mqEsXmBehDdg2Q9mMA2T6YEWPGbEtYofSzX_bDnz4",
        # sec_user_id="MS4wLjABAAAAQinRMLyQNYA45OYXoCDrwszhRGaDVirRE1fTNSaGGkc",
        sec_user_id="MS4wLjABAAAADyrPwJGfqa_NWIw0jrrk1NURMonGw2RlPnX0ORc3MSA",
    )
    print(f"js: {json.dumps(js, ensure_ascii=False, indent=4)}")
    return


async def main2():
    import random
    import re
    import log
    from project_settings import project_path, log_directory

    log.setup_size_rotating(log_directory=log_directory)

    args = get_args()

    output_video_dir = Path("output_video_dir")
    output_video_dir.mkdir(parents=True, exist_ok=True)
    read_me_file = output_video_dir / "README.txt"

    client = MediaDownload()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    flag = client.check_login()
    print(f"flag: {flag}")

    js = await client.get_media_list_by_mix_id(
        mix_id="7337883410737661989",
    )
    print(f"count: {len(js)}")

    with open(read_me_file.as_posix(), "w", encoding="utf-8") as f:
        for row in js:
            aweme_id = row["aweme_id"]
            create_time_str = row["create_time_str"]
            title = row["title"]
            desc = row["desc"]
            url_list = row["url_list"]
            tags = row["tags"]
            video_url = random.sample(url_list, k=1)[0]

            title_ = re.sub(r'[\\/:*?"<>|]', '_', title)
            title_ = title_[:50]
            filename = output_video_dir / f"{aweme_id}_{create_time_str}_{title_}.mp4"
            filename.parent.mkdir(parents=True, exist_ok=True)
            await client.download_video_by_url(filename, video_url)

            content = f"{title}\n{desc}\n{tags}"
            f.write(f"{content}\n\n\n")
            f.flush()
    return


if __name__ == "__main__":
    asyncio.run(main())
    # asyncio.run(main2())
