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
