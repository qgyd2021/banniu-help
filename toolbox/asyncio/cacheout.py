#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import time
from functools import wraps

import time
import hashlib
import pickle
import asyncio
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import OrderedDict


@dataclass
class CacheEntry:
    expire_time: float
    result: Any
    access_time: float


def async_cache_decorator(
        max_age: int = 10,
        max_size: Optional[int] = 100,
        ignore_kwargs: Optional[list] = None
):
    """
    高级缓存装饰器

    Args:
        max_age: 缓存最大年龄（秒）
        max_size: 缓存最大大小（None表示无限制）
        ignore_kwargs: 忽略的kwargs参数名列表
    """
    ignore_kwargs = ignore_kwargs or []

    def decorator(func: Callable):
        cache: Dict[str, CacheEntry] = {}
        access_order = OrderedDict()  # 用于LRU淘汰

        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 清理过期的缓存
            _clean_expired_cache()

            # 生成缓存键（忽略指定的kwargs）
            filtered_kwargs = {k: v for k, v in kwargs.items() if k not in ignore_kwargs}
            cache_key = _generate_cache_key(args, filtered_kwargs)
            current_time = time.time()

            # 检查缓存
            if cache_key in cache:
                entry = cache[cache_key]
                if current_time < entry.expire_time:
                    # 更新访问时间和LRU顺序
                    entry.access_time = current_time
                    access_order.move_to_end(cache_key)
                    return entry.result
                else:
                    # 缓存过期
                    _remove_from_cache(cache_key)

            # 调用原函数
            result = await func(*args, **kwargs)

            # 检查缓存大小并可能淘汰
            if max_size and len(cache) >= max_size:
                # 移除最久未使用的缓存
                oldest_key = next(iter(access_order))
                _remove_from_cache(oldest_key)

            # 添加新缓存
            cache[cache_key] = CacheEntry(
                expire_time=current_time + max_age,
                result=result,
                access_time=current_time
            )
            access_order[cache_key] = True

            return result

        def _clean_expired_cache():
            """清理过期缓存"""
            current_time = time.time()
            expired_keys = [
                key for key, entry in cache.items()
                if current_time >= entry.expire_time
            ]
            for key in expired_keys:
                _remove_from_cache(key)

        def _remove_from_cache(cache_key: str):
            """从缓存中移除指定键"""
            if cache_key in cache:
                del cache[cache_key]
            if cache_key in access_order:
                del access_order[cache_key]

        # 缓存管理方法
        def clear_cache():
            """清空所有缓存"""
            cache.clear()
            access_order.clear()

        def remove_from_cache(*args, **kwargs):
            """移除特定参数的缓存"""
            filtered_kwargs = {k: v for k, v in kwargs.items() if k not in ignore_kwargs}
            cache_key = _generate_cache_key(args, filtered_kwargs)
            if cache_key in cache:
                _remove_from_cache(cache_key)
                return True
            return False

        def get_cache_info() -> Dict[str, Any]:
            """获取缓存统计信息"""
            current_time = time.time()
            valid_entries = sum(
                1 for entry in cache.values()
                if current_time < entry.expire_time
            )
            return {
                'total_entries': len(cache),
                'valid_entries': valid_entries,
                'max_size': max_size,
                'max_age': max_age,
                'cache_keys': list(cache.keys())
            }

        def get_cached_result(*args, **kwargs):
            """获取缓存结果（如果存在且未过期）"""
            filtered_kwargs = {k: v for k, v in kwargs.items() if k not in ignore_kwargs}
            cache_key = _generate_cache_key(args, filtered_kwargs)
            current_time = time.time()

            if cache_key in cache:
                entry = cache[cache_key]
                if current_time < entry.expire_time:
                    return entry.result
            return None

        # 附加方法
        wrapper.clear_cache = clear_cache
        wrapper.remove_from_cache = remove_from_cache
        wrapper.get_cache_info = get_cache_info
        wrapper.get_cached_result = get_cached_result

        return wrapper

    return decorator


def _generate_cache_key(args: tuple, kwargs: dict) -> str:
    """生成缓存键"""
    try:
        # 尝试使用更高效的序列化
        key_data = pickle.dumps((args, sorted(kwargs.items())))
        return hashlib.sha256(key_data).hexdigest()
    except (TypeError, pickle.PickleError):
        # 如果无法序列化，使用字符串表示
        args_str = str(args)
        kwargs_str = str(sorted(kwargs.items()))
        return hashlib.sha256(f"{args_str}:{kwargs_str}".encode()).hexdigest()


@async_cache_decorator(10)
async def call_api():
    await asyncio.sleep(1)
    return {"data": f"API响应时间: {time.time()}", "status": "success"}


async def main():
    # 第一次调用 - 实际调用API
    result1 = await call_api()
    print("第一次结果:", result1)

    # 立即再次调用 - 返回缓存结果
    result2 = await call_api()
    print("第二次结果:", result2)

    # 等待5秒后调用 - 返回缓存结果
    await asyncio.sleep(5)
    result3 = await call_api()
    print("第三次结果:", result3)

    # 等待11秒后调用 - 重新调用API
    await asyncio.sleep(6)  # 总共等待11秒
    result4 = await call_api()
    print("第四次结果:", result4)


if __name__ == "__main__":
    asyncio.run(main())
