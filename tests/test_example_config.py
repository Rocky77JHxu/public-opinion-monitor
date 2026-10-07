from __future__ import annotations

from pathlib import Path

import yaml


def test_example_config_parses_and_contains_required_sections() -> None:
    path = Path("config/config.example.yaml")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert isinstance(config, dict)
    assert {
        "app",
        "storage",
        "scheduler",
        "hotsearch",
        "keyword_search",
        "account_search",
        "mediacrawler",
        "processing",
        "rules",
        "scoring",
        "alert_levels",
        "sentiment",
        "llm",
        "output",
        "security",
    }.issubset(config)
