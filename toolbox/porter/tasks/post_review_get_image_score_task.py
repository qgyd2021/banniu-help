#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("toolbox")

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils


@BaseTask.register("post_review_get_image_score")
class PostReviewGetImageScoreTask(BaseTask, TaskJsonUtils):
    """
    根据 post_review_image_review.image_marks 计算图片审核分并流转。

    规则：
    - 符合 -> 100
    - 空字符串 -> 90
    - 不符合 -> 0
    取分数最高的三张图片求平均，作为最终分（0-100，四舍五入取整）。
    """

    def __init__(self,
                 check_interval: int,
                 platform_to_dirs: List[Tuple[str, str, str]],
                 top_k: int = 3,
                 **kwargs
                 ):
        super().__init__(
            flag=f"[{self.__class__.__name__}]",
            check_interval=check_interval
        )

        self.platform_to_dir = list()
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            if not os.path.isabs(src):
                src = project_path / src
            else:
                src = Path(src)
            if not os.path.isabs(dst):
                dst = project_path / dst
            else:
                dst = Path(dst)
            self.platform_to_dir.append((p, src, dst))

        self.top_k = max(1, int(top_k))
        self.label_to_score = {"符合": 100, "": 97, "不符合": 0}

    def _normalize_label(self, raw_label: object) -> str:
        if raw_label is None:
            return ""
        text = str(raw_label).strip()
        if text in ("", "空", "未标记", "默认", "默认符合"):
            return ""
        if text in ("符合", "通过", "是", "good"):
            return "符合"
        if text in ("不符合", "不通过", "否", "bad"):
            return "不符合"
        return text if text in ("符合", "不符合") else ""

    def _calculate_image_score(self, payload: dict) -> Dict[str, object]:
        review_obj = payload.get("post_review_image_review")
        image_marks = {}
        if isinstance(review_obj, dict):
            marks = review_obj.get("image_marks")
            if isinstance(marks, dict):
                image_marks = marks

        rows: List[Dict[str, object]] = []
        label_count = {"符合": 0, "不符合": 0, "空": 0}
        for image_url, label_raw in image_marks.items():
            if not isinstance(image_url, str) or not image_url.strip():
                continue
            label = self._normalize_label(label_raw)
            score = self.label_to_score.get(label, 90 if label == "" else 0)
            if label == "符合":
                label_count["符合"] += 1
            elif label == "不符合":
                label_count["不符合"] += 1
            else:
                label = ""
                label_count["空"] += 1
            rows.append({
                "image_url": image_url,
                "label": label,
                "score": score,
            })

        if not rows:
            return {
                "score": 0,
                "desc": "未找到 image_marks，无法计算图片分数。",
                "image_count": 0,
                "label_count": label_count,
                "selected_top_scores": [],
                "selected_top_images": [],
                "calculated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        rows_sorted = sorted(rows, key=lambda x: int(x.get("score", 0)), reverse=True)
        top_rows = rows_sorted[:self.top_k]
        top_scores = [int(x["score"]) for x in top_rows]
        avg_score = int(round(sum(top_scores) / len(top_scores))) if top_scores else 0
        avg_score = max(0, min(100, avg_score))

        desc = (
            f"共 {len(rows)} 张图片：符合 {label_count['符合']} 张，不符合 {label_count['不符合']} 张，空 {label_count['空']} 张。"
            f"按规则映射分值（符合=100，空=97，不符合=0），取最高 {len(top_scores)} 张参与计算，"
            f"分值为 {top_scores}，平均分 {avg_score}。"
        )
        return {
            "score": avg_score,
            "desc": desc,
            "image_count": len(rows),
            "label_count": label_count,
            "selected_top_scores": top_scores,
            "selected_top_images": top_rows,
            "calculated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return

        moved = 0
        scored = 0
        scanned = 0
        for platform, source_dir, target_dir in self.platform_to_dir:
            if not source_dir.exists():
                logger.info(f"{self.flag}源目录不存在，跳过: platform={platform}, source={source_dir.as_posix()}")
                continue
            target_dir.mkdir(parents=True, exist_ok=True)

            files = self.pick_task_files(source_dir, recursive=False)
            for src in files:
                scanned += 1
                try:
                    payload = await self.load_json_file(src)
                except Exception as e:
                    logger.error(f"{self.flag}读取/解析失败: {src.as_posix()}, err={e}")
                    continue

                score_result = self._calculate_image_score(payload)
                payload["post_review_get_image_score"] = score_result
                payload["post_review_get_image_score_status"] = "done"
                payload["post_review_get_image_score_reason"] = "top_k_image_marks_average"

                dst = target_dir / src.name
                final = await asyncio.to_thread(self.safe_move, src, dst)
                await self.write_json(final, payload)
                scored += 1
                moved += 1
                logger.info(
                    f"{self.flag}图片评分完成并流转: {src.name} -> {final.as_posix()}, "
                    f"platform={platform}, score={score_result.get('final_score')}"
                )

        logger.info(f"{self.flag}本轮扫描 {scanned} 个文件，评分 {scored} 个，移动 {moved} 个。")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewGetImageScoreTask(
        check_interval=60,
        platform_to_dirs=[
            ("douyin", "temp/banniu_37728/step_8_post_review_image_review/douyin", "temp/banniu_37728/step_9_post_review_get_image_score/douyin"),
            ("xiaohongshu", "temp/banniu_37728/step_8_post_review_image_review/xiaohongshu", "temp/banniu_37728/step_9_post_review_get_image_score/xiaohongshu"),
            ("kuaishou", "temp/banniu_37728/step_8_post_review_image_review/kuaishou", "temp/banniu_37728/step_9_post_review_get_image_score/kuaishou"),
            ("bilibili", "temp/banniu_37728/step_8_post_review_image_review/bilibili", "temp/banniu_37728/step_9_post_review_get_image_score/bilibili"),
            ("xiaoheihe", "temp/banniu_37728/step_8_post_review_image_review/xiaoheihe", "temp/banniu_37728/step_9_post_review_get_image_score/xiaoheihe"),
        ],
        top_k=3,
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
