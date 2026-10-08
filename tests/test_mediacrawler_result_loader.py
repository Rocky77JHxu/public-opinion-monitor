from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from opinion_monitor.collectors.mediacrawler import (
    MediaCrawlerLoadContext,
    load_jsonl,
)
from opinion_monitor.models import MediaCrawlerPlatform


def test_loads_mediacrawler_jsonl_and_normalizes_fields() -> None:
    context = MediaCrawlerLoadContext(
        task_id=uuid4(),
        platform=MediaCrawlerPlatform.XHS,
        source_type="keyword_search",
        keyword="示例关键词",
        keyword_level=1,
    )

    result = load_jsonl(Path("tests/fixtures/mediacrawler/search.jsonl"), context)

    assert result.total_lines == 5
    assert result.loaded_count == 4
    assert result.failed_count == 1
    assert len(result.items) == 4

    first = result.items[0]
    assert first.external_id == "xhs:note-1"
    assert first.title == "示例采集标题一"
    assert first.content == "示例正文一"
    assert first.url == "https://example.test/note/1"
    assert first.author_id == "user-1"
    assert first.author_name == "示例作者"
    assert first.engagement == {
        "like": 12345,
        "comment": 67,
        "share": 8,
        "read": 9,
    }
    assert first.published_at is not None
    assert first.published_at.year == 2025
    assert first.keyword == "示例关键词"
    assert first.raw_payload["source"] == "mediacrawler_jsonl"

    second = result.items[1]
    assert second.published_at is not None
    assert second.published_at.hour == 2
    assert second.engagement == {"like": 45}

    assert [error.line_number for error in result.errors] == [5]


def test_jsonl_loader_reports_missing_file() -> None:
    context = MediaCrawlerLoadContext(
        task_id=uuid4(),
        platform=MediaCrawlerPlatform.WEIBO,
        source_type="account",
        account_config_id="example",
    )

    result = load_jsonl(Path("does/not/exist.jsonl"), context)

    assert result.loaded_count == 0
    assert result.failed_count == 0
    assert "无法读取文件" in result.errors[0].reason
