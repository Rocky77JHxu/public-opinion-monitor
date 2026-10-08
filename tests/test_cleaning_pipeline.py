from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from opinion_monitor.config import load_config
from opinion_monitor.models import AlertCategory, MediaCrawlerPlatform, RawItem, utc_now
from opinion_monitor.processing import CleaningPipeline

CONFIG_PATH = Path("config/config.example.yaml")


def raw_item(
    *,
    title: str,
    content: str | None = None,
    url: str | None = None,
    published_at: datetime | None = None,
    external_id: str = "id",
) -> RawItem:
    return RawItem(
        id=uuid4(),
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        external_id=f"xhs:{external_id}",
        title=title,
        content=content,
        url=url,
        published_at=published_at,
        collected_at=utc_now(),
        keyword="火灾",
        keyword_level=1,
        raw_payload={"test": True},
        collector_version="test",
    )


def pipeline() -> CleaningPipeline:
    config = load_config(CONFIG_PATH, env={})
    return CleaningPipeline(config.processing, config.rules)


def test_pipeline_filters_expired_items_and_keeps_missing_time() -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    expired = raw_item(
        title="旧火灾消息",
        published_at=now - timedelta(hours=73),
        external_id="old",
    )
    missing_time = raw_item(title="新火灾消息", external_id="new")

    result = pipeline().run([expired, missing_time], reference_time=now)

    assert result.input_count == 2
    assert result.accepted_count == 1
    assert result.discarded_count == 1
    assert result.discarded_items[0].reason == "expired"
    assert result.accepted_items[0].title == "新火灾消息"


def test_pipeline_can_drop_missing_published_time_by_policy() -> None:
    config = load_config(CONFIG_PATH, env={})
    config.processing.date_filter.missing_published_at_policy = "drop"
    item = raw_item(title="缺少发布时间", external_id="missing")

    result = CleaningPipeline(config.processing, config.rules).run([item])

    assert result.accepted_count == 0
    assert result.discarded_items[0].reason == "missing_published_at"


def test_pipeline_deduplicates_by_canonical_url_and_merges_sources() -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    first = raw_item(
        title="火灾通报一",
        url="https://example.test/a/?xsec_token=one&b=2&a=1",
        published_at=now - timedelta(minutes=10),
        external_id="first",
    )
    duplicate = raw_item(
        title="同一火灾通报",
        url="https://example.test/a/?xsec_token=two&a=1&b=2",
        published_at=now - timedelta(minutes=5),
        external_id="second",
    )

    result = pipeline().run([duplicate, first], reference_time=now)

    assert result.accepted_count == 1
    assert result.discarded_count == 1
    accepted = result.accepted_items[0]
    assert accepted.title == "火灾通报一"
    assert accepted.source_raw_item_ids == [first.id, duplicate.id]
    assert result.discarded_items[0].details["duplicate_of_clean_id"] == str(accepted.id)


def test_pipeline_deduplicates_similar_titles() -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    first = raw_item(title="某市化工厂发生火灾", external_id="one")
    second = raw_item(title="某市化工厂发生火灾！", external_id="two")

    result = pipeline().run([first, second], reference_time=now)

    assert result.accepted_count == 1
    assert result.discarded_count == 1


def test_pipeline_classifies_rule_category() -> None:
    item = raw_item(title="某地化工厂爆炸起火", content="现场有人员受伤")
    result = pipeline().run([item], reference_time=datetime(2026, 10, 9, tzinfo=UTC))

    assert result.accepted_items[0].preliminary_category is AlertCategory.SUDDEN_EVENT
    assert result.accepted_items[0].preliminary_category_confidence >= 0.60
