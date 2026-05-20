#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests


class MCHoseOSS(object):
    def __init__(self,
                 host: str
                 ):
        self.host = host.rstrip("/") or "http://192.168.150.13:8888"

    def upload_file(
        self,
        file_path: Union[str, Path],
        token: Optional[str] = None,
        environment: str = "test",
        cache_max_age: Union[int, str] = 15552000,
        timeout_s: int = 60,
    ) -> Dict[str, Any]:
        url = f"{self.host}/api/upload-resource"
        headers = {
            "Authorization": f"Bearer {token}",
        }
        params = {
            "environment": environment
        }
        data = {
            "cacheMaxAge": str(cache_max_age)
        }

        p = Path(file_path)
        filename = p.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with open(p.as_posix(), "rb") as f:
            files = {"file": (filename, f, content_type)}

            resp = requests.post(
                url,
                params=params,
                headers=headers,
                files=files,
                data=data,
                timeout=timeout_s,
            )
        resp.raise_for_status()
        return resp.json()


def main():

    token = "eyJ1c2VySWQiOiJUN3U0dUJ3emdpenNtZEJmIiwic2Vzc2lvbklkIjoiMTc3ODMxMjU3NTk0My1pdWE2ZDFvamh4IiwiZXhwIjoxNzc4OTE3Mzc1fQ=="

    # 示例：把本地文件上传到 MCHose OSS
    oss = MCHoseOSS(host="http://192.168.150.13:8888")
    js = oss.upload_file(
        file_path=r"C:\Users\Administrator\Downloads\resized_kitten.png",
        token=token,
        environment="test",
    )
    print(json.dumps(js, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
