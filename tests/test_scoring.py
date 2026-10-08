from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from opinion_monitor.config import load_config
from opinion_monitor.models import (
    AlertCategory,
    CleanItem,
    GeoEvidence,
    HotSearchPlatform,
    LLMAnalysisResult,
    LLMAnalysisRun,
    MediaCrawlerPlatform,
    RawItem,
    SentimentEvidence,
    utc_now,
)
from opinion_monitor.processing import CleaningPipeline
from opinion_monitor.scoring import RiskScoringService
from opinion_monitor.storage import SqliteStorage

CONFIG = load_config(Path("config/config.example.yaml"), env={})


def _raw() -> RawItem:
    return RawItem(
        id=uuid4(),
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        external_id="xhs:note-score",
        title="某市化工厂发生爆炸火灾",
        content="现场正在救援，有人员受伤。",
        url="https://example.test/note/score",
        published_at=utc_now(),
        collected_at=utc_now(),
        keyword="火灾",
        keyword_level=1,
        engagement={"like_count": 999_999},
        raw_payload={},
        collector_version="test",
    )


def _clean_item(raw: RawItem | None = None) -> CleanItem:
    source = raw or _raw()
    return CleaningPipeline(CONFIG.processing, CONFIG.rules).run([source]).accepted_items[0]


def _analysis(
    item: CleanItem,
    *,
    with_sentiment: bool = True,
) -> LLMAnalysisResult:
    return LLMAnalysisResult(
        clean_item_id=item.id,
        model="test-model",
        classification_prompt_version="classification",
        geo_prompt_version="geo",
        risk_prompt_version="risk",
        category=AlertCategory.SUDDEN_EVENT,
        category_confidence=0.92,
        category_reason="包含火灾、爆炸与伤亡表述",
        geo_evidence=[
            GeoEvidence(
                province="测试省",
                city="测试市",
                district=None,
                location_text="某市化工厂",
                confidence=0.8,
            )
        ],
        sentiment=(
            SentimentEvidence(
                total_comments=100,
                sampled_comments=100,
                distribution={"anxious": 1.0},
                dominant_sentiment="anxious",
                negative_ratio=1.0,
                anger_ratio=0.1,
                anxiety_ratio=0.9,
                distrust_ratio=0.2,
                sentiment_score=80,
                summary="评论高度担忧",
            )
            if with_sentiment
            else None
        ),
        risk_score=88,
        risk_reason="事故词、伤亡描述与负面情绪同时出现",
        key_risk_factors=["事故", "伤亡"],
        information_gaps=["官方通报尚未出现"],
        recommended_actions=["核实官方通报"],
        uncertainty_notes=["信源仍为社媒内容"],
        created_at=utc_now(),
    )


def test_risk_scoring_service_combines_components_and_levels() -> None:
    raw = _raw()
    item = _clean_item(raw)
    analysis = _analysis(item)
    service = RiskScoringService(CONFIG)

    result = service.score(item, analysis, [raw])

    components = result.assessment.components
    assert components["keyword_category"].score == 70
    assert components["source"].score == 60
    assert components["llm_category"].score == 92
    assert components["sentiment"].score == 80
    assert components["llm_risk"].score == 88
    assert components["heat"].score > 99
    assert result.assessment.overall_score == pytest.approx(81.9, abs=0.01)
    assert result.assessment.alert_level.value == "orange"
    assert result.assessment.final_category is AlertCategory.SUDDEN_EVENT
    assert result.assessment.requires_manual_review is False
    assert result.event.alert_level.value == "orange"
    assert result.event.geo_evidence[0]["city"] == "测试市"
    assert result.event.recommended_actions == ["核实官方通报"]


def test_risk_scoring_uses_llm_category_when_conflict_and_requires_review() -> None:
    raw = _raw()
    item = _clean_item(raw)
    analysis = _analysis(item, with_sentiment=False).model_copy(
        update={
            "category": AlertCategory.POLICE_STABILITY,
            "category_confidence": 0.4,
        }
    )

    result = RiskScoringService(CONFIG).score(item, analysis, [])

    assert result.assessment.final_category is AlertCategory.POLICE_STABILITY
    assert result.assessment.preliminary_category is AlertCategory.SUDDEN_EVENT
    assert result.assessment.category_conflict is True
    assert result.assessment.requires_manual_review is True
    assert any("冲突" in reason for reason in result.assessment.review_reasons)
    assert any("情感" in reason for reason in result.assessment.review_reasons)


def test_risk_scoring_normalizes_legacy_zero_to_one_sentiment_score() -> None:
    raw = _raw()
    item = _clean_item(raw)
    base = _analysis(item)
    assert base.sentiment is not None
    analysis = base.model_copy(
        update={"sentiment": base.sentiment.model_copy(update={"sentiment_score": 0.68})}
    )

    result = RiskScoringService(CONFIG).score(item, analysis, [raw])

    sentiment = result.assessment.components["sentiment"]
    assert sentiment.score == 68
    assert sentiment.evidence["raw_score"] == 0.68
    assert sentiment.evidence["scale_normalized"] is True


def test_risk_scoring_config_version_is_deterministic() -> None:
    version = RiskScoringService(CONFIG).config_version

    assert version == RiskScoringService(CONFIG).config_version
    assert len(version) == 12


def test_hotsearch_rank_uses_platform_weight() -> None:
    raw = RawItem(
        id=uuid4(),
        source_type="hotsearch",
        platform=HotSearchPlatform.WEIBO,
        external_id="weibo:hot-1",
        title="某市化工厂发生爆炸火灾",
        url="https://s.weibo.com/weibo?q=%E6%9F%90%E5%B8%82",
        published_at=utc_now(),
        collected_at=utc_now(),
        rank=1,
        hot_value=1_000_000,
        raw_payload={},
        collector_version="test",
    )
    item = _clean_item(raw)
    analysis = _analysis(item)

    result = RiskScoringService(CONFIG).score(item, analysis, [raw])

    heat = result.assessment.components["heat"]
    assert heat.evidence["rank"] == 1
    assert heat.evidence["platform_top_rank_weight"] == 95
    assert heat.score == pytest.approx(0.6 * 95 + 0.4 * 100)


def test_storage_persists_scoring_result_and_structured_event(tmp_path: Path) -> None:
    raw = _raw()
    item = _clean_item(raw)
    analysis = _analysis(item)
    storage = SqliteStorage(tmp_path / "state.db")
    storage.initialise()
    storage.save_raw_items([raw])
    storage.save_processing_result(CleaningPipeline(CONFIG.processing, CONFIG.rules).run([raw]))
    assert storage.list_clean_items_ready_for_scoring() == []

    storage.save_llm_analysis_run(
        LLMAnalysisRun(
            clean_item_id=item.id,
            executed=True,
            prompts=[],
            result=analysis,
        )
    )
    assert storage.list_clean_items_ready_for_scoring()[0].id == item.id

    result = RiskScoringService(CONFIG).score(
        item,
        analysis,
        storage.list_raw_items_for_clean_item(item.id),
    )
    storage.save_scoring_run(result)

    assert storage.list_clean_items_ready_for_scoring() == []
    assert storage.stats()["risk_assessments"] == 1
    assert storage.stats()["structured_output_events"] == 1
    with sqlite3.connect(storage.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_cli_previews_risk_assessment_without_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml

    from opinion_monitor.cli import main

    raw = _raw()
    item = _clean_item(raw)
    config = CONFIG.model_dump(mode="json")
    config["storage"]["sqlite"]["path"] = str(tmp_path / "state.db")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    storage = SqliteStorage(config["storage"]["sqlite"]["path"])
    storage.initialise()
    storage.save_raw_items([raw])
    storage.save_processing_result(CleaningPipeline(CONFIG.processing, CONFIG.rules).run([raw]))
    storage.save_llm_analysis_run(
        LLMAnalysisRun(
            clean_item_id=item.id,
            executed=True,
            prompts=[],
            result=_analysis(item),
        )
    )

    exit_code = main(["--config", str(config_path), "preview-risk-assessment"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["items"][0]["status"] == "succeeded"
    assert payload["items"][0]["assessment"]["overall_score"] > 0
    assert storage.stats()["risk_assessments"] == 0
