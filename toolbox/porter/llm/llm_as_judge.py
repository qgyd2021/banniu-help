#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import re
from typing import Any, Optional

from openai import AsyncOpenAI, OpenAI


class LLMAsJudge(object):
    """
    OpenAI 兼容 Chat Completions：传入用户侧字符串，将助手回复解析为 JSON（任意合法 JSON 根类型）。
    不做业务层校验；最近一次助手原文可通过 ``last_assistant_text`` 读取。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_id: str,
        system_prompt: str = "",
        temperature: float = 0.2,
        top_p: float = 0.8,
    ):
        self._model_id = model_id
        self._system_prompt = (system_prompt or "").strip()
        self._temperature = temperature
        self._top_p = top_p
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._last_assistant_text: Optional[str] = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def last_assistant_text(self) -> Optional[str]:
        return self._last_assistant_text

    @staticmethod
    def parse_model_text_to_json(text: str) -> Any:
        if text is None:
            raise ValueError("model output is None")
        s = text.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, flags=re.IGNORECASE)
        if fence:
            s = fence.group(1).strip()
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1]
        return json.loads(s)

    def complete_json(self, user_message: str) -> Any:
        messages = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.append({"role": "user", "content": user_message})

        completion = self._client.chat.completions.create(
            model=self._model_id,
            messages=messages,
            temperature=self._temperature,
            top_p=self._top_p,
        )
        content = (completion.choices[0].message.content or "").strip()
        self._last_assistant_text = content
        return self.parse_model_text_to_json(content)


class AsyncLLMAsJudge(object):
    """
    LLMAsJudge 的异步版本：接口保持一致，调用端可直接 await complete_json。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_id: str,
        system_prompt: str = "",
        temperature: float = 0.2,
        top_p: float = 0.8,
    ):
        self._model_id = model_id
        self._system_prompt = (system_prompt or "").strip()
        self._temperature = temperature
        self._top_p = top_p
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._last_assistant_text: Optional[str] = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def last_assistant_text(self) -> Optional[str]:
        return self._last_assistant_text

    @staticmethod
    def parse_model_text_to_json(text: str) -> Any:
        return LLMAsJudge.parse_model_text_to_json(text)

    async def complete_json(self, user_message: str) -> Any:
        messages = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.append({"role": "user", "content": user_message})

        completion = await self._client.chat.completions.create(
            model=self._model_id,
            messages=messages,
            temperature=self._temperature,
            top_p=self._top_p,
        )
        content = (completion.choices[0].message.content or "").strip()
        self._last_assistant_text = content
        return self.parse_model_text_to_json(content)
