#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from gradio_client import Client, handle_file

logger = logging.getLogger("toolbox")

from toolbox.porter.entity.post_review import PostReview
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.porter.entity.post_meta import PostMeta
from toolbox.bilibili.utils.fresh_media_url import FreshImageUrl as BilibiliFreshImageUrl
from toolbox.weibo.utils.fresh_media_url import FreshImageUrl as WeiboFreshImageUrl
from toolbox.xiaohongshu.utils.fresh_media_url import FreshImageUrl as XiaoHongShuFreshImageUrl
from toolbox.douyin.utils.fresh_media_url import FreshImageUrl as DouyinFreshImageUrl
from toolbox.kuaishou.utils.fresh_media_url import FreshImageUrl as KuaishouFreshImageUrl
from toolbox.dewu.utils.fresh_media_url import FreshImageUrl as DewuFreshImageUrl
from toolbox.xiaoheihe.utils.fresh_media_url import FreshImageUrl as XiaoHeiHeFreshImageUrl

from toolbox.utils.utils import when_error

from project_settings import environment, project_path, temp_directory


@BaseTask.register("post_review_image_item_review", exist_ok=True)
class PostReviewImageItemReviewTask(BaseTask, TaskJsonUtils):
    def __init__(self,
                 check_interval: int,
                 platform_to_dirs: List[Tuple[str, str, str]],
                 **kwargs):
        super().__init__(
            flag=f"[{self.__class__.__name__}]",
            check_interval=check_interval,
        )
        self.platform_to_dir: List[Tuple[str, Path, Path]] = []
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            src_path = self.resolve_project_path(src)
            dst_path = self.resolve_project_path(dst)
            self.platform_to_dir.append((p, src_path, dst_path))

        host = environment.get(key="POST_REVIEW_IMAGE_ITEM_HOST", default="http://192.168.34.115:7861/", dtype=str)
        self.api_name = environment.get(key="POST_REVIEW_IMAGE_ITEM_API_NAME", default="/yolo_predict", dtype=str)
        self.model_choice = environment.get(key="POST_REVIEW_IMAGE_ITEM_MODEL_CHOICE", default="yolo11n.pt", dtype=str)

        self.yolo_client = Client(src=host)

        self.image_stream_client_map: Dict[str, Any] = {
            "bilibili": BilibiliFreshImageUrl(),
            "weibo": WeiboFreshImageUrl(),
            "xiaohongshu": XiaoHongShuFreshImageUrl(),
            "douyin": DouyinFreshImageUrl(),
            "kuaishou": KuaishouFreshImageUrl(),
            "dewu": DewuFreshImageUrl(),
            "xiaoheihe": XiaoHeiHeFreshImageUrl(),
        }

    def download_image_to_local(self, platform: str, image_url: str, image_index: int, share_url: str) -> str:
        client = self.image_stream_client_map.get(platform)
        if client is None:
            return None
        response = client.ensure_image_url(
            image_url=image_url,
            share_url=share_url,
            image_index=image_index,
        )
        temp_dir = temp_directory / "post_review_image_item_review"
        temp_dir.mkdir(parents=True, exist_ok=True)
        filename = (temp_dir / f"{uuid.uuid4().hex}.jpg").as_posix()
        try:
            with open(filename, "wb") as f:
                for chunk in response.raw.stream(1024 * 128, decode_content=False):
                    if chunk:
                        f.write(chunk)
        finally:
            response.close()
        return filename

    @when_error(return_value=None)
    async def process_one_file(self, task_file: Path, target_dir: Path) -> Path:
        payload: dict = await self.load_json_file(task_file)
        post_meta = PostMeta.from_dict(payload["post_meta"])

        result = list()
        for idx, image_url in enumerate(post_meta.image_urls or []):
            filename: str = self.download_image_to_local(
                platform=post_meta.platform, image_url=image_url, image_index=idx, share_url=post_meta.share_url
            )
            try:
                _, js = self.yolo_client.predict(
                    image=handle_file(filename),
                    model_choice=self.model_choice,
                    conf=0.25,
                    iou=0.7,
                    imgsz=640,
                    label_area_fraction=1 / 60,
                    api_name=self.api_name,
                )
            finally:
                Path(filename).unlink(missing_ok=True)
            js = json.loads(js)
            class_counts = js["results"][0]["class_counts"]
            result.append({
                "image_url": image_url,
                "class_counts": class_counts,
            })

        post_review = PostReview.from_dict(payload.get("post_review", dict()))
        post_review.review_image_item.images = result

        dst = target_dir / task_file.name
        self.safe_move(task_file, dst)
        await self.append_kv_to_task_file(dst, kv={"post_review": post_review.to_dict()})
        return dst

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return

        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            if not files:
                continue

            for src in files:
                dst = await self.process_one_file(src, target_dir)
                if dst is not None:
                    logger.info(f"{self.flag}图片检测完成并归档: {dst.as_posix()}")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewImageItemReviewTask(
        check_interval=60,
        gradio_server_url="http://192.168.34.115:7861/",
        platform_to_dirs=[
            # ["dewu", "temp/banniu_39369/step_5_3_post_review_text_tags_review/dewu", "temp/banniu_39369/step_5_4_post_review_image_item_review/dewu"],
            # ["douyin", "temp/banniu_39369/step_5_3_post_review_text_tags_review/douyin", "temp/banniu_39369/step_5_4_post_review_image_item_review/douyin"],
            ["xiaohongshu", "temp/banniu_39369/step_5_3_post_review_text_tags_review/xiaohongshu", "temp/banniu_39369/step_5_4_post_review_image_item_review/xiaohongshu"],
            # ["kuaishou", "temp/banniu_39369/step_5_3_post_review_text_tags_review/kuaishou", "temp/banniu_39369/step_5_4_post_review_image_item_review/kuaishou"],
            # ["bilibili", "temp/banniu_39369/step_5_3_post_review_text_tags_review/bilibili", "temp/banniu_39369/step_5_4_post_review_image_item_review/bilibili"],
            # ["xiaoheihe", "temp/banniu_39369/step_5_3_post_review_text_tags_review/xiaoheihe", "temp/banniu_39369/step_5_4_post_review_image_item_review/xiaoheihe"],
            # ["weibo", "temp/banniu_39369/step_5_3_post_review_text_tags_review/weibo", "temp/banniu_39369/step_5_4_post_review_image_item_review/weibo"]
        ],
        model_choice="yolo11n.pt",
        conf=0.25,
        iou=0.7,
        imgsz=640,
        label_area_fraction=1 / 60,
        api_name="/yolo_predict",
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
