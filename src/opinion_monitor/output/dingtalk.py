"""钉钉自动化 Webhook Payload 构建与投递客户端。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from opinion_monitor.collectors.hotsearch.http import HotSearchHTTPError, validate_public_url
from opinion_monitor.config.schema import RootConfig
from opinion_monitor.models import (
    DingTalkAutomationPayload,
    DingTalkDeliveryAttempt,
    DingTalkDeliveryRecord,
    DingTalkDeliveryResult,
    StructuredOutputEvent,
    utc_now,
)

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_TEXT_LENGTH = 8000
_PHONE = re.compile(
    r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)",
)
_ID_CARD = re.compile(
    r"(?<!\d)\d{6}(?:19|20)\d{2}"
    r"(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])\d{3}[\dXx](?!\d)"
)
_USER_ID_KEY = re.compile(r"(?:user.?id|author.?id)", re.IGNORECASE)


class DingTalkOutputError(RuntimeError):
    """钉钉产出构建或投递失败。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass(slots=True)
class _PreparedOutput:
    payload: dict[str, Any]
    payload_json: str
    payload_hash: str


class DingTalkWebhookClient:
    """带公共地址校验、超时与重试的钉钉 Webhook 客户端。"""

    def __init__(
        self,
        config: RootConfig,
        *,
        env: Mapping[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        resolver: Callable[[str], list[Any]] | None = None,
    ) -> None:
        self._config = config
        self._url = env.get(config.output.dingtalk.webhook_url_env, "")
        self._transport = transport
        self._sleep = sleep
        if resolver is None:
            self._url_validator: Callable[[str], None] = validate_public_url
        else:

            def validate(url: str) -> None:
                addresses = resolver(urlparse_hostname(url))
                if not addresses:
                    raise DingTalkOutputError("Webhook 域名没有解析到 IP 地址")
                from ipaddress import ip_address

                for raw_address in addresses:
                    address = ip_address(raw_address)
                    if (
                        address.is_private
                        or address.is_loopback
                        or address.is_link_local
                        or address.is_unspecified
                        or address.is_multicast
                        or address.is_reserved
                    ):
                        raise DingTalkOutputError(f"Webhook URL 解析到禁止访问的地址：{address}")

            self._url_validator = validate

    async def post(self, payload: Mapping[str, Any]) -> tuple[int, str]:
        """发送 Payload；返回 HTTP 状态码与响应体。"""

        if not self._url:
            raise DingTalkOutputError("钉钉 Webhook URL 为空")
        if self._url == "replace-me":
            raise DingTalkOutputError("钉钉 Webhook URL 仍是占位符，请更新 .env")
        if not self._config.security.allow_private_network:
            try:
                self._url_validator(self._url)
            except HotSearchHTTPError as exc:
                message = str(exc).replace("热搜 URL", "钉钉 Webhook URL")
                message = message.replace("热搜域名", "钉钉 Webhook 域名")
                raise DingTalkOutputError(message) from exc

        attempts_allowed = 1 + self._config.output.dingtalk.max_retries
        last_error: DingTalkOutputError | None = None
        async with httpx.AsyncClient(
            timeout=self._config.output.dingtalk.timeout_seconds,
            transport=self._transport,
            verify=self._config.security.validate_ssl,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            for attempt in range(1, attempts_allowed + 1):
                try:
                    response = await client.post(
                        self._url,
                        headers={"Content-Type": "application/json"},
                        json=dict(payload),
                    )
                except httpx.HTTPError as exc:
                    last_error = DingTalkOutputError(f"钉钉 Webhook 请求失败：{exc}")
                else:
                    body = response.text
                    if 200 <= response.status_code < 300:
                        _validate_webhook_body(response.status_code, body)
                        return response.status_code, body[:_MAX_TEXT_LENGTH]

                    last_error = DingTalkOutputError(
                        f"钉钉 Webhook HTTP 状态码异常：{response.status_code}",
                        status_code=response.status_code,
                        response_body=_clip_text(body),
                    )
                    if response.status_code not in _RETRYABLE_STATUS:
                        raise last_error

                if attempt < attempts_allowed:
                    await self._sleep(self._config.output.dingtalk.retry_backoff_seconds)

        raise DingTalkOutputError(f"钉钉 Webhook 请求失败：{last_error}")


def urlparse_hostname(url: str) -> str:
    """从 URL 提取 hostname，供测试注入解析器。"""

    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.hostname:
        raise DingTalkOutputError(f"Webhook URL 无效：{url}")
    return parsed.hostname


def _validate_webhook_body(status_code: int, body: str) -> None:
    text = body.strip()
    if not text:
        return
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        if text.lower() in {"ok", "success"}:
            return
        raise DingTalkOutputError(
            "钉钉 Webhook 响应不是有效 JSON",
            status_code=status_code,
            response_body=_clip_text(body),
        ) from None
    if not isinstance(document, dict):
        raise DingTalkOutputError(
            "钉钉 Webhook 响应根节点不是对象",
            status_code=status_code,
            response_body=_clip_text(body),
        )

    errcode = document.get("errcode")
    if isinstance(errcode, str) and errcode.isdigit():
        errcode = int(errcode)
    if isinstance(errcode, int) and errcode != 0:
        raise DingTalkOutputError(
            f"钉钉 Webhook 返回业务错误：{errcode} {document.get('errmsg')}",
            status_code=status_code,
            response_body=_clip_text(body),
        )

    code = document.get("code")
    if isinstance(code, str) and code.isdigit():
        code = int(code)
    if isinstance(code, int) and code != 0:
        raise DingTalkOutputError(
            f"钉钉 Webhook 返回业务错误：{code} {document.get('message')}",
            status_code=status_code,
            response_body=_clip_text(body),
        )

    if document.get("success") is False:
        raise DingTalkOutputError(
            f"钉钉 Webhook 返回失败：{document.get('message') or document.get('msg')}",
            status_code=status_code,
            response_body=_clip_text(body),
        )
    status = document.get("status")
    if isinstance(status, str) and status.lower() in {"fail", "failed", "error"}:
        raise DingTalkOutputError(
            f"钉钉 Webhook 返回失败状态：{status}",
            status_code=status_code,
            response_body=_clip_text(body),
        )


def _clip_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:_MAX_TEXT_LENGTH]


def _sanitize_value(value: Any, key: str = "") -> Any:
    if isinstance(value, str):
        if _USER_ID_KEY.fullmatch(key):
            return "***"
        result = _PHONE.sub("[手机号]", value)
        return _ID_CARD.sub("[身份证号]", result)
    if isinstance(value, list):
        return [_sanitize_value(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _sanitize_value(item, str(name)) for name, item in value.items()}
    return value


def sanitize_event(event: StructuredOutputEvent) -> StructuredOutputEvent:
    """按安全配置脱敏结构化事件。"""

    document = _sanitize_value(event.model_dump(mode="json"))
    return StructuredOutputEvent.model_validate(document)


def _compact_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _markdown_text(event: StructuredOutputEvent, keyword: str) -> str:
    url = event.url or "未提供来源链接"
    if event.url:
        url = f"[查看来源]({event.url})"
    lines = [
        f"### {keyword}｜{event.alert_level_label}",
        "",
        f"**标题：**{_inline_text(event.title)}",
        f"- 综合得分：{event.overall_score:.2f}",
        f"- 预警属性：{event.category.value}",
        f"- 来源平台：{event.platform}",
        f"- 事件 ID：`{event.event_id}`",
        "",
        f"**摘要：**{_inline_text(event.summary)}",
        "",
    ]
    if event.sentiment_summary:
        lines.extend([f"**情感：**{_inline_text(event.sentiment_summary)}", ""])
    if event.key_risk_factors:
        lines.append("**关键风险因素：**")
        lines.extend(f"- {_inline_text(item)}" for item in event.key_risk_factors)
        lines.append("")
    if event.recommended_actions:
        lines.append("**建议动作：**")
        lines.extend(f"- {_inline_text(item)}" for item in event.recommended_actions)
        lines.append("")
    lines.append(f"**追踪：**`{event.trace_id}`")
    lines.append(url)
    return "\n".join(lines)


def _inline_text(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()


class DingTalkOutputService:
    """构建钉钉 Payload，并执行 dry-run 或真实投递。"""

    def __init__(
        self,
        config: RootConfig,
        *,
        env: Mapping[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._env = env
        self._transport = transport
        self._sleep = sleep

    def prepare(self, event: StructuredOutputEvent) -> _PreparedOutput:
        safe_event = sanitize_event(event)
        mode = self._config.output.dingtalk.send_mode
        if mode == "automation_json":
            automation = DingTalkAutomationPayload(
                keyword=self._config.output.dingtalk.trigger_keyword,
                event_id=safe_event.event_id,
                trace_id=safe_event.trace_id,
                dedup_key=str(safe_event.event_id),
                occurred_at=safe_event.created_at,
                data=safe_event,
            )
            payload: dict[str, Any] = automation.model_dump(mode="json")
        else:
            title = (
                f"{self._config.output.dingtalk.trigger_keyword}｜"
                f"{safe_event.alert_level_label}｜{_inline_text(safe_event.title)}"
            )
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": _markdown_text(
                        safe_event,
                        self._config.output.dingtalk.trigger_keyword,
                    ),
                },
            }

        payload_json = _compact_json(payload)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        return _PreparedOutput(payload, payload_json, payload_hash)

    async def deliver(
        self,
        event: StructuredOutputEvent,
        *,
        dry_run: bool,
        attempt_offset: int = 0,
    ) -> DingTalkDeliveryResult:
        prepared = self.prepare(event)
        output_config = self._config.output.dingtalk
        level_config = output_config.levels[event.alert_level]
        now = utc_now()

        def build_record(
            status: str,
            *,
            attempt_count: int,
            response_status_code: int | None = None,
            response_body: str | None = None,
            error: str | None = None,
        ) -> DingTalkDeliveryRecord:
            return DingTalkDeliveryRecord(
                event_id=event.event_id,
                clean_item_id=event.clean_item_id,
                alert_level=event.alert_level,
                send_mode=output_config.send_mode,
                status=status,  # type: ignore[arg-type]
                attempt_count=attempt_count,
                immediate=level_config.immediate,
                dry_run=dry_run,
                payload_hash=prepared.payload_hash,
                payload_json=prepared.payload_json,
                response_status_code=response_status_code,
                response_body=_clip_text(response_body),
                error=error,
                created_at=now,
                updated_at=utc_now(),
            )

        if not output_config.enabled or not level_config.enabled:
            reason = (
                "钉钉产出全局开关未启用"
                if not output_config.enabled
                else f"预警级别 {event.alert_level.value} 未启用钉钉产出"
            )
            record = build_record("skipped", attempt_count=attempt_offset)
            record = record.model_copy(update={"error": reason})
            return DingTalkDeliveryResult(
                event_id=event.event_id,
                status="skipped",
                record=record,
                payload=prepared.payload,
            )

        def build_attempt(
            status: str,
            *,
            response_status_code: int | None = None,
            response_body: str | None = None,
            error: str | None = None,
        ) -> DingTalkDeliveryAttempt:
            return DingTalkDeliveryAttempt(
                event_id=event.event_id,
                attempt_number=attempt_offset + 1,
                status=status,  # type: ignore[arg-type]
                dry_run=dry_run,
                payload_hash=prepared.payload_hash,
                response_status_code=response_status_code,
                response_body=_clip_text(response_body),
                error=error,
                started_at=now,
                completed_at=utc_now(),
            )

        if dry_run:
            attempt = build_attempt("dry_run")
            record = build_record(
                "dry_run",
                attempt_count=attempt.attempt_number,
            )
            return DingTalkDeliveryResult(
                event_id=event.event_id,
                status="dry_run",
                record=record,
                attempt=attempt,
                payload=prepared.payload,
            )

        client = DingTalkWebhookClient(
            self._config,
            env=self._env,
            transport=self._transport,
            sleep=self._sleep,
        )
        try:
            status_code, response_body = await client.post(prepared.payload)
        except DingTalkOutputError as exc:
            attempt = build_attempt(
                "failed",
                response_status_code=exc.status_code,
                response_body=exc.response_body,
                error=str(exc),
            )
            record = build_record(
                "failed",
                attempt_count=attempt.attempt_number,
                response_status_code=exc.status_code,
                response_body=exc.response_body,
                error=str(exc),
            )
            return DingTalkDeliveryResult(
                event_id=event.event_id,
                status="failed",
                record=record,
                attempt=attempt,
                payload=prepared.payload,
            )

        attempt = build_attempt(
            "succeeded",
            response_status_code=status_code,
            response_body=response_body,
        )
        record = build_record(
            "succeeded",
            attempt_count=attempt.attempt_number,
            response_status_code=status_code,
            response_body=response_body,
        )
        return DingTalkDeliveryResult(
            event_id=event.event_id,
            status="succeeded",
            record=record,
            attempt=attempt,
            payload=prepared.payload,
        )
