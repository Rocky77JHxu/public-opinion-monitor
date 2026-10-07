from __future__ import annotations

import pytest
import structlog

from opinion_monitor.observability import configure_logging


def test_configure_logging_supports_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", log_format="json")

    structlog.get_logger("test").info("日志初始化正常", value=1)

    captured = capsys.readouterr()
    assert '"event": "日志初始化正常"' in captured.out
    assert '"value": 1' in captured.out
