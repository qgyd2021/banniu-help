#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
https://pypi.org/project/biliupload/
https://github.com/SocialSisterYi/bilibili-API-collect
"""
import argparse
import json
import logging
import math
from pathlib import Path
import re

logger = logging.getLogger("toolbox")

import requests
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from tqdm import tqdm

from project_settings import project_path
from toolbox.bilibili.bilibili_client import BilibiliClient


class BilibiliVideoUploader20200810(BilibiliClient):
    def __init__(self):
        super().__init__()

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def pre_upload(self, filename, filesize):
        url = "https://member.bilibili.com/preupload"
        params = {
            "name":	filename,
            "size":	filesize,
            # The parameters below are fixed
            "r": "upos",
            "profile": "ugcupos/bup",
            "ssl":	0,
            "version":	"2.8.9",
            "build": "2080900",
            "upcdn": "bda2",
            "probe_version": "20200810"
        }

        response = requests.request(
            method="POST",
            url=url,
            headers={
                "TE": "Trailers",
                **self.headers,
            },
            params=params,
            cookies=self.cookies,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        if js["OK"] != 1:
            raise AssertionError(f"request failed;")
        return js

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def get_upload_video_id(self, endpoint, upos_uri, auth, **kwargs):
        url = f"https:{endpoint}/{upos_uri}?uploads&output=json"
        response = requests.request(
            method="POST",
            url=url,
            headers={
                "X-Upos-Auth": auth,
                **self.headers,
            },
            cookies=self.cookies,
        )

        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        if js["OK"] != 1:
            raise AssertionError(f"request failed;")
        return js

    def upload_video_in_chunks(self, endpoint, upos_uri, auth, upload_id, fileio, filesize, chunk_size, chunks):
        url = f"https:{endpoint}/{upos_uri}"
        params = {
            "partNumber": None,  # start from 1
            "uploadId":	upload_id,
            "chunk": None,  # start from 0
            "chunks": chunks,
            "size":	None,  # current batch size
            "start": None,
            "end":	None,
            "total": filesize,
        }

        process_bar = tqdm(desc=f"bilibili_upload_video({endpoint})", total=chunks)
        for chunknum in range(chunks):
            start = fileio.tell()
            batchbytes = fileio.read(chunk_size)
            params["partNumber"] = chunknum + 1
            params["chunk"] = chunknum
            params["size"] = len(batchbytes)
            params["start"] = start
            params["end"] = fileio.tell()
            response = requests.request(
                method="PUT",
                url=url,
                headers={
                    "X-Upos-Auth": auth,
                    **self.headers,
                },
                params=params,
                data=batchbytes,
                cookies=self.cookies,
            )
            if response.status_code != 200:
                raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
            process_bar.update(n=1)

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def finish_upload(self, endpoint, upos_uri, auth, filename, upload_id, biz_id, chunks):
        url = f"https:{endpoint}/{upos_uri}"
        params = {
            "output": "json",
            "name":	filename,
            "profile" : "ugcupos/bup",
            "uploadId": upload_id,
            "biz_id": biz_id
        }
        data = {
            "parts": [
                {"partNumber": i, "eTag": "etag"}
                for i in range(chunks, 1)
            ]
        }
        response = requests.request(
            method="POST",
            url=url,
            headers={
                "X-Upos-Auth": auth,
                **self.headers,
            },
            params=params,
            json=data,
            cookies=self.cookies,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        if js["OK"] != 1:
            raise AssertionError(f"request failed;")
        return js

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def publish_video(self, bilibili_filename, metadata: dict):
        url = f'https://member.bilibili.com/x/vu/web/add?csrf={self.cookies["bili_jct"]}'

        data = {
            "copyright": metadata["copyright"],
            "videos": [
                {
                    "filename": bilibili_filename,
                    "title": metadata["title"][:80],
                    "desc": metadata["desc"]
                }
            ],
            "source": metadata["source"],
            "tid": metadata["tid"],
            "title": metadata["title"][:80],
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

        response = requests.request(
            method="POST",
            url=url,
            headers={
                "TE": "Trailers",
                **self.headers,
            },
            json=data,
            cookies=self.cookies,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def upload_video_file(self, filename):
        filename = Path(filename)
        filesize = filename.stat().st_size

        js = self.pre_upload(filename=filename, filesize=filesize)
        endpoint = js["endpoint"]
        upos_uri = js["upos_uri"].split("//")[-1]
        auth = js["auth"]
        biz_id = js["biz_id"]
        chunk_size = js["chunk_size"]
        chunks = math.ceil(filesize / chunk_size)

        upload_video_id_response = self.get_upload_video_id(
            endpoint=endpoint,
            upos_uri=upos_uri,
            auth=auth,
        )
        upload_id = upload_video_id_response["upload_id"]
        key = upload_video_id_response["key"]

        bilibili_filename = re.search(r"/(.*)\.", key).group(1)
        fileio = filename.open(mode="rb")
        self.upload_video_in_chunks(
            endpoint=endpoint,
            upos_uri=upos_uri,
            auth=auth,
            upload_id=upload_id,
            fileio=fileio,
            filesize=filesize,
            chunk_size=chunk_size,
            chunks=chunks
        )
        fileio.close()

        # notify the all chunks have been uploaded
        self.finish_upload(
            endpoint=endpoint,
            upos_uri=upos_uri, auth=auth, filename=filename,
            upload_id=upload_id, biz_id=biz_id, chunks=chunks
        )
        return biz_id, upload_id, bilibili_filename

    def upload_video_and_publish(self, filename: str, metadata: dict):
        _, upload_id, bilibili_filename = self.upload_video_file(filename)
        logger.info(f"finish uploading, upload_id: {upload_id}, bilibili_filename: {bilibili_filename}, filename: {filename}")
        publish_video_response = self.publish_video(bilibili_filename=bilibili_filename, metadata=metadata)

        bvid = None
        status_code = publish_video_response["code"]
        if status_code != 0:
            # 137022
            # 21104, 第(1)个视频的标题过长,已经超过80个字符
            message = publish_video_response["message"]
            logger.info(f"publish_video failed; code: {status_code}, message: {message}")
        else:
            try:
                bvid = publish_video_response["data"]["bvid"]
            except KeyError as error:
                raise KeyError(f"publish_video failed; KeyError: {error}, publish_video_response: {publish_video_response}")
        return bvid


class BilibiliVideoUploader20221109(BilibiliVideoUploader20200810):
    def __init__(self):
        super().__init__()

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def pre_upload(self, filename, filesize):
        url = "https://member.bilibili.com/preupload"
        params = {
            "probe_version": "20221109",
            "upcdn": "bldsa",
            "zone": "cs",
            "name": filename,
            "r": "upos",
            "profile": "ugcfx/bup",
            "ssl": 0,
            "version": "2.14.0.0",
            "build": "2140000",
            "size": filesize,
        }
        response = requests.request(
            method="POST",
            url=url,
            headers={
                "TE": "Trailers",
                **self.headers,
            },
            params=params,
            cookies=self.cookies,
        )

        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        if js["OK"] != 1:
            raise AssertionError(f"request failed;")
        return js

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def get_upload_video_id(self,
                            endpoint, upos_uri, auth,
                            filesize, chunk_size, biz_id,
                            **kwargs
                            ):
        url = f"https:{endpoint}/{upos_uri}?uploads&output=json"
        params = {
            "profile": "ugcfx/bup",
            "filesize": filesize,
            "partsize": chunk_size,
        }
        response = requests.request(
            method="POST",
            url=url,
            headers={
                "X-Upos-Auth": auth,
                **self.headers,
            },
            params=params,
            cookies=self.cookies,
        )

        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        if js["OK"] != 1:
            raise AssertionError(f"request failed;")
        return js

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def finish_upload(self, endpoint, upos_uri, auth, filename, upload_id, biz_id, chunks):
        url = f"https:{endpoint}/{upos_uri}"

        params = {
            "output": "json",
            "name":	filename,
            "profile" : "ugcfx/bup",
            "uploadId": upload_id,
            "biz_id": biz_id
        }
        data = {
            "parts": [
                {"partNumber": i+1, "eTag": "etag"}
                for i in range(chunks)
            ]
        }
        response = requests.request(
            method="POST",
            url=url,
            headers={
                "X-Upos-Auth": auth,
                **self.headers,
            },
            params=params,
            data=json.dumps(data),
            cookies=self.cookies,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        if js["OK"] != 1:
            raise AssertionError(f"request failed;")
        return js

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.ERROR),
    )
    def publish_video(self, bilibili_filename, metadata: dict):
        url = f'https://member.bilibili.com/x/vu/web/add?csrf={self.cookies["bili_jct"]}'

        data = {
            "copyright": metadata["copyright"],
            "videos": [
                {
                    "filename": bilibili_filename,
                    "title": metadata["title"],
                    "desc": metadata["desc"]
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

        response = requests.request(
            method="POST",
            url=url,
            headers={
                "TE": "Trailers",
                **self.headers,
            },
            json=data,
            cookies=self.cookies,
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def upload_video_file(self, filename: str):
        filename = Path(filename)
        filesize = filename.stat().st_size

        js = self.pre_upload(filename=filename, filesize=filesize)
        endpoint = js["endpoint"]
        upos_uri = js["upos_uri"].split("//")[-1]
        auth = js["auth"]
        biz_id = js["biz_id"]
        chunk_size = js["chunk_size"]
        chunks = math.ceil(filesize / chunk_size)

        upload_video_id_response = self.get_upload_video_id(
            endpoint=endpoint,
            upos_uri=upos_uri,
            auth=auth,
            filesize=filesize,
            chunk_size=chunk_size,
            biz_id=biz_id,
        )
        upload_id = upload_video_id_response["upload_id"]
        key = upload_video_id_response["key"]

        bilibili_filename = re.search(r"/(.*)\.", key).group(1)
        fileio = filename.open(mode="rb")
        self.upload_video_in_chunks(
            endpoint=endpoint,
            upos_uri=upos_uri,
            auth=auth,
            upload_id=upload_id,
            fileio=fileio,
            filesize=filesize,
            chunk_size=chunk_size,
            chunks=chunks
        )
        fileio.close()

        self.finish_upload(
            endpoint=endpoint,
            upos_uri=upos_uri, auth=auth, filename=filename.name,
            upload_id=upload_id, biz_id=biz_id, chunks=chunks
        )

        return biz_id, upload_id, bilibili_filename


# BilibiliVideoUploader = BilibiliVideoUploader20200810
BilibiliVideoUploader = BilibiliVideoUploader20221109


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--key_of_credentials",
        default="bilibili_chenjiesen_credentials",
        type=str
    )
    parser.add_argument(
        "--filename",
        default=(project_path / "data/tasks/chenjieshen_douyin_video_to_bilibili/video/douyin/陈杰森/754766069892763162520250908_101827首富黄光裕王者归来携国美杀入AI社交赛道 资本新秀陈杰森对话商业传奇二资本市场背后首富眼中的.mp4").as_posix(),
        type=str
    )
    args = parser.parse_args()
    return args


def main():
    import log
    from project_settings import project_path, log_directory, environment

    log.setup_size_rotating(log_directory=log_directory)

    args = get_args()

    client = BilibiliVideoUploader()

    flag = client.check_login()
    print(f"flag: {flag}")
    credentials = environment.get(args.key_of_credentials, dtype=json.loads)
    client.login_with_credentials_info(credentials)
    flag = client.check_login()
    print(f"flag: {flag}")

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
        "cover": "",
        "dynamic": "",
    }

    bvid = client.upload_video_and_publish(
        filename=args.filename,
        metadata={
            "title": "九三阅兵的意义有多重大。 为什么说这次阅兵是“雷军式BOSS直销”？来的是客户，更是未来的“合伙人”！",
            "desc": "九三阅兵的意义有多重大。 为什么说这次阅兵是“雷军式BOSS直销”？来的是客户，更是未来的“合伙人”！#阅兵 #金融 #商业 #商机 #干货分享",
            "tag": ",".join(tags),

            "copyright": 1,
            "source": None,
            "tid": 138,
            "cover": "",
            "dynamic": "",
        }
    )
    print(f"bvid: {bvid}")
    return


if __name__ == "__main__":
    main()
