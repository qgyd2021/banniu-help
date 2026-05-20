#!/usr/bin/python3
# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List, Optional

import cacheout

from toolbox.banniu.restful.banniu_client import AsyncBanNiuRestfulClient, BanNiuRestfulClient
from toolbox.banniu.form.column_list import ColumnListForm


class BanNiuClient(BanNiuRestfulClient):
    @cacheout.memoize(ttl=3600 * 1)
    def build_form(self, project_id: str) -> ColumnListForm:
        js = self.column_list(project_id=project_id)
        rows = js["response"]["map"]["result"]
        # print(json.dumps(rows, ensure_ascii=False, indent=2))
        form = ColumnListForm(rows)
        return form

    def task_create_pretty(self, project_id: str, app_id: str, user_id: str, named_fields: dict):
        form = self.build_form(project_id)

        contents = {}
        for k, v in named_fields.items():
            cid: str = form.get_column_id_by_name(k)
            v = form.map_option_value_to_id(cid, v)
            contents[cid] = v

        return self.task_create(
            project_id=str(project_id),
            app_id=str(app_id),
            user_id=str(user_id),
            contents=contents,
        )

    @staticmethod
    def get_behavior_type_by_name(name: str):
        behavior_type_map = {
            "文本类型": 1,
            "数值类型": 2,
            "单选": 3,
            "下拉": 4,
            "多选": 5,
            "联动": 6,
            "日期时间": 7,
            "日期区间": 8,
            "评分": 9,
            "附件": 10,
            "富文本": 11,
            "标签": 12,
        }
        result = behavior_type_map[name]
        return result

    @staticmethod
    def get_search_type_by_name(name: str):
        search_type_map = {
            "等于": "1",
            "不等于": "2",
            "包含": "3",
            "不包含": "4",
            "包含任一项": "5",
        }
        result = search_type_map[name]
        return result

    def task_list_pretty(
        self,
        project_id: str,
        page_size: int = 10,
        page_num: int = 1,
        star_created: str = None,
        end_created: str = None,
        task_status: int = None,
        condition_column: Optional[List[Dict[str, Any]]] = None,
    ):
        if condition_column is not None:
            form = self.build_form(project_id)
            condition_column_ = list()
            for item in condition_column:
                field = item["字段"]
                behavior_type = item["字段类型"]
                search_type = item["搜索类型"]
                value = item["搜索内容"]
                field = form.get_column_id_by_name(field)
                field = int(field)
                behavior_type = self.get_behavior_type_by_name(behavior_type)
                search_type = self.get_search_type_by_name(search_type)
                item_ = {
                    "id": field,
                    "behaviorType": behavior_type,
                    "searchType": search_type,
                    "value": value
                }
                condition_column_.append(item_)
            condition_column = json.dumps(condition_column_, ensure_ascii=False)

        return self.task_list(
            project_id=project_id,
            page_size=page_size,
            page_num=page_num,
            star_created=star_created,
            end_created=end_created,
            task_status=task_status,
            condition_column=condition_column,
        )


class AsyncBanNiuClient(AsyncBanNiuRestfulClient):
    """
    ``BanNiuClient`` 的异步版本：在 ``AsyncBanNiuRestfulClient`` 之上提供
    ``task_create_pretty`` / ``task_list_pretty`` 等封装。
    """

    @cacheout.memoize(ttl=3600 * 1)
    async def build_form(self, project_id: str) -> ColumnListForm:
        js = await self.column_list(project_id=project_id)
        rows = js["response"]["map"]["result"]
        # print(json.dumps(rows, ensure_ascii=False, indent=2))
        form = ColumnListForm(rows)
        return form

    async def task_create_pretty(self, project_id: str, app_id: str, user_id: str, named_fields: dict):
        form = await self.build_form(project_id)

        contents = {}
        for k, v in named_fields.items():
            cid: str = form.get_column_id_by_name(k)
            v = form.map_option_value_to_id(cid, v)
            contents[cid] = v

        return await self.task_create(
            project_id=str(project_id),
            app_id=str(app_id),
            user_id=str(user_id),
            contents=contents,
        )

    async def task_list_pretty(
        self,
        project_id: str,
        page_size: int = 10,
        page_num: int = 1,
        star_created: str = None,
        end_created: str = None,
        task_status: int = None,
        condition_column: Optional[List[Dict[str, Any]]] = None,
    ):
        if condition_column is not None:
            form = await self.build_form(project_id)
            condition_column_ = list()
            for item in condition_column:
                field = item["字段"]
                behavior_type = item["字段类型"]
                search_type = item["搜索类型"]
                value = item["搜索内容"]
                field = form.get_column_id_by_name(field)
                field = int(field)
                behavior_type = BanNiuClient.get_behavior_type_by_name(behavior_type)
                search_type = BanNiuClient.get_search_type_by_name(search_type)
                value = form.map_option_value_to_id(column_id=field, value=value)
                value = int(value)
                try:
                    value = int(value)
                except ValueError:
                    value = value

                item_ = {
                    "id": field,
                    "behaviorType": behavior_type,
                    "searchType": search_type,
                    "value": value,
                }
                condition_column_.append(item_)
            condition_column = json.dumps(condition_column_, ensure_ascii=False)

        return await self.task_list(
            project_id=project_id,
            page_size=page_size,
            page_num=page_num,
            star_created=star_created,
            end_created=end_created,
            task_status=task_status,
            condition_column=condition_column,
        )


def main():
    import random
    from project_settings import environment

    project_id = "37728"
    app_id = "41339"
    user_id = "000000000"

    client = BanNiuClient(
        app_key=environment.get("BANNIU_APP_KEY"),
        app_secret=environment.get("BANNIU_APP_SECRET"),
        access_token=environment.get("BANNIU_ACCESS_TOKEN"),
    )

    example_named = {
        "产品型号": "Ace68V2",
        "购买渠道": "抖音",
        "发布渠道": "抖音",
        "晒单内容链接": f"[测试]晒单内容链接{random.randint(1, 100000000)}",
        "社媒平台主页截图": json.dumps(["WxU5cVKahMjzONrUONr6Gg=="]),
        "收货人（用于查询）": "田兴",
        "手机号码（用于填写/查询）": "13530604154",
        "收货地址信息": "田兴,13530604154,广东省,深圳市,龙岗区,横岗街道,华侨新村",
    }

    resp = client.task_create_pretty(
        project_id=project_id,
        app_id=app_id,
        user_id=user_id,
        named_fields=example_named,
    )
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    return


def main2():
    from project_settings import environment

    APP_KEY = environment.get("BANNIU_APP_KEY")
    APP_SECRET = environment.get("BANNIU_APP_SECRET")
    ACCESS_TOKEN = environment.get("BANNIU_ACCESS_TOKEN")

    project_id = "37728"

    client = BanNiuClient(app_key=APP_KEY, app_secret=APP_SECRET, access_token=ACCESS_TOKEN)

    condition_column = [
        {
            "字段": "收货人（用于查询）",
            "字段类型": "文本类型",
            "搜索类型": "等于",
            "搜索内容": "曹付庚",
        },
        {
            "字段": "手机号码（用于填写/查询）",
            "字段类型": "文本类型",
            "搜索类型": "等于",
            "搜索内容": "13675639166",
        },
    ]
    js = client.task_list_pretty(
        project_id=project_id,
        condition_column=condition_column,
    )
    print(json.dumps(js, ensure_ascii=False, indent=4))

    return


def main3():
    from project_settings import environment

    APP_KEY = environment.get("BANNIU_APP_KEY")
    APP_SECRET = environment.get("BANNIU_APP_SECRET")
    ACCESS_TOKEN = environment.get("BANNIU_ACCESS_TOKEN")

    now_dt = datetime.now()
    one_year_ago_dt = now_dt - timedelta(days=1)

    project_id = "39369"

    client = BanNiuClient(app_key=APP_KEY, app_secret=APP_SECRET, access_token=ACCESS_TOKEN)

    condition_column = [
        {
            "字段": "审核状态",
            "字段类型": "单选",
            "搜索类型": "等于",
            "搜索内容": "待审核",
        }
    ]
    js = client.task_list_pretty(
        project_id=project_id,
        # star_created=one_year_ago_dt.strftime("%Y-%m-%d %H:%M:%S"),
        # end_created=now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        condition_column=condition_column,
    )
    print(json.dumps(js, ensure_ascii=False, indent=4))

    return


if __name__ == "__main__":
    # main()
    # main2()
    main3()
