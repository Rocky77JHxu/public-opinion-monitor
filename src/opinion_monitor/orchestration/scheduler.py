"""基于配置间隔与浮动窗口的调度器。"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from opinion_monitor.collectors.mediacrawler import (
    build_account_task,
    build_keyword_tasks_for_level,
)
from opinion_monitor.collectors.mediacrawler.models import MediaCrawlerTask
from opinion_monitor.config.schema import RootConfig
from opinion_monitor.models import HotSearchPlatform, utc_now
from opinion_monitor.orchestration.models import (
    ExecutionStatus,
    PipelineRunResult,
    PipelineStageResult,
    ScheduledSource,
    SchedulerCycleResult,
    SchedulerSourceRun,
)
from opinion_monitor.storage import SqliteStorage


class SchedulerPipeline(Protocol):
    """调度器所需的流水线执行协议。"""

    async def run(
        self,
        *,
        execute: bool,
        hotsearch_platforms: Sequence[HotSearchPlatform] = (),
        hotsearch_limit: int | None = None,
        media_tasks: Sequence[MediaCrawlerTask] = (),
        run_processing: bool = True,
        run_llm: bool = True,
        run_scoring: bool = True,
        run_output: bool = True,
        include_queued: bool = False,
        media_limit: int | None = None,
        llm_limit: int | None = None,
        output_limit: int | None = None,
        fail_fast: bool = False,
    ) -> PipelineRunResult:
        """执行一次流水线。"""
        raise NotImplementedError


class SchedulerCatalog:
    """从主配置生成独立调度来源。"""

    @staticmethod
    def build(config: RootConfig) -> list[ScheduledSource]:
        sources: list[ScheduledSource] = []

        if config.hotsearch.defaults.enabled:
            for platform, platform_config in config.hotsearch.platforms.items():
                if not platform_config.enabled:
                    continue
                interval = (
                    platform_config.interval_seconds or config.hotsearch.defaults.interval_seconds
                )
                jitter_min = (
                    platform_config.jitter_min_seconds
                    if platform_config.jitter_min_seconds is not None
                    else config.hotsearch.defaults.jitter_min_seconds
                )
                jitter_max = (
                    platform_config.jitter_max_seconds
                    if platform_config.jitter_max_seconds is not None
                    else config.hotsearch.defaults.jitter_max_seconds
                )
                sources.append(
                    ScheduledSource(
                        key=f"hotsearch:{platform.value}",
                        kind="hotsearch",
                        label=f"热搜-{platform.value}",
                        interval_seconds=interval,
                        jitter_min_seconds=jitter_min,
                        jitter_max_seconds=jitter_max,
                        hotsearch_platform=platform,
                    )
                )

        keyword_config = config.keyword_search
        if keyword_config.defaults.enabled:
            for level_order, (level_name, level) in enumerate(
                keyword_config.levels.items(),
                start=1,
            ):
                if not level.enabled or not level.keywords:
                    continue
                level_number = (
                    int(level_name.rsplit("_", 1)[-1])
                    if level_name.rsplit("_", 1)[-1].isdigit()
                    else level_order
                )
                sources.append(
                    ScheduledSource(
                        key=f"keyword_search:{level_name}",
                        kind="keyword_search",
                        label=f"关键词-{level_name}",
                        interval_seconds=level.interval_seconds,
                        jitter_min_seconds=level.jitter_min_seconds,
                        jitter_max_seconds=level.jitter_max_seconds,
                        keyword_level_name=level_name,
                        keyword_level=level_number,
                    )
                )

        account_config = config.account_search
        if account_config.defaults.enabled:
            for account_id, account in account_config.accounts.items():
                if not account.enabled:
                    continue
                sources.append(
                    ScheduledSource(
                        key=f"account:{account_id}",
                        kind="account",
                        label=f"账号-{account.name}",
                        interval_seconds=account.interval_seconds,
                        jitter_min_seconds=account.jitter_min_seconds,
                        jitter_max_seconds=account.jitter_max_seconds,
                        account_config_id=account_id,
                    )
                )
        return sources


class SchedulerService:
    """计算到期任务、并发执行采集来源，并统一执行后续处理。"""

    def __init__(
        self,
        config: RootConfig,
        *,
        storage: SqliteStorage,
        pipeline_factory: Callable[[], SchedulerPipeline],
        jitter: Callable[[int, int], float] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._config = config
        self._storage = storage
        self._pipeline_factory = pipeline_factory
        self._random = random.SystemRandom()
        self._jitter = jitter or self._default_jitter
        self._clock = clock
        self._sources = SchedulerCatalog.build(config)

    def _default_jitter(self, minimum: int, maximum: int) -> float:
        return self._random.uniform(minimum, maximum)

    @property
    def sources(self) -> list[ScheduledSource]:
        return list(self._sources)

    def due_sources(self, reference_time: datetime | None = None) -> list[ScheduledSource]:
        reference = reference_time or utc_now()
        state = self._storage.list_scheduler_state()
        return [
            source
            for source in self._sources
            if source.key not in state or state[source.key] <= reference
        ]

    def seconds_until_next(self, reference_time: datetime | None = None) -> float:
        reference = reference_time or utc_now()
        state = self._storage.list_scheduler_state()
        candidates = [state.get(source.key) or reference for source in self._sources]
        if not candidates:
            return 0.0
        return max(0.0, (min(candidates) - reference).total_seconds())

    def _next_run(
        self,
        source: ScheduledSource,
        reference_time: datetime,
    ) -> datetime:
        delay = source.interval_seconds + self._jitter(
            source.jitter_min_seconds,
            source.jitter_max_seconds,
        )
        return reference_time + timedelta(seconds=delay)

    def _tasks_for_source(self, source: ScheduledSource) -> list[MediaCrawlerTask]:
        if source.kind == "keyword_search" and source.keyword_level_name is not None:
            return build_keyword_tasks_for_level(self._config, source.keyword_level_name)
        if source.kind == "account" and source.account_config_id is not None:
            return [build_account_task(self._config, source.account_config_id)]
        return []

    def _failed_pipeline(
        self,
        source: ScheduledSource,
        started_at: datetime,
        error: str,
    ) -> PipelineRunResult:
        completed_at = utc_now()
        stage = PipelineStageResult(
            stage="hotsearch" if source.kind == "hotsearch" else "mediacrawler",
            status="failed",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=0,
            details={"source_key": source.key},
            error=error,
        )
        return PipelineRunResult(
            run_id=uuid.uuid4(),
            executed=True,
            status="failed",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=0,
            stages=[stage],
        )

    @staticmethod
    def _combine(statuses: list[ExecutionStatus]) -> ExecutionStatus:
        if any(status == "failed" for status in statuses):
            return "failed"
        if any(status == "partial" for status in statuses):
            return "partial"
        return "succeeded"

    async def _run_source(
        self,
        source: ScheduledSource,
        *,
        cycle_id: uuid.UUID,
        execute: bool,
        hotsearch_limit: int | None,
        media_limit: int | None,
    ) -> SchedulerSourceRun:
        started_at = utc_now()
        pipeline = self._pipeline_factory()
        try:
            result = await asyncio.wait_for(
                pipeline.run(
                    execute=execute,
                    hotsearch_platforms=(
                        [source.hotsearch_platform] if source.hotsearch_platform is not None else []
                    ),
                    hotsearch_limit=hotsearch_limit,
                    media_tasks=self._tasks_for_source(source),
                    run_processing=False,
                    run_llm=False,
                    run_scoring=False,
                    run_output=False,
                    media_limit=media_limit,
                ),
                timeout=self._config.scheduler.task_timeout_seconds,
            )
        except Exception as exc:
            result = self._failed_pipeline(
                source,
                started_at,
                f"{type(exc).__name__}: {exc}",
            )

        completed_at = utc_now()
        next_run_at = self._next_run(source, completed_at)
        self._storage.save_scheduler_state(
            source_key=source.key,
            source_kind=source.kind,
            last_run_at=completed_at,
            next_run_at=next_run_at,
        )
        self._storage.save_scheduler_run(
            run_id=result.run_id,
            cycle_id=cycle_id,
            source_key=source.key,
            source_kind=source.kind,
            status=result.status,
            started_at=started_at,
            completed_at=completed_at,
            result=result.model_dump(mode="json"),
            error=next(
                (stage.error for stage in result.stages if stage.error),
                None,
            ),
        )
        return SchedulerSourceRun(
            source_key=source.key,
            source_kind=source.kind,
            status=result.status,
            started_at=started_at,
            completed_at=completed_at,
            pipeline_result=result,
            next_run_at=next_run_at,
        )

    async def run_cycle(
        self,
        *,
        execute: bool,
        hotsearch_limit: int | None = None,
        include_queued: bool = False,
        media_limit: int | None = None,
        llm_limit: int | None = None,
        output_limit: int | None = None,
        fail_fast: bool = False,
        run_processing: bool = True,
        run_llm: bool = True,
        run_scoring: bool = True,
        run_output: bool = True,
    ) -> SchedulerCycleResult:
        cycle_id = uuid.uuid4()
        started = self._clock()
        started_at = utc_now()
        self._storage.initialise()

        if not self._config.scheduler.enabled:
            completed_at = utc_now()
            return SchedulerCycleResult(
                cycle_id=cycle_id,
                executed=execute,
                status="skipped",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=0,
                idle_seconds=None,
            )

        due = self.due_sources(started_at)
        if not due:
            completed_at = utc_now()
            return SchedulerCycleResult(
                cycle_id=cycle_id,
                executed=execute,
                status="succeeded",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=0,
                idle_seconds=self.seconds_until_next(started_at),
            )

        semaphore = asyncio.Semaphore(self._config.scheduler.max_concurrent_tasks)

        async def execute_source(source: ScheduledSource) -> SchedulerSourceRun:
            async with semaphore:
                return await self._run_source(
                    source,
                    cycle_id=cycle_id,
                    execute=execute,
                    hotsearch_limit=hotsearch_limit,
                    media_limit=media_limit,
                )

        source_runs = list(await asyncio.gather(*(execute_source(source) for source in due)))
        downstream_result: PipelineRunResult | None = None
        if not fail_fast or all(run.status != "failed" for run in source_runs):
            pipeline = self._pipeline_factory()
            try:
                downstream_result = await asyncio.wait_for(
                    pipeline.run(
                        execute=execute,
                        hotsearch_platforms=[],
                        media_tasks=[],
                        run_processing=run_processing,
                        run_llm=run_llm,
                        run_scoring=run_scoring,
                        run_output=run_output,
                        include_queued=include_queued,
                        llm_limit=llm_limit,
                        output_limit=output_limit,
                        fail_fast=fail_fast,
                    ),
                    timeout=self._config.scheduler.task_timeout_seconds,
                )
            except Exception as exc:
                completed_at = utc_now()
                failed_stage = PipelineStageResult(
                    stage="processing",
                    status="failed",
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=0,
                    details={"reason": "调度器后续处理失败"},
                    error=f"{type(exc).__name__}: {exc}",
                )
                downstream_result = PipelineRunResult(
                    run_id=uuid.uuid4(),
                    executed=execute,
                    status="failed",
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=0,
                    stages=[failed_stage],
                )

        statuses = [run.status for run in source_runs]
        if downstream_result is not None:
            statuses.append(downstream_result.status)
        completed_at = utc_now()
        return SchedulerCycleResult(
            cycle_id=cycle_id,
            executed=execute,
            status=self._combine(statuses),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(0, int((self._clock() - started) * 1000)),
            source_runs=source_runs,
            downstream_result=downstream_result,
            idle_seconds=self.seconds_until_next(completed_at),
        )
