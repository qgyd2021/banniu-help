#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
各平台「拉取贴子元信息」流转任务。

各平台 ``toolbox/<platform>/media/share_media_download_.py`` 中的
``ShareMediaDownload`` 已经统一为：

    client.get_post_meta_by_share_text(share_text: str) -> dict

返回的 dict 字段名 / 类型 / 语义与 ``toolbox.porter.entity.post_meta.PostMeta``
完全对齐，因此这里所有平台共用同一份处理骨架，仅在子类上声明
``share_media_client_cls`` 与默认 ``output_dir``。
"""
import asyncio
import logging
import traceback
from typing import ClassVar, Type

from toolbox.bilibili.media.share_media_download_ import ShareMediaDownload as BilibiliShareMediaDownload
from toolbox.dewu.media.share_media_download_ import ShareMediaDownload as DewuShareMediaDownload
from toolbox.douyin.media.share_media_download_ import ShareMediaDownload as DouyinShareMediaDownload
from toolbox.kuaishou.media.share_media_download_ import ShareMediaDownload as KuaishouShareMediaDownload
from toolbox.porter.entity.post_meta import PostMeta
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.weibo.media.share_media_download_ import ShareMediaDownload as WeiboShareMediaDownload
from toolbox.xiaoheihe.media.share_media_download_ import ShareMediaDownload as XiaoHeiHeShareMediaDownload
from toolbox.xiaohongshu.media.share_media_download_ import ShareMediaDownload as XiaoHongShuShareMediaDownload

logger = logging.getLogger("toolbox")


class ShareMediaDownloadTaskBase(BaseTask, TaskJsonUtils):
    """
    各平台 share_media_download 任务的公共骨架。

    子类只需要在类上声明：
    - ``share_media_client_cls``：对应平台 ``_.py`` 中的 ``ShareMediaDownload`` 类；
    - ``default_output_dir``：``output_dir`` 的默认值；
    其余流程完全复用。
    """
    share_media_client_cls: ClassVar[Type]

    def __init__(
        self,
        check_interval: int,
        source_dir: str,
        output_dir: str = None,
        share_post_url_field: str = "晒单内容链接",
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.output_dir = self.resolve_project_path(output_dir)
        self.share_post_url_field = share_post_url_field

        self.share_media_client = self.share_media_client_cls()

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
            share_text = payload["task_formatted"][self.share_post_url_field]

            try:
                post_meta_dict = await asyncio.to_thread(
                    self.share_media_client.get_post_meta_by_share_text, share_text,
                )
                post_meta = PostMeta.from_dict(post_meta_dict)
            except AssertionError as error:
                logger.info(
                    f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}，"
                    f"error： {str(error)}, traceback: {traceback.format_exc()}"
                )
                continue
            except Exception:
                logger.info(f"{self.flag}任务拉取全失败，保留原位置等待下次重试: {task_file.as_posix()}")
                continue

            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / task_file.name
            self.safe_move(task_file, dst)
            await self.append_kv_to_task_file(dst, kv={"post_meta": post_meta.to_dict()})
            logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


@BaseTask.register("share_media_download_by_bilibili")
class ShareMediaDownloadByBilibiliTask(ShareMediaDownloadTaskBase):
    share_media_client_cls = BilibiliShareMediaDownload
    default_output_dir = "bilibili_share_media_download/tasks"


@BaseTask.register("share_media_download_by_dewu")
class ShareMediaDownloadByDewuTask(ShareMediaDownloadTaskBase):
    share_media_client_cls = DewuShareMediaDownload
    default_output_dir = "dewu_share_media_download/tasks"


@BaseTask.register("share_media_download_by_douyin")
class ShareMediaDownloadByDouyinTask(ShareMediaDownloadTaskBase):
    share_media_client_cls = DouyinShareMediaDownload
    default_output_dir = "douyin_share_media_download/tasks"


@BaseTask.register("share_media_download_by_xiaohongshu")
class ShareMediaDownloadByXiaoHongShuTask(ShareMediaDownloadTaskBase):
    share_media_client_cls = XiaoHongShuShareMediaDownload
    default_output_dir = "xiaohongshu_share_media_download/tasks"


@BaseTask.register("share_media_download_by_kuaishou")
class ShareMediaDownloadByKuaishouTask(ShareMediaDownloadTaskBase):
    share_media_client_cls = KuaishouShareMediaDownload
    default_output_dir = "kuaishou_share_media_download/tasks"


@BaseTask.register("share_media_download_by_xiaoheihe")
class ShareMediaDownloadByXiaoHeiHeTask(ShareMediaDownloadTaskBase):
    share_media_client_cls = XiaoHeiHeShareMediaDownload
    default_output_dir = "xiaoheihe_share_media_download/tasks"


@BaseTask.register("share_media_download_by_weibo")
class ShareMediaDownloadByWeiboTask(ShareMediaDownloadTaskBase):
    share_media_client_cls = WeiboShareMediaDownload
    default_output_dir = "weibo_share_media_download/tasks"


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
