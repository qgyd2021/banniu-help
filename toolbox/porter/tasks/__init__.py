#!/usr/bin/python3
# -*- coding: utf-8 -*-
from toolbox.porter.tasks.banniu_task_batch_update import (
    BanNiuTaskBatchUpdateByConditionTask,
    BanNiuTaskBatchUpdateTask,
)
from toolbox.porter.tasks.banniu_task_download_task import BanNiuPendingReviewTaskDownloadTask
from toolbox.porter.tasks.banniu_task_update_task import BanNiuTaskUpdateTask
from toolbox.porter.tasks.portal_server_task import PortalServerTask

from toolbox.porter.tasks.post_review_router_task import PostReviewRouterTask
from toolbox.porter.tasks.share_media_download import (
    ShareMediaDownloadByBilibiliTask, ShareMediaDownloadByDewuTask, ShareMediaDownloadByDouyinTask,
    ShareMediaDownloadByWeiboTask, ShareMediaDownloadByXiaoHeiHeTask, ShareMediaDownloadByXiaoHongShuTask,
    ShareMediaDownloadByKuaishouTask
)
from toolbox.porter.tasks.post_review_text_emotion_review_task import PostReviewTextEmotionReviewTask
from toolbox.porter.tasks.post_review_text_length_review_task import PostReviewTextLengthReviewTask
from toolbox.porter.tasks.post_review_text_tags_review_task import PostReviewTextTagsReviewTask
from toolbox.porter.tasks.post_review_image_item_review_task import PostReviewImageItemReviewTask
from toolbox.porter.tasks.post_review_duplicate_review_task import PostReviewDuplicateReviewTask
from toolbox.porter.tasks.post_review_submit_service_task import PostReviewSubmitServiceTask
from toolbox.porter.tasks.post_review_score_task import PostReviewScoreTask, PostReviewOnlyFinal


if __name__ == "__main__":
    pass
