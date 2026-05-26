#!/usr/bin/python3
# -*- coding: utf-8 -*-
import functools
import json
import logging
import time
import traceback

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from toolbox.porter.tasks.post_review_submit_service_task.exception import ExpectedError

logger = logging.getLogger("toolbox")


def common_route_wrap(f):
    @functools.wraps(f)
    def inner(*args, **kwargs):
        begin = time.time()
        try:
            result = f(*args, **kwargs)
            response = {
                "status_code": 60200,
                "result": result,
                "message": "success",
                "detail": None,
            }
            http_status = 200
        except ExpectedError as e:
            response = {
                "status_code": e.status_code,
                "result": None,
                "message": e.message,
                "detail": e.detail,
                "traceback": e.traceback,
            }
            http_status = 400
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else json.dumps(e.detail, ensure_ascii=False)
            http_status = e.status_code or 500
            response = {
                "status_code": 60000 + http_status,
                "result": None,
                "message": detail or f"HTTP {http_status}",
                "detail": None,
                "traceback": "",
            }
        except Exception as e:
            response = {
                "status_code": 60500,
                "result": None,
                "message": f"{type(e).__name__}: {e}",
                "detail": None,
                "traceback": traceback.format_exc(),
            }
            http_status = 500
        response["time_cost"] = round(time.time() - begin, 4)
        return JSONResponse(content=response, status_code=http_status)

    return inner


def async_common_route_wrap(f):
    @functools.wraps(f)
    async def inner(*args, **kwargs):
        begin = time.time()
        try:
            result = await f(*args, **kwargs)
            response = {
                "status_code": 60200,
                "result": result,
                "message": "success",
                "detail": None,
            }
            http_status = 200
        except ExpectedError as e:
            response = {
                "status_code": e.status_code,
                "result": None,
                "message": e.message,
                "detail": e.detail,
                "traceback": e.traceback,
            }
            http_status = 400
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else json.dumps(e.detail, ensure_ascii=False)
            http_status = e.status_code or 500
            response = {
                "status_code": 60000 + http_status,
                "result": None,
                "message": detail or f"HTTP {http_status}",
                "detail": None,
                "traceback": "",
            }
        except Exception as e:
            response = {
                "status_code": 60500,
                "result": None,
                "message": f"{type(e).__name__}: {e}",
                "detail": None,
                "traceback": traceback.format_exc(),
            }
            http_status = 500
        response["time_cost"] = round(time.time() - begin, 4)
        return JSONResponse(content=response, status_code=http_status)
    return inner


if __name__ == "__main__":
    pass
