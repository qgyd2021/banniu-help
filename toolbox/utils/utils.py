#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""调试小工具。"""
from __future__ import annotations

import asyncio
import functools
import inspect
import time
from typing import Any, Callable, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


def print_time_cost(func: F) -> F:
    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_wrapped(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                print(f"[time] {func.__qualname__} {time.perf_counter() - t0:.4f}s")

        return cast(F, _async_wrapped)

    @functools.wraps(func)
    def _sync_wrapped(*args: Any, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            print(f"[time] {func.__qualname__} {time.perf_counter() - t0:.4f}s")

    return cast(F, _sync_wrapped)


def when_error(return_value: Any = None) -> Callable:
    """当函数执行出错时，返回指定的值（默认 None）"""
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception:
                    return return_value
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    return return_value
            return sync_wrapper
    return decorator

