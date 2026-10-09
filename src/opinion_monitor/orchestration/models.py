"""端到端编排与调度结果模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.models import HotSearchPlatform

PipelineStageName = Literal[
    "hotsearch",
    "mediacrawler",
    "processing",
    "llm_analysis",
    "risk_scoring",
    "dingtalk_output",
]

ExecutionStatus = Literal["succeeded", "partial", "failed", "skipped"]


class PipelineStageResult(BaseModel):
    """端到端流水线中一个阶段的执行结果。"""

    model_config = ConfigDict(extra="forbid")

    stage: PipelineStageName
    status: ExecutionStatus
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class PipelineRunResult(BaseModel):
    """一次端到端流水线执行结果。"""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    executed: bool
    status: ExecutionStatus
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    stages: list[PipelineStageResult]
    storage_stats: dict[str, int] = Field(default_factory=dict)


SchedulerSourceKind = Literal["hotsearch", "keyword_search", "account"]


class ScheduledSource(BaseModel):
    """一个可独立调度的采集来源。"""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    kind: SchedulerSourceKind
    label: str = Field(min_length=1)
    interval_seconds: int = Field(ge=1)
    jitter_min_seconds: int = Field(ge=0)
    jitter_max_seconds: int = Field(ge=0)
    hotsearch_platform: HotSearchPlatform | None = None
    keyword_level_name: str | None = None
    keyword_level: int | None = Field(default=None, ge=1)
    account_config_id: str | None = None


class SchedulerSourceRun(BaseModel):
    """一个调度来源在当前周期内的执行结果。"""

    model_config = ConfigDict(extra="forbid")

    source_key: str
    source_kind: SchedulerSourceKind
    status: ExecutionStatus
    started_at: datetime
    completed_at: datetime
    pipeline_result: PipelineRunResult
    next_run_at: datetime


class SchedulerCycleResult(BaseModel):
    """一次调度周期的采集与后续处理结果。"""

    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    executed: bool
    status: ExecutionStatus
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    source_runs: list[SchedulerSourceRun] = Field(default_factory=list)
    downstream_result: PipelineRunResult | None = None
    idle_seconds: float | None = None
