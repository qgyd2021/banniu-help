#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
班牛 task.list 网关 JSON 的解析，及结合 ColumnListForm 的表头转换。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from typing import Dict, List, Optional

from toolbox.banniu.form.column_list import ColumnListForm


class TaskListForm(object):
    """
    封装 task.list 单次响应 ``js``（一页），提供原始行列表及结合列定义的转换。

    典型用法::

        tasks = TaskListForm(task_list_js)
        cols = ColumnListForm(column_list_js)
        named_rows = tasks.convert_all_rows(cols)
    """

    def __init__(self, raw_rows: Optional[List[dict]] = None) -> None:
        self._raw_rows = [r for r in (raw_rows or []) if isinstance(r, dict)]

    def __repr__(self) -> str:
        n = len(self._raw_rows)
        parts: List[str] = []
        for row in self._raw_rows[:5]:
            task_id = self.get_task_id(row)
            if task_id is None:
                parts.append("<no-task-id>")
            else:
                parts.append(str(task_id))
        head = ", ".join(parts) if parts else ""
        if n > 5:
            head = f"{head}, ..." if head else "..."
        inner = head or "empty"
        return f"TaskListForm(rows={n}, task_ids=[{inner}])"

    @property
    def raw_rows(self) -> List[dict]:
        return self._raw_rows

    @staticmethod
    def get_task_id(raw_row: dict) -> Optional[str]:
        if not isinstance(raw_row, dict):
            return None
        for key in ("-1", "0"):
            if key in raw_row and raw_row[key] not in (None, ""):
                return str(raw_row[key])
        return None

    @staticmethod
    def _get_pretty_row(raw_row: dict, column_form: ColumnListForm) -> dict:
        if not isinstance(raw_row, dict):
            return {}
        out: Dict[str, object] = {}
        for key, value in raw_row.items():
            key_s = str(key).strip()
            if key_s == "0":
                out["taskId(int)"] = value
                continue
            if key_s == "-1":
                out["taskId(str)"] = value
                continue

            column_name = column_form.get_column_name_by_id(key_s)
            field_name = column_name if column_name else key_s
            mapped_value = column_form.get_column_value_by_id(key_s, value)
            out[str(field_name)] = mapped_value if mapped_value is not None else value
        return out

    def get_pretty_rows(self, column_form: ColumnListForm) -> List[dict]:
        """
        将 task.list 的原始 rows（列 id 为 key）转换为易读 rows（列名为 key）。
        对 options 列会优先把 value_id 映射成展示值（title）。
        """
        return [self._get_pretty_row(row, column_form) for row in self._raw_rows]


def get_args():
    parser = argparse.ArgumentParser(description="拉取 task.list 并构建 TaskListForm")
    parser.add_argument("--project_id", default="37728", type=str)
    parser.add_argument("--page_size", default=10, type=int)
    parser.add_argument("--page_num", default=1, type=int)
    parser.add_argument("--days", default=1, type=int, help="向前回溯 N 天作为起始时间窗口")
    args = parser.parse_args()
    return args


def main():
    """
    使用班牛 client 拉取 task.list，实例化 TaskListForm，便于本地调试 rows / task_id 提取等。
    运行：python -m toolbox.banniu.form.task_list
    """
    args = get_args()

    from project_settings import environment
    from toolbox.banniu.banniu_client import BanNiuClient

    client = BanNiuClient(
        app_key=environment.get("BANNIU_APP_KEY"),
        app_secret=environment.get("BANNIU_APP_SECRET"),
        access_token=environment.get("BANNIU_ACCESS_TOKEN"),
    )

    now_dt = datetime.now()
    start_dt = now_dt - timedelta(days=max(0, int(args.days)))

    js = client.task_list(
        project_id=str(args.project_id),
        page_size=int(args.page_size),
        page_num=int(args.page_num),
        star_created=start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        end_created=now_dt.strftime("%Y-%m-%d %H:%M:%S"),
    )
    raw_rows = js["response"]["map"]["result"]
    form = TaskListForm(raw_rows=raw_rows)
    print(form)

    column_js = client.column_list(project_id=str(args.project_id))
    column_form = ColumnListForm(rows=column_js["response"]["map"]["result"])
    pretty_rows = form.get_pretty_rows(column_form=column_form)
    print("first_pretty_row:", json.dumps(pretty_rows[0], ensure_ascii=False, indent=4))
    return


if __name__ == "__main__":
    main()
