#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import time

from toolbox.dingtalk.restful.dingtalk_client import DingTalkRestfulClient


class DingTalkClient(DingTalkRestfulClient):
    def __init__(self,
                 oapi_host: str,
                 api_host: str,
                 client_id: str,
                 client_secret: str,
                 ):
        super(DingTalkClient, self).__init__(oapi_host, api_host, client_id, client_secret)
        self._access_token: str = None
        self._access_token_expires_in: int = None
        self._access_token_expires_ts: int = None

    @property
    def access_token(self):
        if self._access_token is None or time.time() > self._access_token_expires_ts:
            js = self.get_access_token()
            access_token = js["access_token"]
            expires_in = js["expires_in"]
            self._access_token = access_token
            self._access_token_expires_in = expires_in
            self._access_token_expires_ts = time.time() + expires_in - 10
        return self._access_token

    def get_unionid_by_user_id(self, user_id: str):
        js = self.post_unionid(user_id=user_id, access_token=self.access_token)
        union_id = js["result"]["unionid"]
        return union_id


def main():
    from project_settings import environment, project_path

    client_id = environment.get("MC_DT_CLIENT_ID")
    client_secret = environment.get("MC_DT_CLIENT_SECRET")
    user_id = "641333949"   #田兴
    # user_id = "642103274" #丁毅

    client = DingTalkClient(
        oapi_host="https://oapi.dingtalk.com",
        api_host="https://api.dingtalk.com",
        client_id=client_id,
        client_secret=client_secret,
    )
    union_id = client.get_unionid_by_user_id(user_id=user_id)
    print(f"union_id: {union_id}")
    return


if __name__ == "__main__":
    main()
