"""采集器通用接口与传输文档模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.models import HotSearchPlatform, RawItem


class HotSearchParseError(ValueError):
    """热搜响应无法解析或没有有效条目。"""


class HotSearchDocument(BaseModel):
    """解析器看到的平台响应快照。"""

    model_config = ConfigDict(extra="forbid")

    platform: HotSearchPlatform
    request_url: str = Field(pattern=r"^https?://")
    status_code: int = Field(ge=100, le=599)
    content_type: str | None = None
    body: str = Field(min_length=1)
    collected_at: datetime
    response_headers: dict[str, str] = Field(default_factory=dict)


class HotSearchParser(Protocol):
    """热搜平台解析器协议。"""

    platform: HotSearchPlatform

    def parse(self, document: HotSearchDocument) -> list[RawItem]:
        """把平台响应解析为统一原始条目。"""
        ...


__all__ = [
    "HotSearchDocument",
    "HotSearchParseError",
    "HotSearchParser",
]
