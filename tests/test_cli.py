from __future__ import annotations

import json
import subprocess
import sys

import pytest

from opinion_monitor.cli import main


def test_cli_reports_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "opinion_monitor.cli", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "0.1.0"


def test_cli_validates_example_config(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["--log-format", "json", "validate-config"])

    captured = capsys.readouterr()
    assert result == 0
    assert "配置校验通过" in captured.out


def test_cli_inspects_environment_references(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["--log-format", "json", "inspect-env"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert "OPENAI_API_KEY" in payload["references"]
    assert "DINGTALK_AUTOMATION_WEBHOOK_URL" in payload["references"]


def test_cli_show_config_outputs_redacted_json(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["--log-format", "json", "show-config", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["app"]["name"] == "opinion-monitor"
    assert payload["llm"]["api_key_env"] == "OPENAI_API_KEY"


def test_cli_collect_hotsearch_uses_collector_and_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from opinion_monitor.collectors.hotsearch.collector import (
        HotSearchCollectionResult,
        HotSearchPlatformOutcome,
    )
    from opinion_monitor.models import HotSearchPlatform, RawItem

    class FakeCollector:
        def __init__(self, config: object, **kwargs: object) -> None:
            self.config = config
            self.kwargs = kwargs

        async def collect(self, platforms: object) -> HotSearchCollectionResult:
            collected_at = datetime(2026, 10, 8, 3, 0, tzinfo=UTC)
            items = [
                RawItem(
                    id=uuid4(),
                    source_type="hotsearch",
                    platform=HotSearchPlatform.WEIBO,
                    title=f"示例热搜{index}",
                    collected_at=collected_at,
                    rank=index,
                    collector_version="test",
                )
                for index in range(1, 4)
            ]
            return HotSearchCollectionResult(
                started_at=collected_at,
                completed_at=collected_at,
                outcomes=[
                    HotSearchPlatformOutcome(
                        platform=HotSearchPlatform.WEIBO,
                        enabled=True,
                        success=True,
                        item_count=3,
                        duration_ms=1,
                    )
                ],
                items=items,
            )

    monkeypatch.setattr("opinion_monitor.cli.HotSearchCollector", FakeCollector)

    result = main(
        [
            "--log-format",
            "json",
            "collect-hotsearch",
            "--platform",
            "weibo",
            "--limit",
            "2",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert result == 0
    assert len(payload["items"]) == 2
    assert payload["outcomes"][0]["item_count"] == 2
