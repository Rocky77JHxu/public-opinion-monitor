from __future__ import annotations

import subprocess
import sys


def test_cli_reports_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "opinion_monitor.cli", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "0.1.0"
