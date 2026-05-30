#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
班牛 column.list 网关 JSON 的解析与列字段映射。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("toolbox")

# column_id 与 value_id 串联为查找键时的分隔符（避免与数字 id 拼接产生歧义）
_COLUMN_VALUE_LOOKUP_SEP = "\x1f"


def _column_value_lookup_key(column_id: str, value_id: str) -> str:
    return f"{column_id}{_COLUMN_VALUE_LOOKUP_SEP}{value_id}"


class ColumnListForm(object):
    def __init__(self, rows: List[dict]) -> None:
        self._rows = [r for r in (rows or []) if isinstance(r, dict)]
        self._id_to_name: Optional[Dict[str, Optional[str]]] = None
        self._name_to_id: Optional[Dict[str, str]] = None
        self._id_to_options: Optional[Dict[str, List[dict]]] = None
        # key = column_id + sep + value_id（均已 strip），value = 选项展示文案（title）
        self._column_value_lookup: Optional[Dict[str, Optional[str]]] = None

    def __repr__(self) -> str:
        n = len(self._rows)
        parts: List[str] = []
        for row in self._rows[:5]:
            cid = row.get("column_id")
            name = row.get("name")
            parts.append(f"{cid}:{name!r}")
        head = ", ".join(parts) if parts else ""
        if n > 5:
            head = f"{head}, ..." if head else "..."
        inner = head or "empty"
        return f"ColumnListForm(rows={n}, preview=[{inner}])"

    @property
    def rows(self) -> List[dict]:
        return self._rows

    @property
    def id_to_name(self) -> Dict[str, Optional[str]]:
        if self._id_to_name is None:
            self._id_to_name = self._build_id_to_name()
        return self._id_to_name

    @property
    def name_to_id(self) -> Dict[str, str]:
        """列展示名（去首尾空白）-> ``column_id`` 字符串；同名列仅保留首次。"""
        if self._name_to_id is None:
            self._name_to_id = self._build_name_to_id()
        return self._name_to_id

    @property
    def id_to_options(self) -> Dict[str, List[dict]]:
        """``column_id`` -> ``options``（仅 dict 元素）列表。"""
        if self._id_to_options is None:
            self._id_to_options = self._build_id_to_options()
        return self._id_to_options

    @property
    def column_value_lookup(self) -> Dict[str, Optional[str]]:
        """``column_id + 分隔符 + value_id`` -> 选项 ``title``；仅含带 ``options`` 的列。"""
        if self._column_value_lookup is None:
            self._column_value_lookup = self._build_column_value_lookup()
        return self._column_value_lookup

    def _build_column_value_lookup(self) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {}
        for row in self._rows:
            cid = row.get("column_id")
            if cid is None:
                continue
            ckey = str(cid).strip()
            if not ckey:
                continue
            options = row.get("options")
            if not isinstance(options, list):
                continue
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                oid = opt.get("id")
                if oid is None:
                    continue
                vkey = str(oid).strip()
                if not vkey:
                    continue
                lk = _column_value_lookup_key(ckey, vkey)
                title = opt.get("title")
                if isinstance(title, str):
                    val: Optional[str] = title
                elif title is not None:
                    val = str(title)
                else:
                    val = None
                if lk in out:
                    logger.warning(
                        "ColumnListForm 选项键重复，保留首次 lookup_key=%r (忽略 title=%r)",
                        lk,
                        val,
                    )
                    continue
                out[lk] = val
        return out

    def _build_id_to_options(self) -> Dict[str, List[dict]]:
        out: Dict[str, List[dict]] = {}
        for row in self._rows:
            cid = row.get("column_id")
            if cid is None:
                continue
            ckey = str(cid).strip()
            if not ckey:
                continue
            options = row.get("options")
            if not isinstance(options, list):
                continue
            out[ckey] = [opt for opt in options if isinstance(opt, dict)]
        return out

    def _build_id_to_name(self) -> Dict[str, Optional[str]]:
        m: Dict[str, Optional[str]] = {}
        for row in self._rows:
            cid = row.get("column_id")
            if cid is None:
                continue
            key = str(cid).strip()
            if not key:
                continue
            name = row.get("name")
            if isinstance(name, str):
                m[key] = name
            elif name is not None:
                m[key] = str(name)
            else:
                m[key] = None
        return m

    def _build_name_to_id(self) -> Dict[str, str]:
        m: Dict[str, str] = {
            "taskId(int)": "0",
            "taskId(str)": "-1"
        }
        for row in self._rows:
            name = row.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            key = name.strip()
            cid = row.get("column_id")
            if cid is None or str(cid).strip() == "":
                continue
            cid_s = str(cid).strip()
            if key in m:
                logger.warning(
                    "ColumnListForm 列名重复，保留首次 column_id=%r (忽略 column_id=%r, name=%r)",
                    m[key], cid_s, key,
                )
                continue
            m[key] = cid_s
        return m

    def get_column_id_by_name(self, column_name: Any) -> Optional[str]:
        if column_name is None:
            return None
        key = str(column_name).strip()
        if not key:
            return None
        return self.name_to_id.get(key)

    def get_column_name_by_id(self, column_id: Any) -> Optional[str]:
        """
        根据列 ``column_id``（班牛列 id，多为数字或字符串数字）返回列展示名 ``name``。
        无此列时返回 ``None``；有列时返回原始 ``name``（可能为 ``None``、空字符串或非空字符串）。
        """
        if column_id is None:
            return None
        key = str(column_id).strip()
        if not key:
            return None
        if key not in self.id_to_name:
            return None
        if key == "0":
            return "taskId(int)"
        if key == "-1":
            return "taskId(str)"
        return self.id_to_name[key]

    def get_column_options_by_id(self, column_id: Any) -> List[dict]:
        """
        根据 ``column_id`` 返回该列的 ``options`` 列表（仅保留 dict 元素）。
        无此列或该列无 options 时返回空列表。
        """
        if column_id is None:
            return None
        ckey = str(column_id).strip()
        if not ckey:
            return None
        return self.id_to_options.get(ckey)

    def get_column_value_by_id(self, column_id: Any, value_id: Any) -> Optional[str]:
        """
        根据 ``column_id`` 与选项值 ``value_id``（班牛表里存的常为选项 id），
        返回 ``options`` 里对应的展示文案（一般为 ``title``）。

        内部使用一次性构建的 ``column_value_lookup`` 字典（键为 column_id 与 value_id 串联），
        查询为 O(1)。无匹配时返回 ``None``。
        """
        if column_id is None or value_id is None:
            return None
        ckey = str(column_id).strip()
        vkey = str(value_id).strip()
        if not ckey or not vkey:
            return None
        lk = _column_value_lookup_key(ckey, vkey)
        return self.column_value_lookup.get(lk)

    def map_option_value_to_id(self, column_id: Any, value: Any) -> Any:
        if column_id is None:
            return value
        ckey = str(column_id).strip()
        if not ckey:
            return value
        options = self.get_column_options_by_id(ckey) or []
        if not options:
            return value

        title_to_id: Dict[str, str] = {}
        for opt in options:
            if not isinstance(opt, dict):
                continue
            title = str(opt.get("title") or "").strip()
            oid = str(opt.get("id") or "").strip()
            if title and oid and title not in title_to_id:
                title_to_id[title] = oid

        def _map_one(token: str) -> str:
            s = str(token).strip()
            if not s:
                return ""
            return title_to_id.get(s, s)

        if isinstance(value, str) and "," in value:
            parts = [_map_one(p) for p in value.split(",")]
            parts = [p for p in parts if p != ""]
            return ",".join(parts)
        if isinstance(value, str):
            return _map_one(value)
        return value


def get_args():
    parser = argparse.ArgumentParser(description="拉取 column.list 并构建 ColumnListForm")
    parser.add_argument(
        "--project_id",
        default="39369",
        type=str,
    )
    args = parser.parse_args()
    return args


async def main() -> None:
    args = get_args()

    from project_settings import environment
    from toolbox.banniu.restful.banniu_client import AsyncBanNiuRestfulClient

    client = AsyncBanNiuRestfulClient(
        app_key=environment.get("BANNIU_APP_KEY"),
        app_secret=environment.get("BANNIU_APP_SECRET"),
        access_token=environment.get("BANNIU_ACCESS_TOKEN"),
    )
    js = await client.column_list(project_id=str(args.project_id))
    rows = js["response"]["map"]["result"]
    form = ColumnListForm(rows)
    print(json.dumps(form.rows, ensure_ascii=False, indent=4))
    print(form)
    column_name = form.get_column_name_by_id(column_id="37970")
    print(column_name)
    column_id = form.get_column_id_by_name(column_name="同步时间")
    print(column_id)
    column_value = form.get_column_value_by_id(column_id="37970", value_id="37971")
    print(column_value)
    column_options = form.get_column_options_by_id(column_id="38876")
    print(column_options)


if __name__ == "__main__":
    asyncio.run(main())
