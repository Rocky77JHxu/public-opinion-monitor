"""清洗处理结果模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.models.clean import CleanItem, DiscardedItem


class ProcessingResult(BaseModel):
    """一次清洗与去重任务的汇总结果。"""

    model_config = ConfigDict(extra="forbid")

    processing_run_id: UUID
    reference_time: datetime
    input_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    discarded_count: int = Field(ge=0)
    accepted_items: list[CleanItem]
    discarded_items: list[DiscardedItem]
