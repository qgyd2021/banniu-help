#!/usr/bin/python3
# -*- coding: utf-8 -*-
from typing import Dict

import requests
from toolbox.bilibili.bilibili_client import BilibiliClient
from toolbox.bilibili.media.share_media_download import ShareMediaDownload


class FreshImageUrl(BilibiliClient):
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


class FreshVideoUrl(BilibiliClient):
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
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
        post_meta = self.share_client.video.get_post_meta_by_share_url(share_url)

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
    #     image_url="https://i0.hdslb.com/bfs/archive/380c98fbdba792cf773b6eb56755edecc9c3bd34.jpg",
    #     share_url="https://b23.tv/Fe8dviA"
    # )
    fresh = FreshVideoUrl()
    response = fresh.ensure_video_url(
        video_url="https://upos-sz-estgcos.bilivideo.com/upgcxcode/54/82/37666948254/37666948254-1-192.mp4?e=ig8euxZM2rNcNbR1hzdVhwdlhWRzhwdVhoNvNC8BqJIzNbfqXBvEqxTEto8BTrNvN0GvT90W5JZMkX_YN0MvXg8gNEV4NC8xNEV4N03eN0B5tZlqNxTEto8BTrNvNeZVuJ10Kj_g2UB02J0mN0B5tZlqNCNEto8BTrNvNC7MTX502C8f2jmMQJ6mqF2fka1mqx6gqj0eN0B599M=&oi=2005439131&mid=0&deadline=1777099452&trid=d0a462e22844491f8680efebc0456c8u&gen=playurlv3&og=cos&nbs=1&uipk=5&platform=pc&os=estgcos&upsig=6ceea418400a1bfc8264dee441e29f07&uparams=e,oi,mid,deadline,trid,gen,og,nbs,uipk,platform,os&bvc=vod&nettype=0&bw=977847&f=u_0_0&qn_dyeid=51d9997d6bb9b6cc0077a87669ec469c&agrr=0&buvid=145B9E2F-C324-22BB-67A1-93C44B427C3F90034infoc&build=0&dl=0&orderid=0,3",
        share_url="https://b23.tv/4yjJVWJ",
        video_index=0
    )

    stream = StreamingResponse(iter_chunks(response), status_code=response.status_code, media_type=response.headers.get("Content-Type", "image/jpeg"))
    print(stream)
    return


if __name__ == "__main__":
    main()
