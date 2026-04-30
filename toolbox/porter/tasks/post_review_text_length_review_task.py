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


def number_transform(
    length: float,
    text_length_to_score_map: Tuple[List[float], List[float]],
) -> float:
    """
    按 ``text_length_to_score_map`` 将**已算好的**文本长度映射到 ``[0, 100]`` 分数。

    ``text_length_to_score_map`` 为 ``(length_thresholds, scores)``：两列表等长且非空。
    将 ``(阈值, 分数)`` 按阈值从大到小匹配，返回第一个满足 ``length >= 阈值`` 的分数；
    若长度低于所有阈值，则取 ``scores`` 中的最小值。返回值裁剪到 ``[0.0, 100.0]``。
    """
    if len(text_length_to_score_map) != 2:
        raise ValueError("text_length_to_score_map 须为 (length_thresholds, scores) 两项")
    length_thresholds, scores = text_length_to_score_map
    if len(length_thresholds) != len(scores):
        raise ValueError(
            f"length_thresholds 与 scores 长度须一致，现为 {len(length_thresholds)} / {len(scores)}"
        )
    if not length_thresholds:
        raise ValueError("length_thresholds 不能为空")

    n = float(length)
    pairs = sorted(
        zip((float(t) for t in length_thresholds), (float(s) for s in scores)),
        key=lambda x: x[0],
        reverse=True,
    )
    for t, s in pairs:
        if n >= t:
            return float(max(0.0, min(100.0, s)))
    return float(max(0.0, min(100.0, min(s for _, s in pairs))))


@BaseTask.register("post_review_text_length_review")
class PostReviewTextLengthReviewTask(BaseTask, TaskJsonUtils):
    """
    对贴子标题与正文做长度审核，并将结果写回 task json 后流转到目标目录。

    与情感任务相同，通过 ``platform_meta_config`` 配置 ``title_keys`` / ``body_keys``；
    按**标题字符数 + 描述（正文）字符数**得到总长度，经 ``number_transform`` 映射为 0–100 分数。
    每个 task json 仅使用对应平台 meta 列表中的第一条记录，不处理多条。
    """

    def __init__(self,
                 check_interval: int,
                 platform_to_dirs: List[Tuple[str, str, str]],
                 platform_meta_config: Optional[Dict[str, Dict[str, object]]] = None,
                 text_length_to_score_map: Optional[Tuple[List[float], List[float]]] = None,
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

        self.platform_meta_config = platform_meta_config or {}
        default_spec = [
            [50, 40, 30, 20, 10, 5],
            [100, 95, 90, 80, 50, 0],
        ]
        self.text_length_to_score_map = text_length_to_score_map or default_spec

    @staticmethod
    def extract_content(obj: dict, keys: List[str]) -> str:
        """按 keys 顺序合并 obj 中所有非空字符串字段，换行连接。"""
        if not isinstance(obj, dict):
            return ""
        parts: List[str] = []
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        return "\n".join(parts)

    def review_text_length(self, title: str, body: str) -> Dict[str, object]:
        title_length = len((title or "").strip())
        body_length = len((body or "").strip())
        text_length = title_length + body_length
        score = number_transform(float(text_length), self.text_length_to_score_map)
        desc = f"标题长度 {title_length}，描述长度 {body_length}，总长度 {text_length}。"
        return {
            "desc": desc,
            "score": score,
            "title_length": title_length,
            "body_length": body_length,
            "text_length": text_length,
        }

    def review_one_platform(self, payload: dict, platform: str, config: Dict[str, object]) -> Optional[dict]:
        meta_list_key = str(config.get("meta_list_key") or "").strip()
        if not meta_list_key:
            return None

        rows = payload.get(meta_list_key)
        if not isinstance(rows, list) or not rows:
            return None

        title_keys = [str(x) for x in (config.get("title_keys") or [])]
        body_keys = [str(x) for x in (config.get("body_keys") or [])]

        row = rows[0]
        if not isinstance(row, dict):
            return None
        post_meta = row.get("post_meta") or {}
        if not isinstance(post_meta, dict):
            return None
        title = self.extract_content(post_meta, title_keys)
        body = self.extract_content(post_meta, body_keys)
        if not title and not body:
            return None

        result = self.review_text_length(title=title, body=body)
        item = {
            "index": 0,
            "share_url": row.get("share_url"),
            "title": title,
            "body": body,
            **result,
        }

        overall_desc = f"{item.get('desc') or ''}".strip()

        return {
            "platform": platform,
            "meta_list_key": meta_list_key,
            "overall_desc": overall_desc,
            "overall_score": item.get("score"),
            "reviewed_count": 1,
            "item_reviews": [item],
            "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return

        moved = 0
        reviewed = 0
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

                conf = (self.platform_meta_config or {}).get(platform)
                if not isinstance(conf, dict):
                    logger.info(f"{self.flag}缺少平台配置，跳过: platform={platform}, file={src.name}")
                    continue

                review_result = self.review_one_platform(payload, platform, conf)
                if review_result is None:
                    logger.info(f"{self.flag}未命中可审核文本，跳过: {src.name}, platform={platform}")
                    continue

                payload["post_review_text_length_review"] = review_result
                payload["post_review_text_length_review_status"] = "done"
                payload["post_review_text_length_review_reason"] = "matched_meta_list"

                dst = target_dir / src.name
                final = self.safe_move(src, dst)
                await self.write_json(final, payload)
                reviewed += 1
                moved += 1
                logger.info(f"{self.flag}长度审核完成并流转: {src.name} -> {final.as_posix()}, platform={platform}")

        logger.info(f"{self.flag}本轮扫描 {scanned} 个文件，审核 {reviewed} 个，移动 {moved} 个。")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewTextLengthReviewTask(
        check_interval=60,
        platform_to_dirs=[
            ("douyin", "data/douyin_share_media_download/text_emotion_review_finished", "data/douyin_share_media_download/text_length_review_finished"),
            ("xiaohongshu", "data/xiaohongshu_share_media_download/text_emotion_review_finished", "data/xiaohongshu_share_media_download/text_length_review_finished"),
            ("kuaishou", "data/kuaishou_share_media_download/text_emotion_review_finished", "data/kuaishou_share_media_download/text_length_review_finished"),
            ("bilibili", "data/bilibili_share_media_download/text_emotion_review_finished", "data/bilibili_share_media_download/text_length_review_finished"),
            ("xiaoheihe", "data/xiaoheihe_share_media_download/text_emotion_review_finished", "data/xiaoheihe_share_media_download/text_length_review_finished"),
        ],
        platform_meta_config={
            "xiaohongshu": {
                "meta_list_key": "xiaohongshu_post_meta_list",
                "title_keys": ["title"],
                "body_keys": ["desc"],
            },
            "douyin": {
                "meta_list_key": "douyin_post_meta_list",
                "title_keys": ["title"],
                "body_keys": ["desc"],
            },
            "kuaishou": {
                "meta_list_key": "kuaishou_post_meta_list",
                "title_keys": ["title"],
                "body_keys": ["caption"],
            },
            "bilibili": {
                "meta_list_key": "bilibili_post_meta_list",
                "title_keys": ["title"],
                "body_keys": ["desc", "body_text"],
            },
            "xiaoheihe": {
                "meta_list_key": "xiaoheihe_post_meta_list",
                "title_keys": ["title"],
                "body_keys": ["content", "desc"],
            },
        },
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
