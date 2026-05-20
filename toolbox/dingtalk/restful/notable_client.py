#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json

import requests

from toolbox.dingtalk.restful.dingtalk_client import DingTalkRestfulClient


class NotableRestfulClient(DingTalkRestfulClient):
    def get_notable_sheets(self, notable_id: str, union_id: str, access_token: str):
        url = f"{self.api_host}/v1.0/notable/bases/{notable_id}/sheets"
        headers = {
            "x-acs-dingtalk-access-token": access_token,
            "Content-Type": "application/json",
        }
        params = {
            "operatorId": union_id,
        }
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def get_notable_records_by_sheet_id(self, notable_id: str, sheet_id: str, union_id: str, access_token: str):
        url = f"{self.api_host}/v1.0/notable/bases/{notable_id}/sheets/{sheet_id}/records"
        headers = {
            "x-acs-dingtalk-access-token": access_token,
            "Content-Type": "application/json",
        }
        params = {
            "operatorId": union_id,
        }
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def put_notable_records_by_sheet_id(self, notable_id: str, sheet_id: str, records: dict, union_id: str, access_token: str):
        """
        https://open.dingtalk.com/document/development/api-noatable-updaterecords
        """
        url = f"{self.api_host}/v1.0/notable/bases/{notable_id}/sheets/{sheet_id}/records"
        headers = {
            "x-acs-dingtalk-access-token": access_token,
            "Content-Type": "application/json",
        }
        params = {
            "operatorId": union_id,
        }
        data = {
            "records": records
        }
        response = requests.put(url, headers=headers, params=params, data=json.dumps(data))
        if response.status_code != 200:
            raise AssertionError(f"request failed; status code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js


def main():
    from project_settings import environment, project_path

    client_id = environment.get("MC_DT_CLIENT_ID")
    client_secret = environment.get("MC_DT_CLIENT_SECRET")
    user_id = "641333949"   #田兴
    # user_id = "642103274" #丁毅
    notable_id = "6LeBq413JAe1RxDeHBrmZLZzJDOnGvpb"

    client = NotableRestfulClient(
        oapi_host="https://oapi.dingtalk.com",
        api_host="https://api.dingtalk.com",
        client_id=client_id,
        client_secret=client_secret,
    )
    js = client.get_access_token()
    access_token = js["access_token"]
    print(f"access_token: {access_token}")
    js = client.post_unionid(user_id, access_token)
    print(json.dumps(js, ensure_ascii=False, indent=2))
    union_id = js["result"]["unionid"]
    print(f"union_id: {union_id}")

    js = client.get_notable_sheets(notable_id, union_id, access_token)
    sheet_id = js["value"][0]["id"]
    print(f"sheet_id: {sheet_id}")

    js = client.get_notable_records_by_sheet_id(notable_id, sheet_id, union_id, access_token)
    print(json.dumps(js, ensure_ascii=False, indent=2))

    records = [
        {
            "id": "LLHjQWHM9N",
            "fields": {
                "收件人姓名": "测试1",
                # "收件人姓名": "测试2",
            }
        }
    ]
    js = client.put_notable_records_by_sheet_id(notable_id, sheet_id, records, union_id, access_token)
    print(json.dumps(js, ensure_ascii=False, indent=2))

    return


if __name__ == "__main__":
    main()
