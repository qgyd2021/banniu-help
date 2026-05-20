#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json

import requests


class DingTalkRestfulClient(object):
    def __init__(self,
                 oapi_host: str,
                 api_host: str,
                 client_id: str,
                 client_secret: str,
                 ):
        self.oapi_host = oapi_host
        self.api_host = api_host
        self.client_id = client_id
        self.client_secret = client_secret

    def get_access_token(self):
        url = f"{self.oapi_host}/gettoken"
        params = {
            "appkey": self.client_id,
            "appsecret": self.client_secret,
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js

    def post_unionid(self, user_id: str, access_token: str):
        url = f"{self.oapi_host}/topapi/v2/user/get"
        headers = {
            "Content-Type": "application/json",
        }
        params = {
            "access_token": access_token,
        }
        data = {
            "userid": user_id,
        }
        response = requests.post(url, headers=headers, params=params, data=json.dumps(data))
        if response.status_code != 200:
            raise AssertionError(f"request failed; status code: {response.status_code}, text: {response.text}")
        js = response.json()
        return js


if __name__ == "__main__":
    pass
