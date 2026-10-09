"""MediaCrawler 隔离集成层。"""

from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerCommandPlan,
    MediaCrawlerIntegrationResult,
    MediaCrawlerLoadContext,
    MediaCrawlerLoadError,
    MediaCrawlerLoadResult,
    MediaCrawlerRunResult,
    MediaCrawlerRunStatus,
    MediaCrawlerTask,
)
from opinion_monitor.collectors.mediacrawler.result_loader import (
    discover_jsonl_files,
    load_jsonl,
)
from opinion_monitor.collectors.mediacrawler.runner import MediaCrawlerRunner
from opinion_monitor.collectors.mediacrawler.service import MediaCrawlerIntegrationService
from opinion_monitor.collectors.mediacrawler.task_builder import (
    build_account_task,
    build_account_tasks,
    build_keyword_task,
    build_keyword_tasks,
    build_keyword_tasks_for_level,
)

__all__ = [
    "MediaCrawlerCommandPlan",
    "MediaCrawlerIntegrationResult",
    "MediaCrawlerIntegrationService",
    "MediaCrawlerLoadContext",
    "MediaCrawlerLoadError",
    "MediaCrawlerLoadResult",
    "MediaCrawlerRunResult",
    "MediaCrawlerRunStatus",
    "MediaCrawlerTask",
    "build_account_task",
    "build_account_tasks",
    "build_keyword_task",
    "build_keyword_tasks",
    "build_keyword_tasks_for_level",
    "discover_jsonl_files",
    "load_jsonl",
    "MediaCrawlerRunner",
]
