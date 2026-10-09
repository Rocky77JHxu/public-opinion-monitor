from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from opinion_monitor.collectors.hotsearch.collector import (
    HotSearchCollectionResult,
    HotSearchPlatformOutcome,
)
from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerIntegrationResult,
    MediaCrawlerTask,
)
from opinion_monitor.config import load_config
from opinion_monitor.config.schema import AccountConfig
from opinion_monitor.models import HotSearchPlatform, MediaCrawlerPlatform, RawItem, utc_now
from opinion_monitor.orchestration import (
    PipelineRunResult,
    PipelineService,
    PipelineStageResult,
    SchedulerCatalog,
    SchedulerService,
)
from opinion_monitor.storage import SqliteStorage

CONFIG = load_config(Path("config/config.example.yaml"), env={})


def _hotsearch_raw() -> RawItem:
    return RawItem(
        id=uuid4(),
        source_type="hotsearch",
        platform=HotSearchPlatform.WEIBO,
        external_id="weibo:hot-1",
        title="某市突发火灾救援进行中",
        url="https://s.weibo.com/weibo?q=%E7%81%AB%E7%81%BE",
        collected_at=utc_now(),
        rank=1,
        hot_value=100000,
        raw_payload={},
        collector_version="test",
    )


def _media_task(tmp_path: Path) -> MediaCrawlerTask:
    task_id = uuid4()
    workspace = tmp_path / "tasks" / str(task_id) / "xhs" / "jsonl"
    workspace.mkdir(parents=True)
    task = MediaCrawlerTask(
        task_id=task_id,
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        crawl_type="search",
        target="火灾",
        keyword_level=1,
        max_items=1,
        max_comments=10,
        timeout_seconds=30,
        workspace_dir=(tmp_path / "tasks" / str(task_id)).as_posix(),
        input_file=(tmp_path / "tasks" / str(task_id) / "task.json").as_posix(),
        output_file=(tmp_path / "tasks" / str(task_id) / "output.jsonl").as_posix(),
    )
    content = {
        "note_id": "note-pipeline",
        "title": "某地火灾救援",
        "desc": "现场救援进行中",
        "note_url": "https://www.xiaohongshu.com/explore/note-pipeline",
        "published_at": utc_now().isoformat(),
    }
    comment = {
        "comment_id": "comment-pipeline",
        "note_id": "note-pipeline",
        "content": "希望人员平安",
        "create_time": utc_now().isoformat(),
    }
    (workspace / "search_contents_2026-10-09.jsonl").write_text(
        json.dumps(content, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (workspace / "search_comments_2026-10-09.jsonl").write_text(
        json.dumps(comment, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return task


class FakeHotSearchCollector:
    def __init__(self, items: list[RawItem]) -> None:
        self.items = items
        self.calls: list[list[HotSearchPlatform]] = []

    async def collect(
        self,
        platforms: Sequence[HotSearchPlatform],
    ) -> HotSearchCollectionResult:
        self.calls.append(list(platforms))
        started = datetime(2026, 10, 9, tzinfo=UTC)
        return HotSearchCollectionResult(
            started_at=started,
            completed_at=started,
            outcomes=[
                HotSearchPlatformOutcome(
                    platform=platform,
                    enabled=True,
                    success=True,
                    item_count=len(self.items),
                    duration_ms=1,
                )
                for platform in platforms
            ],
            items=self.items,
        )


def test_pipeline_persists_hotsearch_and_processes_clean_items(tmp_path: Path) -> None:
    raw = _hotsearch_raw()
    collector = FakeHotSearchCollector([raw])
    storage = SqliteStorage(tmp_path / "state.db")
    service = PipelineService(
        CONFIG,
        env={},
        storage=storage,
        hotsearch_collector=collector,
    )

    import asyncio

    pipeline_result = asyncio.run(
        service.run(
            execute=True,
            hotsearch_platforms=[HotSearchPlatform.WEIBO],
            run_llm=False,
        )
    )

    assert pipeline_result.status == "succeeded"
    assert collector.calls == [[HotSearchPlatform.WEIBO]]
    assert storage.stats()["raw_items"] == 1
    assert storage.stats()["clean_items"] == 1
    assert storage.stats()["risk_assessments"] == 0
    stage_status = {stage.stage: stage.status for stage in pipeline_result.stages}
    assert stage_status["hotsearch"] == "succeeded"
    assert stage_status["processing"] == "succeeded"
    assert stage_status["risk_scoring"] == "skipped"


def test_pipeline_preview_does_not_collect_or_call_models(tmp_path: Path) -> None:
    collector = FakeHotSearchCollector([_hotsearch_raw()])
    storage = SqliteStorage(tmp_path / "state.db")
    service = PipelineService(
        CONFIG,
        env={},
        storage=storage,
        hotsearch_collector=collector,
    )

    import asyncio

    result = asyncio.run(service.run(execute=False))

    assert collector.calls == []
    assert result.status == "succeeded"
    assert storage.stats()["raw_items"] == 0
    status_by_stage = {stage.stage: stage.status for stage in result.stages}
    assert status_by_stage["hotsearch"] == "skipped"
    assert status_by_stage["mediacrawler"] == "skipped"
    assert status_by_stage["llm_analysis"] == "skipped"


def test_pipeline_ingests_mediacrawler_output_before_processing(tmp_path: Path) -> None:
    import asyncio

    task = _media_task(tmp_path)
    item = RawItem(
        id=uuid4(),
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        external_id="xhs:note-pipeline",
        title="某地火灾救援",
        url="https://www.xiaohongshu.com/explore/note-pipeline",
        published_at=utc_now(),
        collected_at=utc_now(),
        keyword="火灾",
        keyword_level=1,
        raw_payload={},
        collector_version="test",
    )
    executor = FakeMediaExecutor(task, [item])
    storage = SqliteStorage(tmp_path / "state.db")
    service = PipelineService(
        CONFIG,
        env={},
        storage=storage,
        media_executor=executor,
    )

    result = asyncio.run(
        service.run(
            execute=True,
            media_tasks=[task],
            run_llm=False,
        )
    )

    assert result.status == "succeeded"
    assert executor.calls == 1
    assert storage.stats()["raw_items"] == 1
    assert storage.stats()["comment_records"] == 1
    assert storage.stats()["clean_items"] == 1
    media_stage = next(stage for stage in result.stages if stage.stage == "mediacrawler")
    assert media_stage.details["tasks"][0]["raw_inserted"] == 1
    assert media_stage.details["tasks"][0]["comments_inserted"] == 1


class FakeMediaExecutor:
    def __init__(self, task: MediaCrawlerTask, items: list[RawItem]) -> None:
        self.task = task
        self.items = items
        self.calls = 0

    async def run(
        self,
        task: MediaCrawlerTask,
        *,
        execute: bool,
        limit: int | None = None,
    ) -> MediaCrawlerIntegrationResult:
        self.calls += 1
        started = utc_now()
        return MediaCrawlerIntegrationResult.model_validate(
            {
                "task": task.model_dump(mode="json"),
                "command": {
                    "task_id": str(task.task_id),
                    "cwd": ".",
                    "argv": ["test"],
                    "input_file": task.input_file,
                    "output_file": task.output_file,
                    "stdout_file": f"{task.workspace_dir}/stdout.log",
                    "stderr_file": f"{task.workspace_dir}/stderr.log",
                    "timeout_seconds": task.timeout_seconds,
                    "watchdog_enabled": False,
                    "watchdog_poll_seconds": 0.25,
                },
                "run": {
                    "task_id": str(task.task_id),
                    "status": "succeeded",
                    "started_at": started.isoformat(),
                    "completed_at": started.isoformat(),
                    "return_code": 0,
                },
                "output_files": [],
                "load_results": [],
                "items": [item.model_dump(mode="json") for item in self.items],
            }
        )


def test_scheduler_catalog_and_cycle_persist_state(tmp_path: Path) -> None:
    account = AccountConfig(
        enabled=True,
        name="测试账号",
        platform=MediaCrawlerPlatform.XHS,
        external_id="account-1",
        weight=80,
        interval_seconds=3600,
        jitter_min_seconds=10,
        jitter_max_seconds=20,
        max_items=2,
    )
    keyword_config = CONFIG.keyword_search.model_copy(deep=True)
    level_1 = keyword_config.levels["level_1"].model_copy(
        update={"keywords": ["火灾"], "platforms": [MediaCrawlerPlatform.XHS]}
    )
    keyword_config.levels["level_1"] = level_1
    account_search = CONFIG.account_search.model_copy(
        update={"accounts": {"test_account": account}}
    )
    config = CONFIG.model_copy(
        update={
            "keyword_search": keyword_config,
            "account_search": account_search,
        }
    )
    sources = SchedulerCatalog.build(config)
    assert [source.key for source in sources] == [
        "hotsearch:weibo",
        "hotsearch:baidu",
        "hotsearch:zhihu",
        "hotsearch:douyin",
        "hotsearch:bilibili",
        "keyword_search:level_1",
        "account:test_account",
    ]

    class FakePipeline:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, **kwargs: Any) -> PipelineRunResult:
            self.calls += 1
            started = utc_now()
            return PipelineRunResult(
                run_id=uuid4(),
                executed=bool(kwargs["execute"]),
                status="succeeded",
                started_at=started,
                completed_at=utc_now(),
                duration_ms=1,
                stages=[
                    PipelineStageResult(
                        stage="processing",
                        status="succeeded",
                        started_at=started,
                        completed_at=utc_now(),
                        duration_ms=1,
                    )
                ],
            )

    pipelines = [FakePipeline()]
    storage = SqliteStorage(tmp_path / "state.db")
    storage.initialise()
    scheduler = SchedulerService(
        config,
        storage=storage,
        pipeline_factory=lambda: pipelines[0],
        jitter=lambda minimum, maximum: minimum,
    )

    import asyncio

    result = asyncio.run(scheduler.run_cycle(execute=False))
    assert result.status == "succeeded", [
        (
            run.source_key,
            run.status,
            [stage.error for stage in run.pipeline_result.stages if stage.error],
        )
        for run in result.source_runs
    ]
    assert len(result.source_runs) == len(sources)
    assert result.downstream_result is not None
    assert pipelines[0].calls == len(sources) + 1
    assert storage.stats()["scheduler_state"] == len(sources)
    assert storage.stats()["scheduler_runs"] == len(sources)
    assert all(run.next_run_at > run.started_at for run in result.source_runs)
    assert scheduler.due_sources() == []

    idle = scheduler.seconds_until_next()
    assert (
        0 < idle <= max(source.interval_seconds + source.jitter_min_seconds for source in sources)
    )


def test_cli_pipeline_preview_does_not_access_external_services(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml

    from opinion_monitor.cli import main

    config = CONFIG.model_dump(mode="json")
    config["storage"]["sqlite"]["path"] = str(tmp_path / "state.db")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    exit_code = main(["--config", str(config_path), "run-pipeline"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["executed"] is False
    assert payload["status"] == "succeeded"
    assert all(stage["status"] in {"succeeded", "skipped"} for stage in payload["stages"])


def test_cli_scheduler_single_cycle_preview_persists_schedule_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml

    from opinion_monitor.cli import main

    config = CONFIG.model_dump(mode="json")
    config["storage"]["sqlite"]["path"] = str(tmp_path / "state.db")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    exit_code = main(["--config", str(config_path), "run-scheduler"])
    payload = json.loads(capsys.readouterr().out)
    storage = SqliteStorage(config["storage"]["sqlite"]["path"])

    assert exit_code == 0
    assert payload["cycles"][0]["status"] == "succeeded"
    assert len(payload["cycles"][0]["source_runs"]) == 5
    assert storage.stats()["scheduler_state"] == 5
    assert storage.stats()["scheduler_runs"] == 5
