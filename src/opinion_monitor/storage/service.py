"""MediaCrawler 任务结果入库与清洗编排。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerCommentLoadResult,
    MediaCrawlerLoadResult,
    MediaCrawlerTask,
)
from opinion_monitor.collectors.mediacrawler.result_loader import (
    discover_jsonl_files,
    load_comment_jsonl,
    load_jsonl,
)
from opinion_monitor.config.schema import RootConfig
from opinion_monitor.models import ProcessingResult, utc_now
from opinion_monitor.processing import CleaningPipeline
from opinion_monitor.storage.database import SqliteStorage


class Phase4IngestSummary(BaseModel):
    """Phase 4 入库与清洗汇总。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    workspace_dir: str
    database_path: str
    content_files: list[str]
    comment_files: list[str]
    content_loads: list[MediaCrawlerLoadResult]
    comment_loads: list[MediaCrawlerCommentLoadResult]
    raw_inserted: int = Field(ge=0)
    comments_inserted: int = Field(ge=0)
    processing: ProcessingResult
    storage_stats: dict[str, int]


def _is_content_file(path: Path) -> bool:
    name = path.name.lower()
    return "content" in name and "comment" not in name


def _is_comment_file(path: Path) -> bool:
    return "comment" in path.name.lower()


def ingest_and_process_media_crawler_task(
    config: RootConfig,
    task: MediaCrawlerTask,
    *,
    storage: SqliteStorage | None = None,
    process: bool = True,
) -> Phase4IngestSummary:
    """加载任务输出、持久化原始数据，并按需执行清洗。"""

    if config.storage.backend != "sqlite":
        message = "Phase 4 当前仅实现 SQLite；请在 storage.backend 中使用 sqlite"
        raise ValueError(message)
    repository = storage or SqliteStorage(config.storage.sqlite.path)
    repository.initialise()
    repository.save_media_crawler_task(task)

    from opinion_monitor.collectors.mediacrawler.models import MediaCrawlerLoadContext

    context = MediaCrawlerLoadContext(
        task_id=task.task_id,
        platform=task.platform,
        source_type=task.source_type,
        keyword=task.target if task.source_type == "keyword_search" else None,
        keyword_level=task.keyword_level,
        account_config_id=task.account_config_id,
    )

    workspace = Path(task.workspace_dir)
    files = discover_jsonl_files(workspace)
    content_files = [path for path in files if _is_content_file(path)]
    comment_files = [path for path in files if _is_comment_file(path)]

    content_loads = [load_jsonl(path, context, limit=task.max_items) for path in content_files]
    comment_loads = [load_comment_jsonl(path, context) for path in comment_files]

    raw_items = [item for result in content_loads for item in result.items]
    comments = [comment for result in comment_loads for comment in result.comments]
    raw_inserted = repository.save_raw_items(raw_items)
    comments_inserted = repository.save_comments(comments)

    pending = repository.list_pending_raw_items()
    existing = repository.list_clean_items()
    processing: ProcessingResult
    if process:
        processing = CleaningPipeline(config.processing, config.rules).run(
            pending,
            existing_items=existing,
        )
        repository.save_processing_result(processing)
    else:
        processing = ProcessingResult(
            processing_run_id=task.task_id,
            reference_time=utc_now(),
            input_count=0,
            accepted_count=0,
            discarded_count=0,
            accepted_items=[],
            discarded_items=[],
        )

    return Phase4IngestSummary(
        task_id=str(task.task_id),
        workspace_dir=task.workspace_dir,
        database_path=str(repository.path),
        content_files=[path.as_posix() for path in content_files],
        comment_files=[path.as_posix() for path in comment_files],
        content_loads=content_loads,
        comment_loads=comment_loads,
        raw_inserted=raw_inserted,
        comments_inserted=comments_inserted,
        processing=processing,
        storage_stats=repository.stats(),
    )


def process_pending_items(
    config: RootConfig,
    *,
    storage: SqliteStorage | None = None,
) -> ProcessingResult:
    """处理数据库中尚无决策记录的全部原始条目。"""

    if config.storage.backend != "sqlite":
        message = "Phase 4 当前仅实现 SQLite；请在 storage.backend 中使用 sqlite"
        raise ValueError(message)
    repository = storage or SqliteStorage(config.storage.sqlite.path)
    repository.initialise()
    pending = repository.list_pending_raw_items()
    existing = repository.list_clean_items()
    result = CleaningPipeline(config.processing, config.rules).run(
        pending,
        existing_items=existing,
    )
    repository.save_processing_result(result)
    return result
