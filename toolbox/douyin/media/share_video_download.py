#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import logging
import re
import requests

logger = logging.getLogger("toolbox")


class ShareVideoDownload(object):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    def __init__(self):
        super().__init__()

    @staticmethod
    def get_share_url_by_share_text(text: str):
        pattern = r"https://v\.douyin\.com/[A-Za-z0-9_\-]+/"

        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is None:
            raise AssertionError(f"no share url found; text: {text}")
        share_url = match.group(0)
        return share_url

    def get_video_download_url_by_share_url(self, share_url: str):
        response = requests.request(
            "GET",
            url=share_url,
            headers=self.headers
        )
        if response.status_code != 200:
            raise AssertionError(f"invalid share_url: {share_url}, status_code: {response.status_code}")
        video_id = response.url.split("?")[0].strip("/").split("/")[-1]
        video_url = f"https://www.iesdouyin.com/share/video/{video_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1"
        }
        response = requests.request(
            "GET",
            url=video_url,
            headers=headers
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; video_url: {video_url}")

        # 使用正则表达式提取视频信息
        pattern = re.compile(
            pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            flags=re.DOTALL
        )
        match = pattern.search(response.text)
        if match is None:
            raise AssertionError(f"pattern parse failed; text: {response.text}")

        js = json.loads(match.group(1).strip())
        data = js["loaderData"]["video_(id)/page"]["videoInfoRes"]["item_list"][0]
        video_download_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        return video_download_url

    def download_video_by_video_download_url(self, video_download_url: str, filename: str):
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1"
        }
        response = requests.request(
            "GET",
            url=video_download_url,
            headers=headers,
            stream=True
        )
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {video_download_url}")

        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return filename

    def download_video_by_share_text(self, text: str, filename: str):
        share_url = self.get_share_url_by_share_text(text)
        video_download_url = self.get_video_download_url_by_share_url(share_url)
        self.download_video_by_video_download_url(video_download_url, filename)
        return filename


def main():
    client = ShareVideoDownload()

    text = """
    6.66 g@B.TL 01/22 pDH:/ 骆驼祥子的大结局，是普通人无法逃脱的命运吗 # 老舍 # 骆驼祥子  https://v.douyin.com/Bocl1I_wcdg/ 复制此链接，打开Dou音搜索，直接观看视频！
    """
    text = """
    5.89 t@r.Eh 04/11 QxF:/ 一口气1小时10分看懂《心经》6大角度，放空自己，究竟涅槃 # 心经 # 抖音花式讲书大赛 # 文脉里的中国 # 国学文化 # 佛学智慧  https://v.douyin.com/FgWK9eip8sA/ 复制此链接，打开Dou音搜索，直接观看视频！
    """
    filename = client.download_video_by_share_text(text, "test.mp4")
    print(filename)

    return


if __name__ == "__main__":
    main()
