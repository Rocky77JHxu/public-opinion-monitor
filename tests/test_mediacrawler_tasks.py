from __future__ import annotations

from pathlib import Path

from opinion_monitor.collectors.mediacrawler import (
    MediaCrawlerRunner,
    build_account_tasks,
    build_keyword_tasks,
)
from opinion_monitor.collectors.mediacrawler.models import MediaCrawlerTask
from opinion_monitor.config import load_config
from opinion_monitor.config.schema import AccountConfig, RootConfig
from opinion_monitor.models import MediaCrawlerPlatform


def base_config() -> RootConfig:
    return load_config(Path("config/config.example.yaml"), env={})


async def test_builds_keyword_tasks_for_enabled_platforms() -> None:
    config = base_config()
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.XHS]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    config.keyword_search.levels["level_2"].enabled = False
    config.keyword_search.levels["level_3"].enabled = False

    tasks = build_keyword_tasks(config)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.platform == MediaCrawlerPlatform.XHS
    assert task.source_type == "keyword_search"
    assert task.crawl_type == "search"
    assert task.target == "示例关键词"
    assert task.keyword_level == 1
    assert task.max_items == 20
    assert task.max_comments == 50
    assert task.input_file.endswith("task.json")
    assert task.output_file.endswith("output.jsonl")


async def test_builds_enabled_account_task() -> None:
    config = base_config()
    config.account_search.accounts["example"] = AccountConfig(
        enabled=True,
        name="示例账号",
        platform=MediaCrawlerPlatform.DOUYIN,
        external_id="account-id",
        weight=85,
        crawl_type="creator",
        max_items=11,
        interval_seconds=10800,
        jitter_min_seconds=600,
        jitter_max_seconds=1800,
    )

    tasks = build_account_tasks(config)

    assert len(tasks) == 1
    assert tasks[0].source_type == "account"
    assert tasks[0].platform == MediaCrawlerPlatform.DOUYIN
    assert tasks[0].crawl_type == "creator"
    assert tasks[0].target == "account-id"
    assert tasks[0].max_items == 11


async def test_runner_skips_execution_by_default() -> None:
    config = base_config()
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.XHS]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    task = build_keyword_tasks(config)[0]
    runner = MediaCrawlerRunner(config.mediacrawler)

    result = await runner.run(task, execute=False)

    assert result.status == "skipped"
    assert result.return_code is None
    assert "allow_execution=false" in (result.error or "")


async def test_runner_builds_isolated_argv_without_shell() -> None:
    config = base_config()
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.BILIBILI]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    task = build_keyword_tasks(config)[0]

    plan = MediaCrawlerRunner(config.mediacrawler).build_plan(task)

    assert plan.argv[:3] == ["uv", "run", "python"]
    assert Path(plan.argv[3]).name == "upstream_entry.py"
    assert plan.argv[4:] == [
        "--platform",
        "bili",
        "--lt",
        "qrcode",
        "--type",
        "search",
        "--start",
        "1",
        "--get_comment",
        "true",
        "--get_sub_comment",
        "false",
        "--get_media",
        "false",
        "--headless",
        "false",
        "--save_data_option",
        "jsonl",
        "--save_data_path",
        str(Path(task.workspace_dir).resolve()),  # noqa: ASYNC240
        "--max_comments_count_singlenotes",
        "50",
        "--crawler_max_notes_count",
        "20",
        "--max_concurrency_num",
        "1",
        "--keywords",
        "示例关键词",
    ]
    assert plan.cwd == "third_party/MediaCrawler"
    assert plan.timeout_seconds == task.timeout_seconds


async def test_runner_uses_injected_executor_when_explicitly_allowed() -> None:
    config = base_config()
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.XHS]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    config.mediacrawler.pinned_ref = "a" * 40
    task = build_keyword_tasks(config)[0]

    async def executor(task: object, plan: object) -> tuple[int | None, object, str | None]:
        return 0, "succeeded", None

    result = await MediaCrawlerRunner(
        config.mediacrawler,
        command_executor=executor,  # type: ignore[arg-type]
    ).run(task, execute=True)

    assert result.status == "succeeded"
    assert result.return_code == 0


async def test_execution_requires_pinned_ref() -> None:
    config = base_config()
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.XHS]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    task = build_keyword_tasks(config)[0]
    invalid_media_config = config.mediacrawler.model_copy(update={"pinned_ref": ""})

    result = await MediaCrawlerRunner(invalid_media_config).run(task, execute=True)

    assert result.status == "failed"
    assert "pinned_ref" in (result.error or "")


async def test_integration_service_loads_discovered_jsonl_after_success(
    tmp_path: Path,
) -> None:
    from opinion_monitor.collectors.mediacrawler import (
        MediaCrawlerIntegrationService,
        MediaCrawlerRunner,
        MediaCrawlerRunResult,
        MediaCrawlerRunStatus,
    )
    from opinion_monitor.models import utc_now

    config = base_config()
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.XHS]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    original_task = build_keyword_tasks(config)[0]
    output = tmp_path / original_task.workspace_dir / "xhs_search_contents.jsonl"
    output.parent.mkdir(parents=True)
    output.write_text(
        '{"note_id":"note-1","title":"集成测试标题","desc":"集成测试正文"}\n',
        encoding="utf-8",
    )
    task = original_task.model_copy(
        update={"workspace_dir": str(tmp_path / original_task.workspace_dir)}
    )

    class SuccessfulRunner:
        def build_plan(self, task: MediaCrawlerTask) -> object:
            return MediaCrawlerRunner(config.mediacrawler).build_plan(task)

        async def run(self, task: MediaCrawlerTask, execute: bool) -> object:
            return MediaCrawlerRunResult(
                task_id=task.task_id,
                status=MediaCrawlerRunStatus.SUCCEEDED,
                started_at=utc_now(),
                completed_at=utc_now(),
                return_code=0,
            )

    result = await MediaCrawlerIntegrationService(
        config.mediacrawler,
        runner=SuccessfulRunner(),  # type: ignore[arg-type]
    ).run(task, execute=True)

    assert result.run.status == "succeeded"
    assert len(result.output_files) == 1
    assert result.items[0].title == "集成测试标题"


async def test_integration_service_marks_zero_output_as_failed(tmp_path: Path) -> None:
    from opinion_monitor.collectors.mediacrawler import (
        MediaCrawlerIntegrationService,
        MediaCrawlerRunResult,
        MediaCrawlerRunStatus,
    )
    from opinion_monitor.models import utc_now

    config = base_config()
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.XHS]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    task = build_keyword_tasks(config)[0]
    task = task.model_copy(update={"workspace_dir": str(tmp_path)})

    class NoOutputRunner:
        def build_plan(self, task: MediaCrawlerTask) -> object:
            return MediaCrawlerRunner(config.mediacrawler).build_plan(task)

        async def run(self, task: MediaCrawlerTask, execute: bool) -> object:
            return MediaCrawlerRunResult(
                task_id=task.task_id,
                status=MediaCrawlerRunStatus.SUCCEEDED,
                started_at=utc_now(),
                completed_at=utc_now(),
                return_code=0,
            )

    result = await MediaCrawlerIntegrationService(
        config.mediacrawler,
        runner=NoOutputRunner(),  # type: ignore[arg-type]
    ).run(task, execute=True)

    assert result.run.status == "failed"
    assert "未生成内容 JSONL" in (result.run.error or "")
