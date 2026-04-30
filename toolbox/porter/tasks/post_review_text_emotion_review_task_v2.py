#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("toolbox")

from project_settings import project_path, environment
from toolbox.porter.llm import LLMAsJudge, AsyncLLMAsJudge
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.porter.entity.post_meta import PostMeta


_EMOTION_SYSTEM_PROMPT = """
## 背景
公司为推广新的产品让购买过产品的用户在社交媒体上发分享贴子，审核通过后给用户送礼品。

## 任务
现在我们需要对贴子中文字的部分进行情感判断，以确定它是不是正向积极的内容而不是不利于品牌的消积内容。
我们将情感定为：积极，中性，消极。

## 输出格式
必须输出严格的JSON格式，并遵循以下 schema
{
  "type": "object",
  "properties": {
    "desc": {
      "title": "描述",
      "type": "string",
      "description": "给出该标签的详细说明",
      "minLength": 1
    },
    "label": {
      "title": "标签",
      "type": "string",
      "enum": ["积极", "中性", "消极"],
      "description": "情感分类标签"
    }
  },
  "required": ["desc", "label"]
}
""".strip()


@BaseTask.register("post_review_text_emotion_review_v2")
class PostReviewTextEmotionReviewTaskV2(BaseTask, TaskJsonUtils):
    def __init__(self,
                 check_interval: int,
                 platform_to_dirs: List[Tuple[str, str]],
                 key_of_llm_base_url: str = "POST_REVIEW_LLM_BASE_URL",
                 key_of_llm_api_key: str = "POST_REVIEW_LLM_API_KEY",
                 key_of_llm_model_id: str = "POST_REVIEW_LLM_MODEL_ID",
                 **kwargs
                 ):
        super().__init__(
            flag=f"[{self.__class__.__name__}]",
            check_interval=check_interval
        )

        self.platform_to_dir = list()
        for platform, src, dst in platform_to_dirs:
            p = str(platform).strip().lower()
            src = self.resolve_project_path(src)
            dst = self.resolve_project_path(dst)
            self.platform_to_dir.append((p, src, dst))

        llm_base_url = environment.get(key_of_llm_base_url, default="http://127.0.0.1:11434/v1")
        llm_api_key = environment.get(key_of_llm_api_key, default="ollama")
        llm_model_id = environment.get(key_of_llm_model_id, default="qwen2.5:14b-instruct")
        self.llm_judge = AsyncLLMAsJudge(
            base_url=llm_base_url,
            api_key=llm_api_key,
            model_id=llm_model_id,
            system_prompt=_EMOTION_SYSTEM_PROMPT,
        )

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

    async def score_text(self, title: str, body: str) -> Dict[str, object]:
        user_prompt = f"标题：{title or ''}\n正文：{body or ''}".strip()

        parsed = await self.llm_judge.complete_json(user_prompt)
        js = parsed if isinstance(parsed, dict) else {}
        label = str(js.get("label") or "").strip()
        desc = str(js.get("desc") or "").strip() or "empty desc from llm"
        score = self.label_to_score.get(label, 0.0)
        return {
            "score": score,
            "label": label,
            "desc": desc,
        }

    async def review_one_platform(self, payload: dict, platform: str, config: Dict[str, object]) -> Optional[dict]:
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

        emotion = await self.score_text(title=title, body=body)
        item = {
            "index": 0,
            "share_url": row.get("share_url"),
            "title": title,
            "body": body,
            **emotion,
        }

        label = str(item.get("label") or "")
        label_count = {"积极": 0, "中性": 0, "消极": 0}
        if label in label_count:
            label_count[label] = 1
            overall_label = label
        else:
            overall_label = "中性"
        overall_score = item.get("score")
        overall_desc = f"{item.get('desc') or ''}".strip()

        return {
            "platform": platform,
            "meta_list_key": meta_list_key,
            "overall_label": overall_label,
            "overall_score": overall_score,
            "overall_desc": overall_desc,
            "label_count": label_count,
            "reviewed_count": 1,
            "item_reviews": [item],
            "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "llm_model_id": self.llm_judge.model_id,
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
            if not files:
                continue

            for src in files:
                scanned += 1
                payload = await self.load_json_file(src)
                post_meta = PostMeta.from_dict(payload["post_meta"])
                print(post_meta)


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewTextEmotionReviewTaskV2(
        check_interval=60,
        platform_to_dirs=[
            ("douyin", "temp/banniu_37728/step_14_finished/douyin", "temp/banniu_37728/step_14_finished/douyin"),
        ],
        key_of_llm_base_url="POST_REVIEW_LLM_BASE_URL",
        key_of_llm_api_key="POST_REVIEW_LLM_API_KEY",
        key_of_llm_model_id="POST_REVIEW_LLM_MODEL_ID",
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
