#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
任务包的聚合导入入口。

注意：此处采用“软导入”避免某些任务依赖的第三方库缺失时导致整个包无法 import。
具体任务建议在使用处显式 import。
"""


def _safe_import(path: str):
    try:
        __import__(path, globals(), locals(), ["*"])
    except Exception:
        # 兼容开发/测试环境缺依赖：跳过即可
        return


_safe_import("toolbox.porter.tasks.banniu_task_download_task")
_safe_import("toolbox.porter.tasks.post_review_get_text_score_task")
_safe_import("toolbox.porter.tasks.post_review_text_length_review_task")
_safe_import("toolbox.porter.tasks.post_review_text_tags_review_task")
_safe_import("toolbox.porter.tasks.post_review_text_emotion_review_task")
_safe_import("toolbox.porter.tasks.post_review_duplicate_review_task")
_safe_import("toolbox.porter.tasks.bilibili_share_media_download_task")
_safe_import("toolbox.porter.tasks.kuaishou_share_media_download_task")
_safe_import("toolbox.porter.tasks.xiaohongshu_share_media_download_task")
_safe_import("toolbox.porter.tasks.douyin_share_media_download_task")
_safe_import("toolbox.porter.tasks.weibo_share_media_download_task")
_safe_import("toolbox.porter.tasks.xiaoheihe_share_media_download_task")
_safe_import("toolbox.porter.tasks.dewu_share_media_download_task")
_safe_import("toolbox.porter.tasks.post_review_router_task")
_safe_import("toolbox.porter.tasks.post_review_media_review_service_task.post_review_image_review_service_task")
_safe_import("toolbox.porter.tasks.post_review_media_review_service_task.post_review_video_review_service_task")
_safe_import("toolbox.porter.tasks.post_review_media_review_service_task_pretty.post_review_image_review_service_task_pretty")
_safe_import("toolbox.porter.tasks.post_review_media_review_service_task_pretty.post_review_video_review_service_task_pretty")
_safe_import("toolbox.porter.tasks.post_review_submit_service_task.post_review_submit_service_task")
_safe_import("toolbox.porter.tasks.post_review_get_image_score_task")
_safe_import("toolbox.porter.tasks.post_review_get_video_score_task")
_safe_import("toolbox.porter.tasks.post_review_get_image_score_bypass")
_safe_import("toolbox.porter.tasks.post_review_get_video_score_bypass")
_safe_import("toolbox.porter.tasks.banniu_task_update_task")
_safe_import("toolbox.porter.tasks.banniu_task_batch_update_task")
_safe_import("toolbox.porter.tasks.portal_server_task")


if __name__ == "__main__":
    pass
