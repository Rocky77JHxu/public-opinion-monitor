from __future__ import annotations

from pathlib import Path

from opinion_monitor.collectors.mediacrawler import (
    MediaCrawlerRunner,
    build_account_tasks,
    build_keyword_tasks,
)
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
    assert config.mediacrawler.allow_execution is False
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.XHS]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    task = build_keyword_tasks(config)[0]
    runner = MediaCrawlerRunner(config.mediacrawler)

    result = await runner.run(task)

    assert result.status == "skipped"
    assert result.return_code is None
    assert "allow_execution=false" in (result.error or "")


async def test_runner_builds_isolated_argv_without_shell() -> None:
    config = base_config()
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.BILIBILI]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    task = build_keyword_tasks(config)[0]

    plan = MediaCrawlerRunner(config.mediacrawler).build_plan(task)

    assert plan.argv == [
        "uv",
        "run",
        "main.py",
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
        "--save_data_option",
        "jsonl",
        "--save_data_path",
        task.workspace_dir,
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
    config.mediacrawler.license_accepted = True
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


async def test_execution_requires_license_and_pinned_ref() -> None:
    config = base_config()
    config.mediacrawler.license_accepted = False
    config.mediacrawler.pinned_ref = ""
    config.keyword_search.levels["level_1"].platforms = [MediaCrawlerPlatform.XHS]
    config.keyword_search.levels["level_1"].keywords = ["示例关键词"]
    task = build_keyword_tasks(config)[0]

    result = await MediaCrawlerRunner(config.mediacrawler).run(task, execute=True)

    assert result.status == "failed"
    assert "license_accepted 或 pinned_ref" in (result.error or "")
