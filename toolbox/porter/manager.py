#!/usr/bin/python3
# -*- coding: utf-8 -*-
import argparse
import asyncio
import json

from toolbox.porter.tasks.base_task import BaseTask
from project_settings import environment, project_path, log_directory, time_zone_info


class PorterManager(object):
    def __init__(self):
        # state
        self.coro_task_set = set()

    @staticmethod
    def get_coro_task_set_by_task_file(tasks_file: str):
        with open(tasks_file, "r", encoding="utf-8") as f:
            tasks = json.load(f)

        coro_task_set = set()
        for task in tasks:
            enable = task.pop("enable")
            task_type = task.pop("type")

            if not enable:
                continue
            task_cls: BaseTask = BaseTask.by_name(task_type)
            task_obj = task_cls(**task)

            coro_task_set.add(task_obj.start())
        return coro_task_set

    def add_tasks_by_task_file(self, tasks_file: str):
        coro_task_set = self.get_coro_task_set_by_task_file(tasks_file)
        self.coro_task_set.update(coro_task_set)
        return len(coro_task_set)

    async def run(self):
        future_tasks = list()
        for task in self.coro_task_set:
            task = asyncio.ensure_future(task)
            # task = asyncio.create_task(task)
            future_tasks.append(task)
            await asyncio.sleep(3)

        await asyncio.wait(future_tasks)


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--porter_task_file",
        # default=(project_path / "porter_tasks/porter_task_37728.json").as_posix(),
        default=(project_path / "porter_tasks/porter_task_37728_v2.json").as_posix(),
        type=str
    )
    args = parser.parse_args()
    return args


async def main():
    args = get_args()

    import log
    from project_settings import environment, project_path, log_directory, time_zone_info

    log.setup_size_rotating(log_directory=log_directory, tz_info=time_zone_info)

    manager = PorterManager()
    manager.add_tasks_by_task_file(args.porter_task_file)
    await manager.run()
    return


if __name__ == "__main__":
    asyncio.run(main())
