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


@BaseTask.register("post_review_text_tags_review")
class PostReviewTextTagsReviewTask(BaseTask, TaskJsonUtils):
    """
    依据“标准名 + 相似名（同义词）”在标题/正文中做关键词检测，并统计每个标准名命中次数。
    """

    def __init__(
        self,
        check_interval: int,
        platform_to_dirs: List[Tuple[str, str, str]],
        platform_meta_config: Optional[Dict[str, Dict[str, object]]] = None,
        tags_config: Optional[Dict[str, List[str]]] = None,
        **kwargs,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)

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
        self.tags_config = self._normalize_tags_config(tags_config or {})

    @staticmethod
    def _normalize_tags_config(raw: Dict[str, List[str]]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for standard_name, aliases in (raw or {}).items():
            std = str(standard_name or "").strip()
            if not std:
                continue
            words: List[str] = [std]
            if isinstance(aliases, list):
                for a in aliases:
                    s = str(a or "").strip()
                    if s and s not in words:
                        words.append(s)
            out[std] = words
        return out

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

    @staticmethod
    def _count_occurrences(text: str, keyword: str) -> int:
        t = str(text or "").lower()
        k = str(keyword or "").lower()
        if not t or not k:
            return 0
        return t.count(k)

    def review_one_text(self, text: str) -> Dict[str, int]:
        standard_counts: Dict[str, int] = {}
        for standard_name, words in self.tags_config.items():
            total = 0
            for w in words:
                c = self._count_occurrences(text, w)
                total += c
            standard_counts[standard_name] = total
        return standard_counts

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
        merged_text = f"{title}\n{body}".strip()
        if not merged_text:
            return None

        standard_totals = self.review_one_text(merged_text)

        item_reviews = [
            {
                "index": 0,
                "share_url": row.get("share_url"),
                "title": title,
                "body": body,
                "standard_counts": standard_totals,
            }
        ]

        detected_standard_count = sum(1 for _, v in standard_totals.items() if int(v) > 0)
        found_tags = [k for k, v in standard_totals.items() if int(v) > 0]
        not_found_tags = [k for k, v in standard_totals.items() if int(v) <= 0]
        overall_score = int((detected_standard_count / len(standard_totals)) * 100) if standard_totals else 0
        found_text = "、".join(found_tags) if found_tags else "无"
        not_found_text = "、".join(not_found_tags) if not_found_tags else "无"
        overall_desc = (
            f"已命中 tag: {found_text}；"
            f"未命中 tag: {not_found_text}。"
        )
        return {
            "platform": platform,
            "meta_list_key": meta_list_key,
            "overall_score": overall_score,
            "overall_desc": overall_desc,
            "reviewed_count": 1,
            "detected_standard_count": detected_standard_count,
            "standard_counts": standard_totals,
            "item_reviews": item_reviews,
            "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def do_task(self):
        if not self.platform_to_dir:
            logger.info(f"{self.flag}platform_to_dirs 为空，跳过")
            return
        if not self.tags_config:
            logger.info(f"{self.flag}tags_config 为空，跳过")
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

                payload["post_review_text_tags_review"] = review_result
                payload["post_review_text_tags_review_status"] = "done"
                payload["post_review_text_tags_review_reason"] = "matched_meta_list"

                dst = target_dir / src.name
                final = self.safe_move(src, dst)
                await self.write_json(final, payload)
                reviewed += 1
                moved += 1
                logger.info(f"{self.flag}文本标签审核完成并流转: {src.name} -> {final.as_posix()}, platform={platform}")

        logger.info(f"{self.flag}本轮扫描 {scanned} 个文件，审核 {reviewed} 个，移动 {moved} 个。")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewTextTagsReviewTask(
        check_interval=60,
        platform_to_dirs=[
            ("douyin", "temp/banniu_37728/step_4_post_review_text_emotion_review/douyin", "temp/banniu_37728/step_5_post_review_text_tags_review/douyin"),
            ("xiaohongshu", "temp/banniu_37728/step_4_post_review_text_emotion_review/xiaohongshu", "temp/banniu_37728/step_5_post_review_text_tags_review/xiaohongshu"),
        ],
        platform_meta_config={
            "xiaohongshu": {"meta_list_key": "xiaohongshu_post_meta_list", "title_keys": ["title"], "body_keys": ["desc"]},
            "douyin": {"meta_list_key": "douyin_post_meta_list", "title_keys": ["title"], "body_keys": ["desc"]},
        },
        tags_config={
            "迈从": ["迈从", "MCHose", "MC Hose"],
            "迈从ACE68v2": ["迈从ACE68 v2", "迈从ACE68v2", "ACE68v2"],
        },
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
