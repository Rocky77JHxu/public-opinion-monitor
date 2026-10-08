"""OpenAI-compatible Chat Completions 客户端。"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from opinion_monitor.config.schema import LLMConfig
from opinion_monitor.models import LLMUsage

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(ValueError):
    """LLM 请求或结构化输出错误。"""


def extract_json_content(content: str) -> Any:
    """解析模型输出，容许一个代码块包裹。"""

    text = content.strip()
    if text.startswith("```"):
        text = _JSON_FENCE.sub("", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型输出不是有效 JSON：{exc}") from exc


class LLMClient:
    """最小 OpenAI-compatible 客户端，不依赖厂商 SDK。"""

    def __init__(
        self,
        config: LLMConfig,
        *,
        env: Mapping[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._base_url = env[config.base_url_env].rstrip("/")
        self._api_key = env[config.api_key_env]
        self._model = env[config.model_env]
        self._transport = transport
        self._sleep = sleep

    @property
    def model(self) -> str:
        return self._model

    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[Any, LLMUsage]:
        if not self._base_url or not self._api_key or not self._model:
            raise LLMError("LLM base URL、API Key 或模型名称为空")

        request_body: dict[str, Any] = {
            "model": self._model,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self._config.enable_structured_output:
            request_body["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        attempts_allowed = 1 + self._config.max_retries
        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            transport=self._transport,
            trust_env=False,
        ) as client:
            last_error: Exception | None = None
            for attempt in range(1, attempts_allowed + 1):
                try:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=request_body,
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                else:
                    if 200 <= response.status_code < 300:
                        document = response.json()
                        choices = document.get("choices") or []
                        if not choices or not isinstance(choices, list):
                            raise LLMError("模型响应缺少 choices")
                        message = choices[0].get("message") or {}
                        content = message.get("content")
                        if not isinstance(content, str):
                            raise LLMError("模型响应缺少 message.content")
                        raw_usage = document.get("usage") or {}
                        usage = LLMUsage.model_validate(
                            {
                                "prompt_tokens": raw_usage.get("prompt_tokens"),
                                "completion_tokens": raw_usage.get("completion_tokens"),
                                "total_tokens": raw_usage.get("total_tokens"),
                            }
                        )
                        return extract_json_content(content), usage

                    last_error = LLMError(f"LLM HTTP 状态码异常：{response.status_code}")
                    if response.status_code not in _RETRYABLE_STATUS:
                        raise last_error

                if attempt < attempts_allowed:
                    await self._sleep(0.1 * attempt)

        raise LLMError(f"LLM 请求失败：{last_error}")
