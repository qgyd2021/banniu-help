#!/usr/bin/python3
# -*- coding: utf-8 -*-
from typing import Dict

import requests
from toolbox.weibo.weibo_client import WeiboClient
from toolbox.weibo.media.share_media_download import ShareMediaDownload


class FreshImageUrl(WeiboClient):
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Referer": "https://weibo.com/",
    }

    candidate_referer = [
        "https://weibo.com/", "https://weibo.com/", "https://m.weibo.cn/", "https://weibo.cn/"
    ]

    def __init__(self):
        super().__init__()
        self.share_client = ShareMediaDownload()

    def ensure_image_url(self, image_url: str, share_url: str, image_index: int):
        response = requests.request(
            "GET",
            image_url,
            headers=self.headers, stream=True, timeout=60
        )
        if response.status_code in (200, 206):
            return response

        response.close()
        post_meta = self.share_client.get_post_meta_by_share_url(share_url)

        image_urls = post_meta["image_urls"]
        image_url = image_urls[image_index]
        response = requests.request(
            "GET",
            image_url,
            headers=self.headers, stream=True, timeout=60
        )
        if response.status_code in (200, 206):
            return response
        raise NotImplementedError


class FreshVideoUrl(WeiboClient):
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Referer": "https://weibo.com/",
        "Origin": "https://weibo.com",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }
    def __init__(self):
        super().__init__()
        self.share_client = ShareMediaDownload()

    def ensure_video_url(self, video_url: str, share_url: str, video_index: int):
        response = requests.request(
            "GET",
            video_url,
            headers=self.headers, stream=True, timeout=60
        )
        status_code = response.status_code
        if status_code in (200, 206):
            return response

        response.close()
        post_meta = self.share_client.get_post_meta_by_share_url(share_url)

        video_urls = post_meta["video_urls"]
        video_url = video_urls[video_index]
        response = requests.request(
            "GET",
            video_url,
            headers=self.headers, stream=True, timeout=60
        )
        if response.status_code in (200, 206):
            return response
        raise NotImplementedError


def main():
    from fastapi.responses import StreamingResponse

    def iter_chunks(resp):
        for chunk in resp.raw.stream(1024 * 128, decode_content=False):
            if chunk:
                yield chunk
        resp.close()

    # fresh = FreshImageUrl()
    # response = fresh.ensure_image_url(
    #     image_url="https://wx4.sinaimg.cn/mw2000/006mL8GZgy1ic8z4s721ij32c03401kz.jpg",
    #     image_index=0,
    #     share_url="https://weibo.com/5833111217/5288449626348169"
    # )

    fresh = FreshVideoUrl()
    response = fresh.ensure_video_url(
        video_url="https://video.weibo.com/media/play?livephoto=https%3A%2F%2Flivephoto.us.sinaimg.cn%2F003nZGBvgx08wUCY1wnK0f0f0100qOo80k01.mov",
        share_url="https://weibo.com/6130661131/5288421876566468",
        video_index=0,
    )

    stream = StreamingResponse(iter_chunks(response), status_code=response.status_code, media_type=response.headers.get("Content-Type", "application/octet-stream"))
    print(stream)
    return


if __name__ == "__main__":
    main()
