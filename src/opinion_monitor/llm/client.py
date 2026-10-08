"""OpenAI-compatible Responses API 结构化输出客户端。"""

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
_SCHEMA_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class LLMError(ValueError):
    """LLM 请求或结构化输出错误。"""


def extract_json_content(content: str) -> Any:
    """解析模型输出；宽松模式仍容许一个 Markdown 代码块。"""

    text = content.strip()
    if text.startswith("```"):
        text = _JSON_FENCE.sub("", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型输出不是有效 JSON：{exc}") from exc


def extract_response_text(document: dict[str, Any]) -> str:
    """从 Responses API 文档提取 output_text，并显式暴露未完成/拒答状态。"""

    status = document.get("status", "completed")
    if status == "incomplete":
        details = document.get("incomplete_details") or {}
        reason = details.get("reason") if isinstance(details, Mapping) else None
        raise LLMError(f"模型响应未完成：{reason or 'unknown'}")
    if status != "completed":
        raise LLMError(f"模型响应状态异常：{status}")

    top_level_refusal = document.get("refusal")
    if isinstance(top_level_refusal, str) and top_level_refusal:
        raise LLMError(f"模型拒绝响应：{top_level_refusal}")

    texts: list[str] = []
    output_text = document.get("output_text")
    if isinstance(output_text, str):
        if not output_text.strip():
            raise LLMError("模型响应缺少 output_text")
        return output_text

    output_items = document.get("output") or []
    if not isinstance(output_items, list):
        raise LLMError("模型响应 output 不是数组")

    for item in output_items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        item_refusal = item.get("refusal")
        if item_type == "refusal" or (isinstance(item_refusal, str) and item_refusal):
            raise LLMError(f"模型拒绝响应：{item_refusal or 'unknown'}")
        if item_type != "message":
            continue
        content = item.get("content") or []
        if isinstance(content, str):
            content = [{"type": "output_text", "text": content}]
        if not isinstance(content, list):
            raise LLMError("模型响应 message.content 不是数组")
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "refusal":
                refusal = part.get("refusal")
                raise LLMError(f"模型拒绝响应：{refusal or 'unknown'}")
            if part_type == "output_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])

    text = "".join(texts).strip()
    if not text:
        raise LLMError("模型响应缺少 output_text")
    return text


def _usage_from_response(document: Mapping[str, Any]) -> LLMUsage:
    """兼容 Responses API 的 input/output tokens 与 Chat Completions 字段。"""

    usage = document.get("usage") or {}
    if not isinstance(usage, Mapping):
        raise LLMError("模型响应 usage 不是对象")

    prompt_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    completion_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    total_tokens = usage.get("total_tokens")
    if (
        total_tokens is None
        and isinstance(prompt_tokens, int)
        and isinstance(completion_tokens, int)
    ):
        total_tokens = prompt_tokens + completion_tokens
    return LLMUsage.model_validate(
        {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
    )


def _validate_strict_schema_node(schema: Mapping[str, Any]) -> None:
    """递归检查 Structured Outputs 的关键约束，避免上游 400。"""

    schema_type = schema.get("type")
    types = schema_type if isinstance(schema_type, list) else [schema_type]
    if "object" in types:
        if schema.get("additionalProperties") is not False:
            raise LLMError("结构化输出对象必须设置 additionalProperties=false")
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, dict) or not properties:
            raise LLMError("结构化输出 properties 必须是非空对象")
        if not isinstance(required, list):
            raise LLMError("结构化输出 required 必须是数组")
        if set(properties) != set(required):
            raise LLMError("结构化输出 required 必须覆盖 properties 的全部字段")
        for child in properties.values():
            if isinstance(child, Mapping):
                _validate_strict_schema_node(child)
    if "array" in types:
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise LLMError("结构化输出数组必须定义 items")
        _validate_strict_schema_node(items)


def _validate_strict_schema(schema: Mapping[str, Any]) -> None:
    """在请求前检查根节点与所有嵌套节点的严格输出约束。"""

    if schema.get("type") != "object":
        raise LLMError("结构化输出根节点 type 必须是 object")
    _validate_strict_schema_node(schema)


class LLMClient:
    """最小 OpenAI-compatible Responses 客户端，不依赖厂商 SDK。"""

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
        schema_name: str,
        response_schema: Mapping[str, Any],
    ) -> tuple[Any, LLMUsage]:
        """调用 Responses API 并返回 JSON 对象与用量。"""

        if not self._base_url or not self._api_key or not self._model:
            raise LLMError("LLM base URL、API Key 或模型名称为空")
        if not _SCHEMA_NAME.fullmatch(schema_name):
            raise LLMError("结构化输出 schema_name 只能包含字母、数字、下划线和中划线")
        if not isinstance(response_schema, Mapping):
            raise LLMError("response_schema 必须是 JSON Schema 对象")

        if self._config.enable_structured_output:
            _validate_strict_schema(response_schema)
            output_format: dict[str, Any] = {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": dict(response_schema),
            }
        else:
            output_format = {"type": "json_object"}

        request_body: dict[str, Any] = {
            "model": self._model,
            "temperature": self._config.temperature,
            "max_output_tokens": self._config.max_output_tokens,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "text": {"format": output_format},
        }
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
                        f"{self._base_url}/responses",
                        headers=headers,
                        json=request_body,
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                else:
                    if 200 <= response.status_code < 300:
                        try:
                            document = response.json()
                        except ValueError as exc:
                            raise LLMError("模型响应不是有效 JSON 文档") from exc
                        if not isinstance(document, dict):
                            raise LLMError("模型响应根节点不是对象")
                        content = extract_response_text(document)
                        return extract_json_content(content), _usage_from_response(document)

                    last_error = LLMError(f"LLM HTTP 状态码异常：{response.status_code}")
                    if response.status_code not in _RETRYABLE_STATUS:
                        raise last_error

                if attempt < attempts_allowed:
                    await self._sleep(0.1 * attempt)

        raise LLMError(f"LLM 请求失败：{last_error}")
