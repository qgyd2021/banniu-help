#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path
from typing import Any, List, Tuple

import gradio as gr

from project_settings import project_path, temp_directory


def when_click_query_button(base_dir: str) -> List[List[Any]]:
    base_dir: Path = project_path / base_dir
    step_dirs = sorted([p for p in base_dir.iterdir() if p.is_dir() and p.name.startswith("step_")], key=lambda x: x.name)

    rows_server = list()
    for fp in sorted(base_dir.rglob("server.json")):
        try:
            js = json.loads(fp.read_text(encoding="utf-8"))
        except json.decoder.JSONDecodeError:
            continue
        if not isinstance(js, dict):
            continue
        name = str(js.get("service_name") or "").strip()
        desc = str(js.get("description") or "").strip()
        path = str(js.get("service_access_path") or "").strip()
        if not (name or desc or path):
            continue
        rows_server.append([name, desc, path])

    rows_steps: List[List[Any]] = []
    for step_dir in step_dirs:
        file_count = sum(1 for p in step_dir.rglob("*") if p.is_file())
        rows_steps.append([step_dir.name, file_count, step_dir.as_posix()])
    return rows_server, rows_steps


def get_project_overview_tab():
    with gr.TabItem("project_overview"):
        gr.Markdown("### 项目概览\n从指定目录扫描项目，查询每个 step 的文件数量。")

        base_dir_choices = [d.relative_to(project_path).as_posix() for d in temp_directory.glob("banniu_*")]
        base_dir = gr.Dropdown(choices=base_dir_choices, value=base_dir_choices[0], label="base_dir")
        query_button = gr.Button(value="query", variant="primary")

        df_server = gr.Dataframe(
            headers=["name", "desc", "url"],
            datatype=["str", "str", "str"],
            interactive=False,
            wrap=True,
            label="server",
            max_height=500
        )
        df_steps = gr.Dataframe(
            headers=["step", "file_count", "path"],
            datatype=["str", "number", "str"],
            interactive=False,
            wrap=True,
            label="step stats",
            max_height=1000
        )
        query_button.click(
            fn=when_click_query_button,
            inputs=[base_dir],
            outputs=[df_server, df_steps],
        )
    return locals()


if __name__ == "__main__":
    pass
