"""采集后进入系统内部边界的原始条目模型。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from opinion_monitor.models.enums import HotSearchPlatform, MediaCrawlerPlatform


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(UTC)


class RawItem(BaseModel):
    """统一原始条目。

    当前 Phase 2 首先接入热搜来源；`source_type` 预留关键词检索与账号检索，
    避免后续 MediaCrawler 接入时破坏模型边界。
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_type: Literal[
        "hotsearch",
        "keyword_search",
        "account",
    ]
    platform: HotSearchPlatform | MediaCrawlerPlatform
    external_id: str | None = None
    title: str = Field(min_length=1)
    content: str | None = None
    url: str | None = Field(default=None, pattern=r"^https?://")
    author_id: str | None = None
    author_name: str | None = None
    published_at: datetime | None = None
    collected_at: datetime
    rank: int | None = Field(default=None, ge=1)
    hot_value: int | None = Field(default=None, ge=0)
    engagement: dict[str, int] = Field(default_factory=dict)
    keyword: str | None = None
    keyword_level: int | None = Field(default=None, ge=1)
    account_config_id: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    collector_version: str = Field(min_length=1)

    @field_validator("collected_at", "published_at")
    @classmethod
    def check_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            msg = "时间字段必须带时区信息"
            raise ValueError(msg)
        return value
