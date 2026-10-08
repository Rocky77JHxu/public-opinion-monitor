from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from opinion_monitor.cli import main
from opinion_monitor.collectors.mediacrawler import MediaCrawlerTask
from opinion_monitor.models import MediaCrawlerPlatform

TASK_ID = UUID("11111111-2222-3333-4444-555555555555")


def synthetic_task() -> MediaCrawlerTask:
    return MediaCrawlerTask(
        task_id=TASK_ID,
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        crawl_type="search",
        target="示例关键词",
        keyword_level=1,
        max_items=20,
        max_comments=50,
        timeout_seconds=1800,
        workspace_dir=f"data/media_crawler/tasks/{TASK_ID}",
        input_file=f"data/media_crawler/tasks/{TASK_ID}/task.json",
        output_file=f"data/media_crawler/tasks/{TASK_ID}/output.jsonl",
    )


def test_cli_plans_mediacrawler_without_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "opinion_monitor.cli.build_keyword_tasks", lambda _config: [synthetic_task()]
    )
    monkeypatch.setattr("opinion_monitor.cli.build_account_tasks", lambda _config: [])

    result = main(["--log-format", "json", "plan-mediacrawler", "--source", "keyword"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["task_count"] == 1
    assert payload["allow_execution"] is True
    assert payload["tasks"][0]["task"]["task_id"] == str(TASK_ID)
    assert "--keywords" in payload["tasks"][0]["command"]["argv"]


def test_cli_loads_mediacrawler_jsonl(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(
        [
            "--log-format",
            "json",
            "load-mediacrawler",
            "--path",
            "tests/fixtures/mediacrawler/search.jsonl",
            "--task-id",
            str(TASK_ID),
            "--platform",
            "xhs",
            "--source-type",
            "keyword_search",
            "--keyword",
            "示例关键词",
            "--keyword-level",
            "1",
            "--limit",
            "2",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["loaded_count"] == 2
    assert len(payload["items"]) == 2


def test_discovers_jsonl_files_newest_first(tmp_path: Path) -> None:
    old = tmp_path / "old.jsonl"
    new = tmp_path / "nested" / "new.jsonl"
    new.parent.mkdir()
    old.write_text("{}\n", encoding="utf-8")
    new.write_text("{}\n", encoding="utf-8")
    (tmp_path / "task.json").write_text("{}\n", encoding="utf-8")

    from opinion_monitor.collectors.mediacrawler import discover_jsonl_files

    assert discover_jsonl_files(tmp_path) == [new, old]


def test_cli_run_mediacrawler_defaults_to_plan_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "--log-format",
            "json",
            "run-mediacrawler",
            "--source",
            "keyword",
            "--platform",
            "xhs",
            "--keyword",
            "示例关键词",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["task"]["source_type"] == "keyword_search"
    assert payload["run"]["status"] == "skipped"
    assert payload["items"] == []
