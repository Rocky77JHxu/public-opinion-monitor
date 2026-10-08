"""MediaCrawler 任务、命令与结果模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.models import MediaCrawlerPlatform, RawItem

PositiveFloat = Annotated[float, Field(gt=0)]


class MediaCrawlerTask(BaseModel):
    """一次 MediaCrawler 任务的稳定定义。"""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    source_type: Literal["keyword_search", "account"]
    platform: MediaCrawlerPlatform
    crawl_type: Literal["search", "creator", "detail"]
    target: str = Field(min_length=1)
    keyword_level: int | None = Field(default=None, ge=1)
    account_config_id: str | None = None
    max_items: int = Field(ge=1)
    max_comments: int = Field(ge=0)
    timeout_seconds: int = Field(ge=1)
    workspace_dir: str = Field(min_length=1)
    input_file: str = Field(min_length=1)
    output_file: str = Field(min_length=1)


class MediaCrawlerCommandPlan(BaseModel):
    """隔离子进程命令计划。"""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    cwd: str
    argv: list[str] = Field(min_length=1)
    input_file: str
    output_file: str
    stdout_file: str
    stderr_file: str
    timeout_seconds: int = Field(ge=1)
    watchdog_enabled: bool
    watchdog_poll_seconds: PositiveFloat


class MediaCrawlerRunStatus(StrEnum):
    SKIPPED = "skipped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class MediaCrawlerRunResult(BaseModel):
    """一次任务执行结果。"""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: MediaCrawlerRunStatus
    started_at: datetime
    completed_at: datetime
    return_code: int | None = None
    error: str | None = None
    stopped_by_watchdog: bool = False
    watchdog_content_count: int | None = Field(default=None, ge=0)


class MediaCrawlerLoadContext(BaseModel):
    """JSONL 加载上下文。"""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    platform: MediaCrawlerPlatform
    source_type: Literal["keyword_search", "account"]
    keyword: str | None = None
    keyword_level: int | None = Field(default=None, ge=1)
    account_config_id: str | None = None


class MediaCrawlerLoadError(BaseModel):
    """单行解析失败记录。"""

    model_config = ConfigDict(extra="forbid")

    line_number: int = Field(ge=1)
    reason: str


class MediaCrawlerLoadResult(BaseModel):
    """JSONL 文件加载结果。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    total_lines: int = Field(ge=0)
    loaded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    items: list[RawItem]
    errors: list[MediaCrawlerLoadError]


class MediaCrawlerIntegrationResult(BaseModel):
    """一次 MediaCrawler 任务的执行与结果加载汇总。"""

    model_config = ConfigDict(extra="forbid")

    task: MediaCrawlerTask
    command: MediaCrawlerCommandPlan
    run: MediaCrawlerRunResult
    output_files: list[str]
    load_results: list[MediaCrawlerLoadResult]
    items: list[RawItem]
