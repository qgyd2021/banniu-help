#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import mimetypes
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests


# 与前端 feedback.js / feedback-upload-api.md 一致：生产直传阿里云 OSS
DEFAULT_OSS_UPLOAD_URL = "https://ioss.maicong.cn/"


class OssClient(object):
    """
    反馈问卷场景：先拉取 OSS Post 签名，再 multipart 直传 ioss.maicong.cn。

    ``host`` 一般为业务网关根，如 ``https://www.maicong.cn``；
    签名路径为 ``{host}/mchose/questionnaire/signature``（与现有前端 base 一致）。
    """

    def __init__(self, host: str):
        self.host = host.rstrip("/")

    def get_signature(self) -> Dict[str, Any]:
        url = f"{self.host}/mchose/questionnaire/signature"
        headers = {
            "Content-Type": "application/json",
            "Referer": "https://www.mchose.com.cn/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
        }
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        js = response.json()
        if js.get("code") != 200:
            raise ValueError(js.get("message") or "获取上传签名失败")
        return js

    @staticmethod
    def build_upload_object_key(original_name: str) -> str:
        rnd = "".join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(8))
        ts = int(time.time() * 1000)
        return f"webdriver/feedback/{ts}-{rnd}-{original_name}"

    def upload_file(
        self,
        file_path: Union[str, Path],
        *,
        timeout_s: int = 120,
    ) -> Dict[str, Any]:
        js = self.get_signature()
        # print(json.dumps(js, ensure_ascii=False, indent=2))
        policy = js["data"]["policy"]
        signature = js["data"]["signature"]
        x_oss_date = js["data"]["x_oss_date"]
        x_oss_credential = js["data"]["x_oss_credential"]
        x_oss_signature_version = js["data"]["x_oss_signature_version"]
        security_token = js["data"]["security_token"]

        p = Path(file_path)
        filename = p.name
        object_key = self.build_upload_object_key(filename)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        url = "https://ioss.maicong.cn/"

        with open(p.as_posix(), "rb") as fh:
            files = [
                ("key", (None, object_key)),
                ("policy", (None, str(policy))),
                ("x-oss-signature-version", (None, str(x_oss_signature_version))),
                ("x-oss-credential", (None, str(x_oss_credential))),
                ("x-oss-date", (None, str(x_oss_date))),
                ("x-oss-signature", (None, str(signature))),
                ("x-oss-security-token", (None, security_token)),
                ("success_action_status", (None, "200")),
                ("file", (filename, fh, content_type)),
            ]
            response = requests.post(url, files=files, timeout=timeout_s)

        if response.status_code != 200:
            raise RuntimeError(f"OSS 上传失败: {response.status_code} {response.text[:500]}")

        url = f"https://ioss.maicong.cn/{object_key}"
        return {
            "url": url,
            "key": object_key,
            "status_code": response.status_code,
            "body": response.text,
        }


def main():
    """
    :return:
    {
      "url": "https://ioss.maicong.cn/webdriver/feedback/1778471026355-2oqhr6ge-resized_kitten.png",
      "key": "webdriver/feedback/1778471026355-2oqhr6ge-resized_kitten.png",
      "status_code": 200,
      "body": ""
    }
    """
    client = OssClient("https://www.maicong.cn")

    js = client.upload_file(
        file_path=r"C:\Users\Administrator\Downloads\resized_kitten.png",
    )
    print(json.dumps(js, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
