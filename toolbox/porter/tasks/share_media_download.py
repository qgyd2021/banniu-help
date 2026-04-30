#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import logging

from toolbox.bilibili.media.share_media_download import ShareMediaDownload as BilibiliShareMediaDownload
from toolbox.dewu.media.share_media_download import ShareMediaDownload as DewuShareMediaDownload
from toolbox.douyin.media.share_media_download import ShareMediaDownload as DouyinShareMediaDownload
from toolbox.kuaishou.media.share_media_download import ShareMediaDownload as KuaishouShareMediaDownload
from toolbox.porter.entity.banniu_task import BanniuTaskFormatted
from toolbox.porter.entity.post_meta import PostMeta
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.weibo.media.share_media_download import ShareMediaDownload as WeiboShareMediaDownload
from toolbox.xiaoheihe.media.share_media_download import ShareMediaDownload as XiaoHeiHeShareMediaDownload
from toolbox.xiaohongshu.media.share_media_download import ShareMediaDownload as XiaoHongShuShareMediaDownload

logger = logging.getLogger("toolbox")


@BaseTask.register("share_media_download_by_bilibili")
class ShareMediaDownloadByBilibiliTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        source_dir: str,
        output_dir: str = "bilibili_share_media_download/tasks",
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.output_dir = self.resolve_project_path(output_dir)
        self.share_media_client = BilibiliShareMediaDownload()

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无 task 文件: {self.source_dir.as_posix()}")
            return

        for task_file in files:
            payload = await self.load_json_file(task_file)

            task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
            share_text = task_formatted.share_text

            try:
                info = self.share_media_client.classify_share_link(share_text)
                entry_url = info["entry_url"]
                if info["kind"] == "video":
                    post_meta = self.share_media_client.video.get_post_meta_by_share_url(entry_url)
                    post_meta["share_url"] = entry_url
                    post_meta = PostMeta.from_dict_by_bilibili_video(post_meta)
                else:
                    post_meta = self.share_media_client.opus.get_opus_meta_by_url(entry_url)
                    post_meta["share_url"] = entry_url
                    post_meta = PostMeta.from_dict_by_bilibili_opus(post_meta)
            except AssertionError:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue
            except Exception:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / task_file.name
            self.safe_move(task_file, dst)
            await self.append_kv_to_task_file(dst, kv={"post_meta": post_meta.to_dict()})
            logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


@BaseTask.register("share_media_download_by_dewu")
class ShareMediaDownloadByDewuTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        source_dir: str,
        output_dir: str = "dewu_share_media_download/tasks",
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.output_dir = self.resolve_project_path(output_dir)
        self.share_media_client = DewuShareMediaDownload()

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无 task 文件: {self.source_dir.as_posix()}")
            return

        for task_file in files:
            payload = await self.load_json_file(task_file)

            task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
            share_text = task_formatted.share_text

            try:
                share_url = self.share_media_client.get_share_url_by_share_text(share_text)
                post_meta = await asyncio.to_thread(self.share_media_client.get_post_meta_by_share_url, share_url)
                post_meta["share_url"] = share_url
                post_meta = PostMeta.from_dict_by_dewu(post_meta)
            except AssertionError:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue
            except Exception:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / task_file.name
            self.safe_move(task_file, dst)
            await self.append_kv_to_task_file(dst, kv={"post_meta": post_meta.to_dict()})
            logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


@BaseTask.register("share_media_download_by_douyin")
class ShareMediaDownloadByDouyinTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        source_dir: str,
        output_dir: str = "douyin_share_media_download/tasks",
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.output_dir = self.resolve_project_path(output_dir)
        self.share_media_client = DouyinShareMediaDownload()

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无 task 文件: {self.source_dir.as_posix()}")
            return

        for task_file in files:
            payload = await self.load_json_file(task_file)

            task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
            share_text = task_formatted.share_text

            try:
                share_url = self.share_media_client.get_share_url_by_share_text(share_text)
                post_meta = await asyncio.to_thread(self.share_media_client.get_post_meta_by_share_url, share_url)
                post_meta["share_url"] = share_url
                post_meta = PostMeta.from_dict_by_douyin(post_meta)
            except AssertionError:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue
            except Exception:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / task_file.name
            self.safe_move(task_file, dst)
            await self.append_kv_to_task_file(dst, kv={"post_meta": post_meta.to_dict()})
            logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


@BaseTask.register("share_media_download_by_xiaohongshu")
class ShareMediaDownloadByXiaoHongShuTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        source_dir: str,
        output_dir: str = "xiaohongshu_share_media_download/tasks",
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.output_dir = self.resolve_project_path(output_dir)
        if XiaoHongShuShareMediaDownload is None:
            raise ModuleNotFoundError("xiaohongshu ShareMediaDownload unavailable (missing optional dependencies)")
        self.share_media_client = XiaoHongShuShareMediaDownload()

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无 task 文件: {self.source_dir.as_posix()}")
            return

        for task_file in files:
            payload = await self.load_json_file(task_file)

            task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
            share_text = task_formatted.share_text

            try:
                share_url = self.share_media_client.get_share_url_by_share_text(share_text)
                post_meta = await asyncio.to_thread(self.share_media_client.get_post_meta_by_share_url, share_url)
                post_meta["share_url"] = share_url
                post_meta = PostMeta.from_dict_by_xiaohongshu(post_meta)
            except AssertionError:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue
            except Exception:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / task_file.name
            self.safe_move(task_file, dst)
            await self.append_kv_to_task_file(dst, kv={"post_meta": post_meta.to_dict()})
            logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


@BaseTask.register("share_media_download_by_kuaishou")
class ShareMediaDownloadByKuaishouTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        source_dir: str,
        output_dir: str = "kuaishou_share_media_download/tasks",
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.output_dir = self.resolve_project_path(output_dir)
        self.share_media_client = KuaishouShareMediaDownload()

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无 task 文件: {self.source_dir.as_posix()}")
            return

        for task_file in files:
            payload = await self.load_json_file(task_file)

            task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
            share_text = task_formatted.share_text

            try:
                share_url = self.share_media_client.get_share_url_by_share_text(share_text)
                post_meta = await asyncio.to_thread(self.share_media_client.get_post_meta_by_share_url, share_url)
                post_meta["share_url"] = share_url
                post_meta = PostMeta.from_dict_by_kuaishou(post_meta)
            except AssertionError:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue
            except Exception:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / task_file.name
            self.safe_move(task_file, dst)
            await self.append_kv_to_task_file(dst, kv={"post_meta": post_meta.to_dict()})
            logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


@BaseTask.register("share_media_download_by_xiaoheihe")
class ShareMediaDownloadByXiaoHeiHeTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        source_dir: str,
        output_dir: str = "xiaoheihe_share_media_download/tasks",
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.output_dir = self.resolve_project_path(output_dir)
        self.share_media_client = XiaoHeiHeShareMediaDownload()

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无 task 文件: {self.source_dir.as_posix()}")
            return

        for task_file in files:
            payload = await self.load_json_file(task_file)

            task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
            share_text = task_formatted.share_text

            try:
                share_url = self.share_media_client.get_share_url_by_share_text(share_text)
                post_meta = await asyncio.to_thread(self.share_media_client.get_post_meta_by_share_url, share_url)
                post_meta["share_url"] = share_url
                post_meta = PostMeta.from_dict_by_xiaoheihe(post_meta)
            except AssertionError:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue
            except Exception:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / task_file.name
            self.safe_move(task_file, dst)
            await self.append_kv_to_task_file(dst, kv={"post_meta": post_meta.to_dict()})
            logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


@BaseTask.register("share_media_download_by_weibo")
class ShareMediaDownloadByWeiboTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int,
        source_dir: str,
        output_dir: str = "weibo_share_media_download/tasks",
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.output_dir = self.resolve_project_path(output_dir)
        if WeiboShareMediaDownload is None:
            raise ModuleNotFoundError("weibo ShareMediaDownload unavailable (missing optional dependencies)")
        self.share_media_client = WeiboShareMediaDownload()

    async def do_task(self):
        if not self.source_dir.exists():
            logger.info(f"{self.flag}源目录不存在: {self.source_dir.as_posix()}")
            return

        files = self.pick_task_files(self.source_dir, recursive=False)
        if not files:
            logger.info(f"{self.flag}源目录无 task 文件: {self.source_dir.as_posix()}")
            return

        for task_file in files:
            payload = await self.load_json_file(task_file)

            task_formatted = BanniuTaskFormatted.from_dict(payload["task_formatted"])
            share_text = task_formatted.share_text

            try:
                share_url = self.share_media_client.get_share_url_by_share_text(share_text)
                post_meta = await asyncio.to_thread(self.share_media_client.get_post_meta_by_share_url, share_url)
                post_meta["share_url"] = share_url
                post_meta = PostMeta.from_dict_by_weibo(post_meta)
            except AssertionError:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue
            except Exception:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / task_file.name
            self.safe_move(task_file, dst)
            await self.append_kv_to_task_file(dst, kv={"post_meta": post_meta.to_dict()})
            logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = ShareMediaDownloadByBilibiliTask(
        check_interval=60,
        source_dir="temp/banniu_37728/step_14_finished/bilibili",
        output_dir="temp/banniu_37728/step_14_finished/bilibili",
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
