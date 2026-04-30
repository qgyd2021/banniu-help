#!/usr/bin/python3
# -*- coding: utf-8 -*-
from typing import Dict

import requests
from toolbox.xiaohongshu.xiaohongshu_client import XiaoHongShuClient
from toolbox.xiaohongshu.media.share_media_download import ShareMediaDownload


class FreshImageUrl(XiaoHongShuClient):
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
        self.share_client = ShareMediaDownload()

    def ensure_image_url(self, image_url: str, image_index: int, share_url: str):
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


class FreshVideoUrl(XiaoHongShuClient):
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
        image_url="http://sns-webpic-qc.xhscdn.com/202604251103/1f341230662d6c9ecafeaa0da719c202/1040g2sg31uvh0ffk2q6g5pekj5613iqj2grpa8g!nd_dft_wgth_jpg_3",
        image_index=0,
        share_url="http://xhslink.com/o/iacZa3MRnB"
    )

    stream = StreamingResponse(iter_chunks(response), status_code=response.status_code, media_type=response.headers.get("Content-Type", "image/jpeg"))
    print(stream)
    return


if __name__ == "__main__":
    main()
