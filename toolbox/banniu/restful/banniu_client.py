#!/usr/bin/python3
# -*- coding: utf-8 -*-
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import hashlib
import json
import logging
import httpx
import requests
from typing import List

import cacheout

from toolbox.design_patterns.singleton import ParamsSingleton

logger = logging.getLogger("toolbox")


class BanNiuRestfulClient(ParamsSingleton):
    def __init__(self, app_key: str, app_secret: str, access_token: str, time_zone_info: str = "Asia/Shanghai") -> None:
        if not self._initialized:
            self.app_key = app_key
            self.app_secret = app_secret
            self.access_token = access_token
            self.time_zone_info = time_zone_info

            self.mini_api_url = "https://open.bytenew.com/gateway/api/miniAPI"
            self.common_url = "https://open.bytenew.com/gateway/api/common"

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
            "timestamp": datetime.now(ZoneInfo(self.time_zone_info)).strftime("%Y-%m-%d %H:%M:%S"),
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
        response = requests.get(self.mini_api_url, params=params)
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
        response = requests.get(self.mini_api_url, params=params)
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
        task_status: 0, 待处理; 1, 已完成; 2, 处理中; 3, 暂停中; 4, 已关闭
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
        response = requests.get(self.mini_api_url, params=params)
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
        response = requests.get(self.mini_api_url, params=params)
        js = response.json()
        return js

    def task_create(self, project_id: str, app_id: str, user_id: str, contents: dict):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/yysw83
        """
        headers = self.get_headers()

        params = {
            "method": "task.create",
        }
        params = self.get_params(params=params)

        data = {
            "project_id": project_id,
            "app_id": app_id,
            "user_id": None,
            # "user_id": user_id,
            "contents": contents,
            "header": None
        }
        response = requests.post(
            self.mini_api_url,
            headers=headers,
            params=params,
            data=json.dumps(data),
        )
        js = response.json()
        return js

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
            self.mini_api_url,
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
            self.mini_api_url,
            headers=headers,
            params=params,
            data=json.dumps(data),
        )
        js = response.json()
        return js

    def file_url_upload(self, contents: list):
        """
        https://banniu.yuque.com/staff-dmhmqa/sg1xhc/ick9va
        """
        headers = self.get_headers()

        params = {
            "method": "file.url.upload",
        }
        params = self.get_params(params=params)

        data = {"contents": contents}

        response = requests.post(
            self.common_url,
            headers=headers,
            params=params,
            data=json.dumps(data),
        )
        js = response.json()
        return js


class AsyncBanNiuRestfulClient(BanNiuRestfulClient):
    """
    BanNiuRestfulClient 的异步版本。

    说明：接口签名尽量与同步版一致，底层使用 httpx.AsyncClient 真正异步请求；
    每次调用在 ``async with`` 内创建/关闭客户端，避免连接泄漏。
    """

    def __init__(self, app_key: str, app_secret: str, access_token: str) -> None:
        super().__init__(app_key=app_key, app_secret=app_secret, access_token=access_token)

    @asynccontextmanager
    async def _async_json_client(self):
        async with httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=100, keepalive_expiry=100),
            headers=self.get_headers(),
            trust_env=False,
            timeout=120.0,
        ) as client:
            yield client

    def get_new_async_session(self) -> httpx.AsyncClient:
        """
        返回未托管生命周期的 ``httpx.AsyncClient``（与历史用法兼容）。

        调用方必须在用完后执行 ``await client.aclose()``；一般应优先使用
        本类自带的 ``async def project_list`` 等方法。
        """
        return httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=100, keepalive_expiry=100),
            headers=self.get_headers(),
            trust_env=False,
            timeout=120.0,
        )

    async def project_list(self):
        params = {"method": "project.list"}
        params = self.get_params(params)
        async with self._async_json_client() as client:
            response = await client.get(self.mini_api_url, params=params)
        response.raise_for_status()
        return response.json()

    @cacheout.memoize(ttl=60 * 15)
    async def column_list(self, project_id: str):
        params = {
            "method": "column.list",
            "project_id": project_id,
        }
        params = self.get_params(params)
        async with self._async_json_client() as client:
            response = await client.get(self.mini_api_url, params=params)
        response.raise_for_status()
        return response.json()

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
        async with self._async_json_client() as client:
            response = await client.get(self.mini_api_url, params=params)
        response.raise_for_status()
        return response.json()

    async def task_get_task(self, project_id: str, task_id: str):
        params = {
            "method": "task.getTask",
            "project_id": project_id,
            "task_id": task_id,
        }
        params = self.get_params(params=params)
        async with self._async_json_client() as client:
            response = await client.get(self.mini_api_url, params=params)
        response.raise_for_status()
        return response.json()

    async def task_create(self, project_id: str, app_id: str, user_id: str, contents: dict):
        params = {
            "method": "task.create",
        }
        params = self.get_params(params=params)
        payload = {
            "project_id": project_id,
            "app_id": app_id,
            "user_id": None,
            "contents": contents,
            "header": None,
        }
        async with self._async_json_client() as client:
            response = await client.post(
                self.mini_api_url,
                params=params,
                json=payload,
            )
        response.raise_for_status()
        return response.json()

    async def task_update(self, project_id: str, app_id: str, task_id: str, contents: dict):
        params = {
            "method": "task.update",
        }
        params = self.get_params(params=params)
        payload = {
            "project_id": project_id,
            "app_id": app_id,
            "task_id": task_id,
            "contents": contents,
            "header": None,
        }
        async with self._async_json_client() as client:
            response = await client.post(
                self.mini_api_url,
                params=params,
                json=payload,
            )
        response.raise_for_status()
        return response.json()

    async def task_batch_update(self, data: List[dict]):
        params = {
            "method": "task.batchUpdate",
        }
        params = self.get_params(params=params)
        payload = {"data": data}
        async with self._async_json_client() as client:
            response = await client.post(
                self.mini_api_url,
                params=params,
                json=payload,
            )
        response.raise_for_status()
        return response.json()

    async def file_url_upload(self, contents: list):
        params = {
            "method": "file.url.upload",
        }
        params = self.get_params(params=params)
        payload = {"contents": contents}
        async with self._async_json_client() as client:
            response = await client.post(
                self.common_url,
                params=params,
                json=payload,
            )
        response.raise_for_status()
        return response.json()


def main():
    from project_settings import environment

    APP_KEY = environment.get("BANNIU_APP_KEY")
    APP_SECRET = environment.get("BANNIU_APP_SECRET")
    ACCESS_TOKEN = environment.get("BANNIU_ACCESS_TOKEN")

    now_dt = datetime.now()
    one_year_ago_dt = now_dt - timedelta(days=1)

    # https://banniu.yuque.com/staff-dmhmqa/sg1xhc/uo4nma
    app_id = "41339"
    project_id = "39369"
    task_id = "6690538"

    client = BanNiuRestfulClient(app_key=APP_KEY, app_secret=APP_SECRET, access_token=ACCESS_TOKEN)
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


def main2():
    """
    {
        "response": {
            "total_results": null,
            "page_no": null,
            "page_size": null,
            "code": 0,
            "has_next": null,
            "error_msg": null,
            "map": {
                "result": [
                    {
                        "fileName": "bytenew1.jpg",
                        "id": "WxU5cVKahMjzONrUONr6Gg==",
                        "suffix": ".jpg",
                        "url": "https://img0.baidu.com/it/u=958451078,2917540410&fm=253&app=138&f=JPEG?w=800&h=1200"
                    }
                ]
            },
            "isSuccess": null
        }
    }
    """
    from project_settings import environment

    APP_KEY = environment.get("BANNIU_APP_KEY")
    APP_SECRET = environment.get("BANNIU_APP_SECRET")
    ACCESS_TOKEN = environment.get("BANNIU_ACCESS_TOKEN")

    client = BanNiuRestfulClient(app_key=APP_KEY, app_secret=APP_SECRET, access_token=ACCESS_TOKEN)

    contents = [
        {
            "url": "https://img0.baidu.com/it/u=958451078,2917540410&fm=253&app=138&f=JPEG?w=800&h=1200",
            "name": "bytenew1.jpg",
            "type": "jpg",
            "signUrl": "1"
        },
    ]
    js = client.file_url_upload(contents=contents)
    print(json.dumps(js, ensure_ascii=False, indent=4))

    return


def main3():
    """
    searchType="1" 代表 等于(文本组件)；searchType="3" 代表 包含(文本组件模糊搜索)；
    searchType：
       1 等于
       2 不等于
       3 包含
       4 不包含
       5 包含任一项

    behaviorType：
       1 文本类型
       2 数值类型
       3 单选
       4 下拉
       5 多选
       6 联动
       7 日期时间
       8 日期区间
       9 评分
       10 附件
       11 富文本
       12 标签
    """
    from project_settings import environment

    APP_KEY = environment.get("BANNIU_APP_KEY")
    APP_SECRET = environment.get("BANNIU_APP_SECRET")
    ACCESS_TOKEN = environment.get("BANNIU_ACCESS_TOKEN")

    # https://banniu.yuque.com/staff-dmhmqa/sg1xhc/uo4nma
    app_id = "41339"
    project_id = "37728"
    task_id = "6690538"

    client = BanNiuRestfulClient(app_key=APP_KEY, app_secret=APP_SECRET, access_token=ACCESS_TOKEN)

    condition_column = [
        {
            "id": 37776,
            "behaviorType": 1,
            "searchType": "1",
            "value": "曹付庚"
        },
        {
            "id": 37729,
            "behaviorType": 1,
            "searchType": "1",
            "value": "13675639166"
        }
    ]
    condition_column = json.dumps(condition_column)
    js = client.task_list(
        project_id=project_id,
        condition_column=condition_column
    )
    print(json.dumps(js, ensure_ascii=False, indent=4))

    return


def main4():
    from project_settings import environment

    APP_KEY = environment.get("BANNIU_APP_KEY")
    APP_SECRET = environment.get("BANNIU_APP_SECRET")
    ACCESS_TOKEN = environment.get("BANNIU_ACCESS_TOKEN")

    app_id = "41339"
    project_id = "39369"

    client = BanNiuRestfulClient(app_key=APP_KEY, app_secret=APP_SECRET, access_token=ACCESS_TOKEN)

    condition_column = [
        {
            "id": 39395,
            "behaviorType": 1,
            "searchType": "1",
            "value": 37783
        },
    ]
    condition_column = json.dumps(condition_column)
    js = client.task_list(
        project_id=project_id,
        condition_column=condition_column
    )
    print(json.dumps(js, ensure_ascii=False, indent=4))

    return


def main5():
    """
    "7373824\n7321359"
    :return:
    """
    from project_settings import environment

    APP_KEY = environment.get("BANNIU_APP_KEY")
    APP_SECRET = environment.get("BANNIU_APP_SECRET")
    ACCESS_TOKEN = environment.get("BANNIU_ACCESS_TOKEN")

    app_id = "41339"
    project_id = "39369"

    client = BanNiuRestfulClient(app_key=APP_KEY, app_secret=APP_SECRET, access_token=ACCESS_TOKEN)

    condition_column = [
        {
            "id": 0,
            "behaviorType": -1,
            "searchType": "5",
            "value": ["7373824", "7321359"]
        },
        {
            "id": 39395,
            "behaviorType": 4,
            "searchType": "5",
            "value": ["37783", "37784"]
        }
    ]
    condition_column = json.dumps(condition_column)
    js = client.task_list(
        project_id=project_id,
        condition_column=condition_column
    )
    print(json.dumps(js, ensure_ascii=False, indent=4))

    return


if __name__ == "__main__":
    # main()
    # main2()
    # main3()
    # main4()
    main5()
