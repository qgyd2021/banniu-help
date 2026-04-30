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


@BaseTask.register("post_review_get_text_score")
class PostReviewGetTextScoreTask(BaseTask, TaskJsonUtils):
    """
    汇总各 review 任务结果，计算 0-100 的综合得分，并流转到下一目录。
    """

    def __init__(self,
                 check_interval: int,
                 platform_to_dirs: List[Tuple[str, str, str]],
                 score_component_config: Optional[Dict[str, Dict[str, object]]] = None,
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

        self.score_component_config = score_component_config or self.default_score_component_config()

    @staticmethod
    def default_score_component_config() -> Dict[str, Dict[str, object]]:
        return {
            "情绪": {
                "field": "post_review_text_emotion_review",
                "weight": 0.50,
                "item_score_key": "overall_score",
                "item_desc_key": "overall_desc",
                "missing_score": 0,
            },
            "长度": {
                "field": "post_review_text_length_review",
                "weight": 0.25,
                "item_score_key": "overall_score",
                "item_desc_key": "overall_desc",
                "missing_score": 0,
            },
            "标签": {
                "field": "post_review_text_tags_review",
                "weight": 0.25,
                "item_score_key": "overall_score",
                "item_desc_key": "overall_desc",
                "missing_score": 0,
            },
        }

    @staticmethod
    def safe_float(v: object, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return default

    @classmethod
    def normalize_weights(cls, component_config: Dict[str, Dict[str, object]]) -> Dict[str, float]:
        raw: Dict[str, float] = {}
        for name, conf in component_config.items():
            raw[name] = max(0.0, cls.safe_float((conf or {}).get("weight"), default=0.0))
        total = sum(raw.values())
        if total <= 0:
            if not raw:
                return {}
            even = 1.0 / len(raw)
            return {k: even for k in raw}
        return {k: v / total for k, v in raw.items()}

    def calculate_total_score(self, payload: dict) -> Dict[str, object]:
        conf_map = self.score_component_config or {}
        norm_weights = self.normalize_weights(conf_map)

        component_rows: List[dict] = []
        summary_parts: List[str] = []
        weighted_sum = 0.0
        for name, conf in conf_map.items():
            field = str((conf or {}).get("field") or "").strip()
            item_desc_key = conf.get("item_desc_key", "overall_desc")
            item_score_key = conf.get("item_score_key", "overall_score")
            missing_score = conf.get("missing_score", 50.0)
            missing_score = float(missing_score)

            review_obj = payload.get(field) if field else None
            desc = ""
            score = missing_score
            if isinstance(review_obj, dict):
                # 直接读取各 review 任务统一输出的 overall_* 字段
                desc = review_obj.get(item_desc_key) or ""
                score = review_obj.get(item_score_key) or missing_score

            score = max(0.0, min(100.0, score))
            weight = norm_weights.get(name, 0.0)
            weighted = score * weight
            weighted_sum += weighted
            if desc:
                summary_parts.append(f"{name}: \n{desc}")
            component_rows.append({
                "name": name,
                "field": field,
                "desc": desc,
                "score": round(score, 2),
                "weight": round(weight, 6),
                "weighted_score": round(weighted, 2),
            })

        final_score = max(0, min(100, int(round(weighted_sum))))
        summary_desc = "\n".join(summary_parts) if summary_parts else "未获取到可用于评分的描述信息。"
        return {
            "score": final_score,
            "desc": summary_desc,
            "components": component_rows,
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
                payload = await self.load_json_file(src)
                if payload is None:
                    continue

                score_result = self.calculate_total_score(payload)
                payload["post_review_get_text_score"] = score_result
                payload["post_review_get_text_score_status"] = "done"
                payload["post_review_get_text_score_reason"] = "weighted_components"

                dst = target_dir / src.name
                final = self.safe_move(src, dst)
                await self.write_json(final, payload)
                scored += 1
                moved += 1
                logger.info(
                    f"{self.flag}综合评分完成并流转: {src.name} -> {final.as_posix()}, "
                    f"platform={platform}, score={score_result.get('final_score')}"
                )

        logger.info(f"{self.flag}本轮扫描 {scanned} 个文件，评分 {scored} 个，移动 {moved} 个。")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewGetTextScoreTask(
        check_interval=60,
        platform_to_dirs=[
            ("douyin", "data/douyin_share_media_download/text_length_review_finished", "data/douyin_share_media_download/get_text_score_finished"),
            ("xiaohongshu", "data/xiaohongshu_share_media_download/text_length_review_finished", "data/xiaohongshu_share_media_download/get_text_score_finished"),
            ("kuaishou", "data/kuaishou_share_media_download/text_length_review_finished", "data/kuaishou_share_media_download/get_text_score_finished"),
            ("bilibili", "data/bilibili_share_media_download/text_length_review_finished", "data/bilibili_share_media_download/get_text_score_finished"),
            ("xiaoheihe", "data/xiaoheihe_share_media_download/text_length_review_finished", "data/xiaoheihe_share_media_download/get_text_score_finished"),
        ],
        score_component_config={
            "情绪": {
                "field": "post_review_text_emotion_review",
                "weight": 0.50,
                "item_score_key": "overall_score",
                "item_desc_key": "overall_desc",
                "missing_score": 0,
            },
            "长度": {
                "field": "post_review_text_length_review",
                "weight": 0.25,
                "item_score_key": "overall_score",
                "item_desc_key": "overall_desc",
                "missing_score": 0,
            },
            "标签": {
                "field": "post_review_text_tags_review",
                "weight": 0.25,
                "item_score_key": "overall_score",
                "item_desc_key": "overall_desc",
                "missing_score": 0,
            },
        },
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
