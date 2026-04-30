#!/usr/bin/python3
# -*- coding: utf-8 -*-
from typing import Dict

import requests
from toolbox.dewu.dewu_client import DewuClient


class FreshImageUrl(DewuClient):
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    def __init__(self):
        super().__init__()

    def ensure_image_url(self, image_url: str, share_url: str, image_index: int):
        response = requests.request(
            "GET",
            image_url,
            headers=self.headers, stream=True, timeout=60
        )
        status_code = response.status_code
        if status_code in (200, 206):
            return response
        else:
            raise NotImplementedError()


class FreshVideoUrl(DewuClient):
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    def __init__(self):
        super().__init__()

    def ensure_video_url(self, video_url: str, share_url: str, video_index: int):
        response = requests.request(
            "GET",
            video_url,
            headers=self.headers, stream=True, timeout=60
        )
        status_code = response.status_code
        if status_code in (200, 206):
            return response
        raise NotImplementedError


def main():
    from fastapi.responses import StreamingResponse

    def iter_chunks(resp):
        for chunk in resp.raw.stream(1024 * 128, decode_content=False):
            if chunk:
                yield chunk
        resp.close()

    fresh = FreshImageUrl()
    response = fresh.ensure_image_url(
        image_url="https://i0.hdslb.com/bfs/archive/380c98fbdba792cf773b6eb56755edecc9c3bd34.jpg",
        share_url="https://b23.tv/Fe8dviA"
    )

    stream = StreamingResponse(iter_chunks(response), status_code=response.status_code, media_type=response.headers.get("Content-Type", "image/jpeg"))
    print(stream)
    return


if __name__ == "__main__":
    main()
