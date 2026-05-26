#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import functools
import logging
import inspect
import time
from typing import Any, Callable, TypeVar, cast

from toolbox.utils.exception import ExpectedError

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger("toolbox")


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
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception as error:
                    # print(f"failed; error type: {type(error)}, error text: {str(error)}")
                    return return_value
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as error:
                    # print(f"failed; error type: {type(error)}, error text: {str(error)}")
                    return return_value
            return sync_wrapper
    return decorator


def when_expected_error(return_value: Any = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except ExpectedError as error:
                    logger.warning(f"ExpectedError failed; message: {error.message}")
                    return return_value
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except ExpectedError as error:
                    logger.warning(f"ExpectedError failed; message: {error.message}")
                    return return_value
            return sync_wrapper
    return decorator

