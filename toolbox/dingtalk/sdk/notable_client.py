#!/usr/bin/python3
# -*- coding: utf-8 -*-
import cacheout

from toolbox.dingtalk.restful.notable_client import NotableRestfulClient
from toolbox.dingtalk.sdk.dingtalk_client import DingTalkClient


class NotableClient(DingTalkClient, NotableRestfulClient):
    def __init__(self,
                 oapi_host: str,
                 api_host: str,
                 client_id: str,
                 client_secret: str,
                 user_id: str,
                 ):
        super(NotableClient, self).__init__(oapi_host, api_host, client_id, client_secret)
        self.user_id = user_id
        self._union_id = None

    @property
    def union_id(self):
        if self._union_id is None:
            self._union_id = self.get_unionid_by_user_id(self.user_id)
        return self._union_id

    @cacheout.memoize(ttl=3600*24)
    def get_notable_sheet_id_by_name(self, notable_id: str, sheet_name: str):
        js = self.get_notable_sheets(
            notable_id=notable_id,
            union_id=self.union_id, access_token=self.access_token
        )
        sheets = js["value"]
        result = None
        for sheet in sheets:
            name = sheet["name"]
            sheet_id = sheet["id"]
            if name == sheet_name:
                result = sheet_id
        return result

    def get_notable_records_by_sheet_name(self, notable_id: str, sheet_name: str):
        sheet_id = self.get_notable_sheet_id_by_name(notable_id, sheet_name)
        js = self.get_notable_records_by_sheet_id(
            notable_id, sheet_id, union_id=self.union_id, access_token=self.access_token
        )
        records = js["records"]
        return records

    def update_notable_records_by_sheet_name(self, notable_id: str, sheet_name: str, records: list):
        sheet_id = self.get_notable_sheet_id_by_name(notable_id, sheet_name)
        js = self.put_notable_records_by_sheet_id(
            notable_id, sheet_id, records,
            union_id=self.union_id, access_token=self.access_token
        )
        return js


def main():
    import json
    from project_settings import environment, project_path

    client_id = environment.get("MC_DT_CLIENT_ID")
    client_secret = environment.get("MC_DT_CLIENT_SECRET")
    # user_id = "641333949"   #田兴
    user_id = "642103274" #丁毅
    notable_id = "6LeBq413JAe1RxDeHBrmZLZzJDOnGvpb"
    sheet_name = "UGC内容登记"

    client = NotableClient(
        oapi_host="https://oapi.dingtalk.com",
        api_host="https://api.dingtalk.com",
        client_id=client_id,
        client_secret=client_secret,
        user_id=user_id,
    )
    records = client.get_notable_records_by_sheet_name(notable_id=notable_id, sheet_name=sheet_name)
    print(f"records: {json.dumps(records, ensure_ascii=False, indent=2)}")

    records = [
        {
            "id": "LLHjQWHM9N",
            "fields": {
                "收件人姓名": "测试1",
                # "收件人姓名": "测试2",
            }
        }
    ]
    js = client.update_notable_records_by_sheet_name(notable_id=notable_id, sheet_name=sheet_name, records=records)
    print(json.dumps(js, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    main()
