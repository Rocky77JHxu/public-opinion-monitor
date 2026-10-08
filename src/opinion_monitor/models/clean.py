"""清洗与研判前处理条目模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.models.enums import AlertCategory, HotSearchPlatform, MediaCrawlerPlatform


class CleanItem(BaseModel):
    """通过日期过滤与去重后的标准化条目。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    raw_item_id: UUID
    source_raw_item_ids: list[UUID]
    source_type: str
    platform: HotSearchPlatform | MediaCrawlerPlatform
    external_id: str | None = None
    title: str = Field(min_length=1)
    content: str | None = None
    canonical_url: str | None = None
    url_hash: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    published_at: datetime | None = None
    collected_at: datetime
    engagement: dict[str, int] = Field(default_factory=dict)
    keyword: str | None = None
    keyword_level: int | None = Field(default=None, ge=1)
    account_config_id: str | None = None
    simhash: str
    title_hash: str
    content_hash: str
    preliminary_category: AlertCategory
    preliminary_category_confidence: float = Field(ge=0, le=1)
    preliminary_category_reason: str
    collector_version: str = Field(min_length=1)


class DiscardedItem(BaseModel):
    """清洗阶段被丢弃的原始条目及原因。"""

    model_config = ConfigDict(extra="forbid")

    raw_item_id: UUID
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class CommentRecord(BaseModel):
    """从 MediaCrawler 评论 JSONL 加载的评论证据。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    task_id: UUID
    platform: MediaCrawlerPlatform
    note_external_id: str = Field(min_length=1)
    external_comment_id: str = Field(min_length=1)
    parent_comment_id: str | None = None
    content: str = Field(min_length=1)
    author_id: str | None = None
    author_name: str | None = None
    published_at: datetime | None = None
    collected_at: datetime
    like_count: int | None = Field(default=None, ge=0)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    collector_version: str = Field(min_length=1)
