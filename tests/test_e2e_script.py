from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "e2e-test.sh"


def test_e2e_script_help_is_available() -> None:
    result = subprocess.run(  # noqa: S603 - 测试固定仓库内脚本
        [str(SCRIPT), "--help"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--execute" in result.stdout
    assert "--skip-account" in result.stdout
    assert "--generate-only" in result.stdout


def test_e2e_script_generate_only_creates_isolated_config(tmp_path: Path) -> None:
    root = tmp_path / "e2e"
    result = subprocess.run(  # noqa: S603 - 测试固定仓库内脚本
        [
            str(SCRIPT),
            "--generate-only",
            "--skip-tests",
            "--skip-account",
            "--config",
            str(PROJECT_ROOT / "config/config.example.yaml"),
            "--env-file",
            str(PROJECT_ROOT / ".env.example"),
            "--root",
            str(root),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))

    assert config["app"]["environment"] == "testing"
    assert config["storage"]["sqlite"]["path"] == str(root / "opinion_monitor.db")
    assert config["hotsearch"]["defaults"]["max_items_per_platform"] == 1
    assert config["keyword_search"]["levels"]["level_1"]["keywords"] == ["火灾"]
    assert config["keyword_search"]["levels"]["level_1"]["platforms"] == ["xhs"]
    assert config["account_search"]["defaults"]["enabled"] is False
    assert metadata["skip_account"] is True
    assert metadata["hotsearch_platforms"] == ["baidu", "bilibili"]
    assert str(root) in result.stdout
