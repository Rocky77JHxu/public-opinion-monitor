"""钉钉产出 Payload 与投递台账模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.models.enums import AlertLevel
from opinion_monitor.models.scoring import StructuredOutputEvent

DingTalkSendMode = Literal["automation_json", "markdown"]
DingTalkDeliveryStatus = Literal[
    "running",
    "succeeded",
    "failed",
    "dry_run",
    "skipped",
]
DingTalkAttemptStatus = Literal["succeeded", "failed", "dry_run"]


class DingTalkAutomationPayload(BaseModel):
    """钉钉自动化 Webhook 的通用 JSON 事件契约。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    event_type: str = Field(default="opinion_monitor.alert", min_length=1)
    keyword: str = Field(min_length=1)
    event_id: UUID
    trace_id: UUID
    dedup_key: str = Field(min_length=1)
    occurred_at: datetime
    data: StructuredOutputEvent


class DingTalkDeliveryRecord(BaseModel):
    """一个结构化事件的钉钉投递状态。"""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    clean_item_id: UUID
    alert_level: AlertLevel
    send_mode: DingTalkSendMode
    status: DingTalkDeliveryStatus
    attempt_count: int = Field(ge=0)
    immediate: bool
    dry_run: bool
    payload_hash: str = Field(min_length=16)
    payload_json: str = Field(min_length=1)
    response_status_code: int | None = None
    response_body: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class DingTalkDeliveryAttempt(BaseModel):
    """一次具体请求或一次 dry-run 的审计记录。"""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    attempt_number: int = Field(ge=1)
    status: DingTalkAttemptStatus
    dry_run: bool
    payload_hash: str = Field(min_length=16)
    response_status_code: int | None = None
    response_body: str | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime


class DingTalkDeliveryResult(BaseModel):
    """一次产出执行的返回结果。"""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    status: DingTalkDeliveryStatus
    record: DingTalkDeliveryRecord
    attempt: DingTalkDeliveryAttempt | None = None
    payload: dict[str, Any]
