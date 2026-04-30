#!/usr/bin/python3
# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import hashlib
import json
import logging
import httpx
import requests
from typing import List

from toolbox.design_patterns.singleton import ParamsSingleton

logger = logging.getLogger("toolbox")


class BanNiuClient(ParamsSingleton):
    def __init__(self, app_key: str, app_secret: str, access_token: str) -> None:
        if not self._initialized:
            self.app_key = app_key
            self.app_secret = app_secret
            self.access_token = access_token

            self.url = "https://open.bytenew.com/gateway/api/miniAPI"

            self._initialized = True

    def get_sign(self, params: dict) -> dict:
        sign = "".join([f"{k}{params[k]}" for k in sorted([k for k in params.keys()])])
        sign = f"{self.app_secret}{sign}{self.app_secret}"
        sign = hashlib.md5(sign.encode("utf-8")).hexdigest().upper()
        return sign

    def get_headers(self):
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        return headers

    def get_params(self, params: dict) -> dict:
        params_ = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "v": "1",

            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "access_token": self.access_token,

            **params
        }
        params_["sign"] = self.get_sign(params=params_)
        return params_


    def project_list(self):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/hdpaht
        """
        params = {
            "method": "project.list",
        }
        params = self.get_params(params)
        response = requests.get(self.url, params=params)
        js = response.json()
        return js

    def column_list(self, project_id: str):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/vcp5eb
        """
        params = {
            "method": "column.list",
            "project_id": project_id,
        }
        params = self.get_params(params)
        response = requests.get(self.url, params=params)
        js = response.json()
        return js

    def task_list(self, project_id: str,
                  page_size: int = 10, page_num: int = 1,
                  star_created: str = None, end_created: str = None,
                  task_status: int = None,
                  condition_column: str = None,
                  ):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/wlx5f9

        star_created: yyyy-MM-dd HH:mm:ss
        end_created: yyyy-MM-dd HH:mm:ss
        task_status: 0, 等处理; 1, 已完成; 2, 处理中; 3, 暂停中; 4, 已关闭
        """
        params = {
            "method": "task.list",
            "project_id": project_id,

            "page_size": page_size,
            "page_num": page_num,
        }
        if star_created is not None:
            params["star_created"] = star_created
        if end_created is not None:
            params["end_created"] = end_created
        if task_status in (0, 1, 2, 3, 4):
            params["task_status"] = task_status
        if condition_column is not None:
            params["condition_column"] = condition_column

        params = self.get_params(params=params)
        response = requests.get(self.url, params=params)
        js = response.json()
        return js

    def task_get_task(self, project_id: str, task_id: str):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/lysx6i
        """
        params = {
            "method": "task.getTask",
            "project_id": project_id,
            "task_id": task_id,
        }
        params = self.get_params(params=params)
        response = requests.get(self.url, params=params)
        js = response.json()
        return js

    def task_create(self):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/yysw83
        """
        pass

    def task_update(self, project_id: str, app_id: str, task_id: str, contents: dict):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/xgu666
        """
        headers = self.get_headers()

        params = {
            "method": "task.update",
        }
        params = self.get_params(params=params)

        data = {
            "project_id": project_id,
            "app_id": app_id,
            "task_id": task_id,
            "contents": contents,
            "header": None
        }

        response = requests.post(
            self.url,
            headers=headers,
            params=params,
            data=json.dumps(data),
        )
        js = response.json()
        return js

    def task_batch_update(self, data: List[dict]):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/te7i0p
        """
        headers = self.get_headers()

        params = {
            "method": "task.batchUpdate",
        }
        params = self.get_params(params=params)

        data_example = [
            {
                "project_id": "project_id",
                "app_id": "app_id",
                "task_id": "task_id",
                "contents": "contents",
                "header": None
            }
        ]

        data = {"data": data}

        response = requests.post(
            self.url,
            headers=headers,
            params=params,
            data=json.dumps(data),
        )
        js = response.json()
        return js


class AsyncBanNiuClient(ParamsSingleton):
    """
    BanNiuClient 的异步版本。

    说明：接口签名尽量与同步版一致，底层使用 httpx.AsyncClient 真正异步请求。
    """

    def __init__(self, app_key: str, app_secret: str, access_token: str) -> None:
        if not self._initialized:
            self.app_key = app_key
            self.app_secret = app_secret
            self.access_token = access_token

            self.url = "https://open.bytenew.com/gateway/api/miniAPI"

            self._initialized = True

    def get_new_async_session(self):
        session = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=100, keepalive_expiry=100),
            headers=self.get_headers(),
            trust_env=False,
        )
        return session

    def get_sign(self, params: dict) -> dict:
        sign = "".join([f"{k}{params[k]}" for k in sorted([k for k in params.keys()])])
        sign = f"{self.app_secret}{sign}{self.app_secret}"
        sign = hashlib.md5(sign.encode("utf-8")).hexdigest().upper()
        return sign

    def get_headers(self):
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        return headers

    def get_params(self, params: dict) -> dict:
        params_ = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "v": "1",
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "access_token": self.access_token,
            **params,
        }
        params_["sign"] = self.get_sign(params=params_)
        return params_

    async def project_list(self):
        params = {"method": "project.list"}
        params = self.get_params(params)
        async_session = self.get_new_async_session()
        response = await async_session.get(self.url, params=params)
        response.raise_for_status()
        js = response.json()
        return js

    async def column_list(self, project_id: str):
        params = {
            "method": "column.list",
            "project_id": project_id,
        }
        params = self.get_params(params)
        async_session = self.get_new_async_session()
        response = await async_session.get(self.url, params=params)
        response.raise_for_status()
        js = response.json()
        return js

    async def task_list(
        self,
        project_id: str,
        page_size: int = 10,
        page_num: int = 1,
        star_created: str = None,
        end_created: str = None,
        task_status: int = None,
        condition_column: str = None,
    ):
        params = {
            "method": "task.list",
            "project_id": project_id,
            "page_size": page_size,
            "page_num": page_num,
        }
        if star_created is not None:
            params["star_created"] = star_created
        if end_created is not None:
            params["end_created"] = end_created
        if task_status in (0, 1, 2, 3, 4):
            params["task_status"] = task_status
        if condition_column is not None:
            params["condition_column"] = condition_column

        params = self.get_params(params=params)
        async_session = self.get_new_async_session()
        response = await async_session.get(self.url, params=params)
        response.raise_for_status()
        js = response.json()
        return js

    async def task_get_task(self, project_id: str, task_id: str):
        params = {
            "method": "task.getTask",
            "project_id": project_id,
            "task_id": task_id,
        }
        params = self.get_params(params=params)
        async_session = self.get_new_async_session()
        response = await async_session.get(self.url, params=params)
        response.raise_for_status()
        js = response.json()
        return js

    async def task_update(self, project_id: str, app_id: str, task_id: str, contents: dict):
        params = {
            "method": "task.update",
        }
        params = self.get_params(params=params)
        data = {
            "project_id": project_id,
            "app_id": app_id,
            "task_id": task_id,
            "contents": contents,
            "header": None,
        }
        async_session = self.get_new_async_session()
        response = await async_session.post(
            self.url,
            params=params,
            data=json.dumps(data),
        )
        response.raise_for_status()
        js = response.json()
        return js

    async def task_batch_update(self, data: List[dict]):
        params = {
            "method": "task.batchUpdate",
        }
        params = self.get_params(params=params)
        data = {"data": data}
        async_session = self.get_new_async_session()
        response = await async_session.post(
            self.url,
            params=params,
            data=json.dumps(data),
        )
        response.raise_for_status()
        js = response.json()
        return js


def main():
    from project_settings import environment

    APP_KEY = environment.get("BANNIU_APP_KEY")
    APP_SECRET = environment.get("BANNIU_APP_SECRET")
    ACCESS_TOKEN = environment.get("BANNIU_ACCESS_TOKEN")

    now_dt = datetime.now()
    one_year_ago_dt = now_dt - timedelta(days=1)

    app_id = "41339"
    project_id = "37728"
    task_id = "6690538"

    client = BanNiuClient(app_key=APP_KEY, app_secret=APP_SECRET, access_token=ACCESS_TOKEN)
    # js = client.project_list()
    js = client.column_list(project_id=project_id)
    print(json.dumps(js, ensure_ascii=False, indent=4))

    js = client.task_list(
        project_id=project_id,
        star_created=one_year_ago_dt.strftime("%Y-%m-%d %H:%M:%S"),
        end_created=now_dt.strftime("%Y-%m-%d %H:%M:%S"),
    )
    # js = client.task_get_task(project_id=project_id, task_id=task_id)
    print(json.dumps(js, ensure_ascii=False, indent=4))
    # contents = js["response"]["map"]["result"]
    contents = {
        "37761": "这款键盘使用感受真的不错，外观颜值我认为非常好看，... http://xhslink.com/o/29WYGfZ9mMe  先复制这段文字，再进【小红书】查看完整笔记。2"
    }
    # print(json.dumps(contents, ensure_ascii=False, indent=4))
    # js = client.task_update(project_id=project_id, app_id=app_id, task_id=task_id, contents=contents)
    # print(json.dumps(js, ensure_ascii=False, indent=4))

    js = client.task_batch_update(data=[
        {
            "project_id": project_id,
            "app_id": app_id,
            "task_id": task_id,
            "contents": contents,
            "header": None
        }
    ])
    print(json.dumps(js, ensure_ascii=False, indent=4))

    return


if __name__ == "__main__":
    main()
