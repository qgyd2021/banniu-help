#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import requests
from zoneinfo import ZoneInfo

from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from project_settings import project_path, time_zone_info
from toolbox.exception import ExpectedError
from toolbox.asyncio.cacheout import async_cache_decorator
from toolbox.douyin.media.media_download import MediaDownload

logger = logging.getLogger("toolbox")


class VideoDownload(MediaDownload):
    def __init__(self):
        super().__init__()

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    async def download_video_by_url(self, filename: Path, url: str):
        filename = Path(filename)
        filename.parent.mkdir(parents=True, exist_ok=True)

        response = await self.async_session.request(
            method="GET",
            url=url,
            headers={
                **self.headers,
                "referer": "https://www.douyin.com/",
            },
        )
        # 302 重定向
        if response.status_code == 302:
            url = response.headers["Location"]
            return await self.download_video_by_url(filename, url)
        elif response.status_code == 200:
            with open(filename, "wb") as f:
                f.write(response.content)
            return filename
        else:
            raise AssertionError(f"Got status code {response.status_code}")

    async def get_video_list_by_min_date(self, sec_user_id: str, min_date: str = "2025-06-10 00:00:00"):
        #UTC时间
        min_date_ = datetime.strptime(min_date, "%Y-%m-%d %H:%M:%S")

        result = list()

        max_cursor = 0
        for i in range(1000):
            rows, max_cursor = await self.get_media_list_by_user_id(sec_user_id=sec_user_id, max_cursor=max_cursor, count=18)
            if len(rows) == 0:
                break
            this_min_date_ = [
                datetime.fromtimestamp(
                    row["create_time"],
                ) < min_date_
                for row in rows
            ]
            if all(this_min_date_):
                break
            for row in rows:
                aweme_type = row["aweme_type"]
                media_type = row["media_type"]
                is_multi_content = row["is_multi_content"]

                # 视频
                if aweme_type not in (0,) and media_type not in (4,):
                    continue

                # 图文（多图）
                # if aweme_type in (68,) and media_type in (2,):
                #     continue

                create_time = row["create_time"]
                aweme_id = row["aweme_id"]
                create_time_str = row["create_time_str"]
                title = row["title"]
                desc = row["desc"]
                tags = row["tags"]
                duration = row["duration"]

                video = row["video"]
                images = row["images"]

                create_time_ = datetime.fromtimestamp(create_time)

                if create_time_ > min_date_:
                    task = {
                        "aweme_id": aweme_id,
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
                    result.append(task)
        return result

    async def get_all_video_by_mix_id(self, mix_id: str):
        result = list()

        cursor = 0
        count = 18
        for i in range(1000):
            rows = await self.get_media_list_by_mix_id(mix_id=mix_id, cursor=cursor, count=count)
            if len(rows) == 0:
                break
            cursor += count

            for row in rows:
                aweme_type = row["aweme_type"]
                media_type = row["media_type"]
                is_multi_content = row["is_multi_content"]

                # 视频
                if aweme_type not in (0,) and media_type not in (4,):
                    continue

                # 图文（多图）
                # if aweme_type in (68,) and media_type in (2,):
                #     continue

                create_time = row["create_time"]
                aweme_id = row["aweme_id"]
                create_time_str = row["create_time_str"]
                title = row["title"]
                desc = row["desc"]
                tags = row["tags"]
                duration = row["duration"]

                video = row["video"]
                images = row["images"]

                task = {
                    "aweme_id": aweme_id,
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
                result.append(task)
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

    client = VideoDownload()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    flag = client.check_login()
    print(f"flag: {flag}")

    js = await client.get_video_list_by_min_date(
        # sec_user_id="MS4wLjABAAAAb0mqEsXmBehDdg2Q9mMA2T6YEWPGbEtYofSzX_bDnz4",
        # sec_user_id="MS4wLjABAAAAQinRMLyQNYA45OYXoCDrwszhRGaDVirRE1fTNSaGGkc",
        sec_user_id="MS4wLjABAAAADyrPwJGfqa_NWIw0jrrk1NURMonGw2RlPnX0ORc3MSA",
        min_date="2026-03-01 00:00:00"
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

    client = VideoDownload()

    flag = client.check_login()
    print(f"flag: {flag}")
    client.login_with_credentials_file(args.credentials_file)
    # client.login_with_qrcode_url()
    flag = client.check_login()
    print(f"flag: {flag}")

    js = await client.get_all_video_by_mix_id(
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
