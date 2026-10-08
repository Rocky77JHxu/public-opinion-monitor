"""MediaCrawler 任务执行与结果加载编排。"""

from __future__ import annotations

from pathlib import Path

from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerIntegrationResult,
    MediaCrawlerLoadContext,
    MediaCrawlerTask,
)
from opinion_monitor.collectors.mediacrawler.result_loader import discover_jsonl_files, load_jsonl
from opinion_monitor.collectors.mediacrawler.runner import MediaCrawlerRunner
from opinion_monitor.config.schema import MediaCrawlerConfig


class MediaCrawlerIntegrationService:
    """执行任务并自动发现、加载 JSONL 输出。"""

    def __init__(
        self,
        config: MediaCrawlerConfig,
        *,
        runner: MediaCrawlerRunner | None = None,
    ) -> None:
        self._config = config
        self._runner = runner or MediaCrawlerRunner(config)

    async def run(
        self,
        task: MediaCrawlerTask,
        *,
        execute: bool,
        limit: int | None = None,
    ) -> MediaCrawlerIntegrationResult:
        command = self._runner.build_plan(task)
        run_result = await self._runner.run(task, execute=execute)

        output_files: list[str] = []
        load_results = []
        if run_result.status.value == "succeeded":
            files = discover_jsonl_files(task.workspace_dir)
            output_files = [file.as_posix() for file in files]
            for file in files:
                context = MediaCrawlerLoadContext(
                    task_id=task.task_id,
                    platform=task.platform,
                    source_type=task.source_type,
                    keyword=task.target if task.source_type == "keyword_search" else None,
                    keyword_level=task.keyword_level,
                    account_config_id=task.account_config_id,
                )
                load_results.append(load_jsonl(Path(file), context, limit=limit))

        items = [item for result in load_results for item in result.items]
        return MediaCrawlerIntegrationResult(
            task=task,
            command=command,
            run=run_result,
            output_files=output_files,
            load_results=load_results,
            items=items,
        )
