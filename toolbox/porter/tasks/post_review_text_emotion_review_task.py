#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import logging
from pathlib import Path
import traceback
from typing import Dict, List, Tuple

logger = logging.getLogger("toolbox")

from project_settings import environment
from toolbox.porter.llm import AsyncLLMAsJudge
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.porter.entity.post_meta import PostMeta
from toolbox.porter.entity.post_review import PostReview


EMOTION_SYSTEM_PROMPT = """
## 背景
公司为推广新的产品让购买过产品的用户在社交媒体上发分享贴子，审核通过后给用户送礼品。

## 任务
现在我们需要对贴子中文字的部分进行情感判断，以确定它是不是正向积极的内容而不是不利于品牌的消积内容。
我们将情感定为：积极，中性，消极。

## 注意
（1）标题或描述太短或语义不全，无法判断情感时，给中性。并描述：“内容少太，无法判断情感。”

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


@BaseTask.register("post_review_text_emotion_review")
class PostReviewTextEmotionReviewTask(BaseTask, TaskJsonUtils):
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
            system_prompt=EMOTION_SYSTEM_PROMPT,
        )

    async def score_text(self, title: str, desc: str) -> Dict[str, object]:
        user_prompt = f"标题：\n{title or ''}\n正文：\n{desc or ''}".strip()
        js = await self.llm_judge.complete_json(user_prompt)
        return {
            "label": js["label"],
            "desc": js["desc"],
        }

    async def process_one_file(self, task_file: Path, target_dir: Path):
        payload = await self.load_json_file(task_file)
        post_meta = PostMeta.from_dict(payload["post_meta"])
        post_review = PostReview.from_dict(payload.get("post_review", dict()))

        if len(post_meta.title) == 0 and len(post_meta.desc) == 0:
            label = "中性"
            desc = "标题和内容都为空。"
        else:
            js = await self.score_text(
                title=post_meta.title,
                desc=post_meta.desc,
            )
            label = js["label"]
            desc = js["desc"]
        post_review.review_text.emotion_label = label
        post_review.review_text.emotion_desc = desc

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
                try:
                    dst = await self.process_one_file(src, target_dir)
                except Exception as error:
                    logger.info(f"{self.flag}任务失败: {src.as_posix()}，error type: {type(error)}, error text: {str(error)}, traceback: {traceback.format_exc()}")
                    continue
                logger.info(f"{self.flag}任务流转并补充元信息成功: {dst.as_posix()}")


def main():
    import log
    from project_settings import log_directory

    log.setup_size_rotating(log_directory=log_directory)

    task = PostReviewTextEmotionReviewTask(
        check_interval=60,
        platform_to_dirs=[
            ("douyin", "temp/banniu_37728_v2/step_4_post_review_duplicate_review/douyin", "temp/banniu_37728_v2/step_5_1_post_review_text_emotion_review/douyin"),
        ],
        key_of_llm_base_url="POST_REVIEW_LLM_BASE_URL",
        key_of_llm_api_key="POST_REVIEW_LLM_API_KEY",
        key_of_llm_model_id="POST_REVIEW_LLM_MODEL_ID",
    )
    asyncio.run(task.do_task())


if __name__ == "__main__":
    main()
