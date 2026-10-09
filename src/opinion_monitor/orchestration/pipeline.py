"""采集、清洗、分析、评分与产出的端到端编排服务。"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from opinion_monitor.collectors.hotsearch.collector import (
    HotSearchCollectionResult,
    HotSearchCollector,
)
from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerIntegrationResult,
    MediaCrawlerTask,
)
from opinion_monitor.collectors.mediacrawler.service import MediaCrawlerIntegrationService
from opinion_monitor.config.schema import RootConfig
from opinion_monitor.llm import LLMAnalysisService
from opinion_monitor.models import HotSearchPlatform, utc_now
from opinion_monitor.orchestration.models import (
    ExecutionStatus,
    PipelineRunResult,
    PipelineStageName,
    PipelineStageResult,
)
from opinion_monitor.output import DingTalkOutputService
from opinion_monitor.scoring import RiskScoringService
from opinion_monitor.storage import SqliteStorage, ingest_and_process_media_crawler_task
from opinion_monitor.storage.service import process_pending_items


class MediaCrawlerPipelineExecutor(Protocol):
    """Pipeline 使用的数据采集执行协议。"""

    async def run(
        self,
        task: MediaCrawlerTask,
        *,
        execute: bool,
        limit: int | None = None,
    ) -> MediaCrawlerIntegrationResult:
        """执行或预览一个 MediaCrawler 任务。"""
        raise NotImplementedError


class HotSearchPipelineCollector(Protocol):
    """Pipeline 使用的热搜采集协议。"""

    async def collect(
        self,
        platforms: Sequence[HotSearchPlatform],
    ) -> HotSearchCollectionResult:
        """采集指定平台热搜。"""
        raise NotImplementedError


class PipelineService:
    """按阶段执行端到端流水线，并保留单阶段失败上下文。"""

    def __init__(
        self,
        config: RootConfig,
        *,
        env: Mapping[str, str],
        storage: SqliteStorage | None = None,
        hotsearch_collector: HotSearchPipelineCollector | None = None,
        media_executor: MediaCrawlerPipelineExecutor | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._config = config
        self._env = dict(env)
        self._storage = storage or SqliteStorage(config.storage.sqlite.path)
        self._hotsearch_collector = hotsearch_collector
        self._media_executor = media_executor
        self._clock = clock

    @staticmethod
    def _combine(statuses: Sequence[ExecutionStatus]) -> ExecutionStatus:
        if any(status == "failed" for status in statuses):
            return "failed"
        if any(status == "partial" for status in statuses):
            return "partial"
        return "succeeded"

    def _stage(
        self,
        stage: PipelineStageName,
        started: float,
        started_at: datetime,
        status: ExecutionStatus,
        details: dict[str, Any],
        error: str | None = None,
    ) -> PipelineStageResult:
        completed_at = utc_now()
        return PipelineStageResult(
            stage=stage,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(0, int((self._clock() - started) * 1000)),
            details=details,
            error=error,
        )

    async def _run_hotsearch(
        self,
        platforms: Sequence[HotSearchPlatform],
        *,
        execute: bool,
        item_limit: int | None = None,
    ) -> PipelineStageResult:
        started = self._clock()
        started_at = utc_now()
        if not platforms:
            return self._stage(
                "hotsearch",
                started,
                started_at,
                "skipped",
                {"reason": "未选择热搜平台"},
            )
        if not execute:
            return self._stage(
                "hotsearch",
                started,
                started_at,
                "skipped",
                {"reason": "未传入 --execute，未访问热搜平台", "platforms": len(platforms)},
            )

        collector = self._hotsearch_collector or HotSearchCollector(
            self._config.hotsearch,
            allow_private_network=self._config.security.allow_private_network,
        )
        result: HotSearchCollectionResult = await collector.collect(platforms)
        limit = item_limit or self._config.hotsearch.defaults.max_items_per_platform
        saved_counts = {platform.value: 0 for platform in platforms}
        items_to_save = []
        for item in result.items:
            platform_value = item.platform.value
            if saved_counts[platform_value] >= limit:
                continue
            items_to_save.append(item)
            saved_counts[platform_value] += 1
        inserted = self._storage.save_raw_items(items_to_save)
        failed = [outcome for outcome in result.outcomes if outcome.enabled and not outcome.success]
        status: ExecutionStatus = "succeeded"
        if not result.successful_platforms:
            status = "failed"
        elif failed:
            status = "partial"
        return self._stage(
            "hotsearch",
            started,
            started_at,
            status,
            {
                "platforms": [outcome.platform.value for outcome in result.outcomes],
                "successful_platforms": [
                    outcome.platform.value for outcome in result.outcomes if outcome.success
                ],
                "failed_platforms": [outcome.platform.value for outcome in failed],
                "parsed_items": len(result.items),
                "items_to_save": len(items_to_save),
                "item_limit": limit,
                "raw_inserted": inserted,
            },
            error=None
            if not failed
            else "; ".join(f"{outcome.platform.value}: {outcome.error}" for outcome in failed),
        )

    async def _run_mediacrawler(
        self,
        tasks: Sequence[MediaCrawlerTask],
        *,
        execute: bool,
        media_limit: int | None,
    ) -> PipelineStageResult:
        started = self._clock()
        started_at = utc_now()
        if not tasks:
            return self._stage(
                "mediacrawler",
                started,
                started_at,
                "skipped",
                {"reason": "未生成 MediaCrawler 任务"},
            )
        if not execute:
            return self._stage(
                "mediacrawler",
                started,
                started_at,
                "skipped",
                {
                    "reason": "未传入 --execute，未启动浏览器或平台请求",
                    "tasks": [str(task.task_id) for task in tasks],
                },
            )

        executor = self._media_executor or MediaCrawlerIntegrationService(self._config.mediacrawler)
        task_details: list[dict[str, Any]] = []
        statuses: list[ExecutionStatus] = []
        for task in tasks:
            result = await executor.run(task, execute=True, limit=media_limit)
            self._storage.save_media_crawler_run(
                result.run,
                output_files=result.output_files,
            )
            raw_inserted = 0
            comments_inserted = 0
            error = result.run.error
            if result.run.status.value == "succeeded":
                summary = ingest_and_process_media_crawler_task(
                    self._config,
                    task,
                    storage=self._storage,
                    process=False,
                )
                raw_inserted = summary.raw_inserted
                comments_inserted = summary.comments_inserted
            else:
                error = error or f"MediaCrawler 任务状态异常：{result.run.status.value}"
            status: ExecutionStatus = (
                "succeeded" if result.run.status.value == "succeeded" else "failed"
            )
            statuses.append(status)
            task_details.append(
                {
                    "task_id": str(task.task_id),
                    "source_type": task.source_type,
                    "platform": task.platform.value,
                    "target": task.target,
                    "status": result.run.status.value,
                    "items": len(result.items),
                    "raw_inserted": raw_inserted,
                    "comments_inserted": comments_inserted,
                    "stopped_by_watchdog": result.run.stopped_by_watchdog,
                    "error": error,
                }
            )

        return self._stage(
            "mediacrawler",
            started,
            started_at,
            self._combine(statuses),
            {"tasks": task_details},
            error=None
            if all(item["error"] is None for item in task_details)
            else "; ".join(
                str(item["error"]) for item in task_details if item["error"] is not None
            ),
        )

    def _run_processing(self) -> PipelineStageResult:
        started = self._clock()
        started_at = utc_now()
        pending_count = len(self._storage.list_pending_raw_items())
        if pending_count == 0:
            return self._stage(
                "processing",
                started,
                started_at,
                "skipped",
                {"reason": "没有待清洗 RawItem"},
            )
        result = process_pending_items(self._config, storage=self._storage)
        return self._stage(
            "processing",
            started,
            started_at,
            "succeeded",
            {
                "input_count": result.input_count,
                "accepted_count": result.accepted_count,
                "discarded_count": result.discarded_count,
            },
        )

    async def _run_llm(
        self,
        *,
        execute: bool,
        limit: int | None,
    ) -> PipelineStageResult:
        started = self._clock()
        started_at = utc_now()
        items = self._storage.list_clean_items_missing_analysis()
        if limit is not None and limit >= 0:
            items = items[:limit]
        if not items:
            return self._stage(
                "llm_analysis",
                started,
                started_at,
                "skipped",
                {"reason": "没有待分析 CleanItem"},
            )
        if not execute:
            return self._stage(
                "llm_analysis",
                started,
                started_at,
                "skipped",
                {
                    "reason": "未传入 --execute，未调用模型",
                    "pending_items": len(items),
                },
            )

        service = LLMAnalysisService(
            self._config.llm,
            env=self._env,
            sentiment_categories=self._config.sentiment.categories,
        )
        details: list[dict[str, Any]] = []
        statuses: list[ExecutionStatus] = []
        for item in items:
            comments = self._storage.list_comments_for_clean_item(item.id)
            run = await service.analyze(item, comments, execute=True)
            self._storage.save_llm_analysis_run(run)
            audit_status = run.audit.status if run.audit is not None else "failed"
            status: ExecutionStatus = "succeeded" if audit_status == "succeeded" else "failed"
            statuses.append(status)
            details.append(
                {
                    "clean_item_id": str(item.id),
                    "status": audit_status,
                    "attempts": run.audit.attempts if run.audit is not None else 0,
                    "error": run.audit.error if run.audit is not None else "缺少审计记录",
                }
            )
        return self._stage(
            "llm_analysis",
            started,
            started_at,
            self._combine(statuses),
            {"items": details},
            error=None
            if all(item["error"] is None for item in details)
            else "; ".join(str(item["error"]) for item in details if item["error"] is not None),
        )

    def _run_scoring(self) -> PipelineStageResult:
        started = self._clock()
        started_at = utc_now()
        items = self._storage.list_clean_items_ready_for_scoring()
        if not items:
            return self._stage(
                "risk_scoring",
                started,
                started_at,
                "skipped",
                {"reason": "没有待评分 CleanItem"},
            )
        service = RiskScoringService(self._config)
        details: list[dict[str, Any]] = []
        for item in items:
            analysis = self._storage.get_llm_analysis_result(item.id)
            if analysis is None:
                details.append(
                    {
                        "clean_item_id": str(item.id),
                        "status": "failed",
                        "error": "缺少 LLM 分析结果",
                    }
                )
                continue
            raw_items = self._storage.list_raw_items_for_clean_item(item.id)
            result = service.score(item, analysis, raw_items)
            self._storage.save_scoring_run(result)
            details.append(
                {
                    "clean_item_id": str(item.id),
                    "status": "succeeded",
                    "overall_score": result.assessment.overall_score,
                    "alert_level": result.assessment.alert_level.value,
                }
            )
        status: ExecutionStatus = (
            "failed" if any(item["status"] == "failed" for item in details) else "succeeded"
        )
        return self._stage(
            "risk_scoring",
            started,
            started_at,
            status,
            {"items": details},
            error=None if status == "succeeded" else "部分条目缺少 LLM 分析结果",
        )

    async def _run_output(
        self,
        *,
        execute: bool,
        include_queued: bool,
        limit: int | None,
    ) -> PipelineStageResult:
        started = self._clock()
        started_at = utc_now()
        output_config = self._config.output.dingtalk
        if not output_config.enabled:
            return self._stage(
                "dingtalk_output",
                started,
                started_at,
                "skipped",
                {"reason": "钉钉产出全局未启用"},
            )
        enabled_levels = {
            level.value
            for level, level_config in output_config.levels.items()
            if level_config.enabled
        }
        events = self._storage.list_structured_output_events(alert_levels=enabled_levels)
        if not include_queued:
            events = [
                event for event in events if output_config.levels[event.alert_level].immediate
            ]
        if limit is not None and limit >= 0:
            events = events[:limit]
        if not events:
            return self._stage(
                "dingtalk_output",
                started,
                started_at,
                "skipped",
                {"reason": "没有待投递结构化事件"},
            )

        service = DingTalkOutputService(self._config, env=self._env)
        details: list[dict[str, Any]] = []
        statuses: list[ExecutionStatus] = []
        for event in events:
            if not execute:
                prepared = service.prepare(event)
                details.append(
                    {
                        "event_id": str(event.event_id),
                        "status": "preview",
                        "payload_hash": prepared.payload_hash,
                    }
                )
                statuses.append("succeeded")
                continue
            previous = self._storage.get_dingtalk_delivery(event.event_id)
            result = await service.deliver(
                event,
                dry_run=False,
                attempt_offset=previous.attempt_count if previous is not None else 0,
            )
            self._storage.save_dingtalk_delivery_result(result)
            status: ExecutionStatus = "succeeded" if result.status == "succeeded" else "failed"
            statuses.append(status)
            details.append(
                {
                    "event_id": str(event.event_id),
                    "status": result.status,
                    "http_status_code": result.record.response_status_code,
                    "error": result.record.error,
                }
            )
        return self._stage(
            "dingtalk_output",
            started,
            started_at,
            self._combine(statuses),
            {"events": details},
            error=None
            if all(item["error"] is None for item in details)
            else "; ".join(str(item["error"]) for item in details if item["error"] is not None),
        )

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
        """执行端到端流水线；外部请求必须显式 execute=true。"""

        run_id = uuid.uuid4()
        started = self._clock()
        started_at = utc_now()
        self._storage.initialise()
        stages: list[PipelineStageResult] = []

        try:
            stages.append(
                await self._run_hotsearch(
                    hotsearch_platforms,
                    execute=execute,
                    item_limit=hotsearch_limit,
                )
            )
            if fail_fast and stages[-1].status == "failed":
                raise RuntimeError(f"热搜阶段失败：{stages[-1].error}")

            stages.append(
                await self._run_mediacrawler(
                    media_tasks,
                    execute=execute,
                    media_limit=media_limit,
                )
            )
            if fail_fast and stages[-1].status == "failed":
                raise RuntimeError(f"MediaCrawler 阶段失败：{stages[-1].error}")

            if run_processing:
                stages.append(self._run_processing())
            if fail_fast and stages[-1].status == "failed":
                raise RuntimeError(f"清洗阶段失败：{stages[-1].error}")

            if run_llm:
                stages.append(await self._run_llm(execute=execute, limit=llm_limit))
            if fail_fast and stages[-1].status == "failed":
                raise RuntimeError(f"LLM 分析阶段失败：{stages[-1].error}")

            if run_scoring:
                stages.append(self._run_scoring())
            if fail_fast and stages[-1].status == "failed":
                raise RuntimeError(f"评分阶段失败：{stages[-1].error}")

            if run_output:
                stages.append(
                    await self._run_output(
                        execute=execute,
                        include_queued=include_queued,
                        limit=output_limit,
                    )
                )
            if fail_fast and stages[-1].status == "failed":
                raise RuntimeError(f"钉钉产出阶段失败：{stages[-1].error}")
        except Exception as exc:
            if not stages or stages[-1].status != "failed":
                stages.append(
                    self._stage(
                        "processing",
                        started,
                        started_at,
                        "failed",
                        {"reason": "流水线中断"},
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            completed_at = utc_now()
            return PipelineRunResult(
                run_id=run_id,
                executed=execute,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=max(0, int((self._clock() - started) * 1000)),
                stages=stages,
                storage_stats=self._storage.stats(),
            )

        completed_at = utc_now()
        return PipelineRunResult(
            run_id=run_id,
            executed=execute,
            status=self._combine([stage.status for stage in stages]),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(0, int((self._clock() - started) * 1000)),
            stages=stages,
            storage_stats=self._storage.stats(),
        )
