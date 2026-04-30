#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import asyncio
import logging
from pathlib import Path
import platform
import threading
import time
from typing import List

import gradio as gr

import log
from project_settings import environment, project_path, log_directory, time_zone_info
from toolbox.porter.manager import PorterManager
from tabs.project_overview_tab import get_project_overview_tab
from tabs.shell_tab import get_shell_tab

log.setup_size_rotating(log_directory=log_directory, tz_info=time_zone_info)
logger = logging.getLogger("main")


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--porter_tasks_dir",
        default=(project_path / "porter_tasks").as_posix(),
        type=str,
    )
    parser.add_argument(
        "--porter_task_glob",
        default="porter_task_*.json",
        type=str,
    )
    parser.add_argument(
        "--server_port",
        default=environment.get("server_port", 7860),
        type=int,
    )
    parser.add_argument(
        "--server_name",
        default="127.0.0.1" if platform.system() in ("Windows", "Darwin") else "0.0.0.0",
        type=str,
    )
    return parser.parse_args()


def _run_coro_in_new_loop(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(coro)


def _collect_task_files(tasks_dir: Path, task_glob: str) -> List[Path]:
    files = sorted([p for p in tasks_dir.glob(task_glob) if p.is_file()])
    return files


def main():
    args = get_args()
    tasks_dir = Path(args.porter_tasks_dir)
    if not tasks_dir.is_absolute():
        tasks_dir = (project_path / tasks_dir).resolve()

    task_files = _collect_task_files(tasks_dir=tasks_dir, task_glob=args.porter_task_glob)
    if not task_files:
        logger.warning(f"未找到任务配置文件: dir={tasks_dir.as_posix()}, glob={args.porter_task_glob}")

    manager = PorterManager()
    for task_file in task_files:
        key = task_file.stem
        value = environment.get(key=key, default=False, dtype=bool)
        logger.info(f"{key}: {value}")
        if value is True:
            manager.add_tasks_by_task_file(tasks_file=task_file.as_posix())
    task_thread = threading.Thread(
        target=_run_coro_in_new_loop,
        args=(manager.run(),),
        daemon=True,
    )
    task_thread.start()
    time.sleep(1)

    # ui
    with gr.Blocks() as blocks:
        gr.Markdown(value="live recording.")
        with gr.Tabs():
            _ = get_project_overview_tab()
            _ = get_shell_tab()

    # http://127.0.0.1:7870/
    # http://10.75.27.247:7870/
    blocks.queue().launch(
        # share=True,
        share=False if platform.system() in ("Windows", "Darwin") else False,
        server_name="127.0.0.1" if platform.system() in ("Windows", "Darwin") else "0.0.0.0",
        server_port=args.server_port
    )


if __name__ == "__main__":
    main()
