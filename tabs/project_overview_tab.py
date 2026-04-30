#!/usr/bin/python3
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Dict, List, Tuple

import gradio as gr

from project_settings import project_path


def _resolve_dir(raw_dir: str) -> Path:
    p = Path(str(raw_dir or "").strip() or "temp")
    if not p.is_absolute():
        p = (project_path / p).resolve()
    return p


def list_projects(base_dir: str) -> Tuple[gr.Dropdown, str]:
    root = _resolve_dir(base_dir)
    if not root.exists() or not root.is_dir():
        return gr.Dropdown(choices=[], value=None), f"目录不存在：{root.as_posix()}"
    choices = sorted([p.name for p in root.iterdir() if p.is_dir()])
    default_value = choices[0] if choices else None
    msg = f"项目数：{len(choices)}（目录：{root.as_posix()}）"
    return gr.Dropdown(choices=choices, value=default_value), msg


def _count_files_recursive(folder: Path) -> int:
    return sum(1 for p in folder.rglob("*") if p.is_file())


def query_project(base_dir: str, project_name: str) -> Tuple[str, List[List[object]]]:
    root = _resolve_dir(base_dir)
    if not project_name:
        return "请先选择项目。", []
    project_dir = root / project_name
    if not project_dir.exists() or not project_dir.is_dir():
        return f"项目目录不存在：{project_dir.as_posix()}", []

    step_dirs = sorted([p for p in project_dir.iterdir() if p.is_dir() and p.name.startswith("step_")], key=lambda x: x.name)
    rows: List[List[object]] = []
    total_files = 0
    for step_dir in step_dirs:
        file_count = _count_files_recursive(step_dir)
        total_files += file_count
        rows.append([step_dir.name, file_count, step_dir.as_posix()])

    summary = (
        f"项目：`{project_name}`\n\n"
        f"- 项目路径：`{project_dir.as_posix()}`\n"
        f"- step 目录数：`{len(step_dirs)}`\n"
        f"- step 内文件总数：`{total_files}`"
    )
    return summary, rows


def get_project_overview_tab():
    with gr.TabItem("project_overview"):
        gr.Markdown("### 项目概览\n从指定目录扫描项目，查询每个 step 的文件数量。")
        with gr.Row():
            base_dir_text = gr.Textbox(label="base_dir", value="temp")
            refresh_btn = gr.Button("refresh projects")
        project_dropdown = gr.Dropdown(label="project", choices=[])
        query_btn = gr.Button("query")
        status_md = gr.Markdown(value="点击 `refresh projects` 加载项目列表。")
        summary_md = gr.Markdown()
        step_df = gr.Dataframe(
            headers=["step", "file_count", "path"],
            datatype=["str", "number", "str"],
            interactive=False,
            wrap=True,
            label="step stats",
        )

        refresh_btn.click(
            fn=list_projects,
            inputs=[base_dir_text],
            outputs=[project_dropdown, status_md],
        )
        query_btn.click(
            fn=query_project,
            inputs=[base_dir_text, project_dropdown],
            outputs=[summary_md, step_df],
        )

    return locals()


if __name__ == "__main__":
    pass
