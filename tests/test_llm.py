from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from opinion_monitor.config import load_config
from opinion_monitor.llm import LLMClient, extract_json_content, load_prompt, render_prompt
from opinion_monitor.llm.service import LLMAnalysisService
from opinion_monitor.models import (
    AlertCategory,
    CommentRecord,
    LLMAnalysisRun,
    LLMUsage,
    MediaCrawlerPlatform,
    RawItem,
    utc_now,
)
from opinion_monitor.processing import CleaningPipeline
from opinion_monitor.storage import SqliteStorage

CONFIG = load_config(Path("config/config.example.yaml"), env={})
ENV = {
    "OPENAI_BASE_URL": "https://llm.example.test/v1",
    "OPENAI_API_KEY": "test-key",
    "OPENAI_MODEL": "test-model",
}


def test_extract_json_content_removes_json_fence() -> None:
    assert extract_json_content('```json\n{"ok": true}\n```') == {"ok": True}


def test_prompt_loader_returns_stable_version_and_system_section() -> None:
    template, version = load_prompt(CONFIG.llm, "classification")

    assert "预警资讯属性分类" in template
    assert len(version) == 12
    assert "只依据输入文本" in load_prompt(CONFIG.llm, "classification")[0]
    assert "{{PAYLOAD_JSON}}" in template


def test_render_prompt_replaces_payload() -> None:
    rendered = render_prompt("{{PAYLOAD_JSON}}", {"title": "火灾"})

    assert rendered == '{"title": "火灾"}'


async def test_llm_client_retries_and_parses_response() -> None:
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = LLMClient(
        CONFIG.llm,
        env=ENV,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )
    output, usage = await client.chat_json(
        system_prompt="system",
        user_prompt="user",
    )

    assert output == {"ok": True}
    assert usage.total_tokens == 15
    assert len(calls) == 2
    assert calls[0].headers["Authorization"] == "Bearer test-key"
    assert b"json_object" in calls[0].read()
    assert sleeps == [0.1]


def _clean_item() -> Any:
    raw = RawItem(
        id=uuid4(),
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        external_id="xhs:note-1",
        title="某市化工厂发生爆炸火灾",
        content="现场正在救援，有人员受伤。",
        url="https://example.test/note/1",
        published_at=utc_now(),
        collected_at=utc_now(),
        keyword="火灾",
        keyword_level=1,
        raw_payload={},
        collector_version="test",
    )
    return CleaningPipeline(CONFIG.processing, CONFIG.rules).run([raw]).accepted_items[0]


def _comment(item: Any, content: str = "希望人员平安") -> CommentRecord:
    return CommentRecord(
        id=uuid4(),
        task_id=uuid4(),
        platform=MediaCrawlerPlatform.XHS,
        note_external_id=item.external_id,
        external_comment_id=f"xhs:comment-{uuid4()}",
        content=content,
        collected_at=utc_now(),
        raw_payload={},
        collector_version="test",
    )


class FakeClient:
    model = "fake-model"

    async def chat_json(self, *, system_prompt: str, user_prompt: str) -> tuple[Any, LLMUsage]:
        if "属性分类" in system_prompt:
            return (
                {
                    "category": "sudden_event",
                    "confidence": 0.92,
                    "reason": "文本包含爆炸、火灾与人员受伤",
                },
                LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        if "地域实体" in system_prompt:
            return (
                {
                    "geo_evidence": [
                        {
                            "province": "测试省",
                            "city": "测试市",
                            "district": None,
                            "location_text": "某市化工厂",
                            "confidence": 0.8,
                        }
                    ]
                },
                LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        if "风险研判" in system_prompt:
            return (
                {
                    "risk_score": 88.0,
                    "risk_reason": "事故词、伤亡描述与负面情绪同时出现",
                    "key_risk_factors": ["事故", "伤亡", "公众担忧"],
                    "information_gaps": ["官方通报尚未出现"],
                    "recommended_actions": ["核实官方通报", "关注救援进展"],
                    "uncertainty_notes": ["信源仍为社媒内容"],
                },
                LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        if "评论情感" in system_prompt:
            return (
                {
                    "distribution": {"anxious": 1.0},
                    "dominant_sentiment": "anxious",
                    "negative_ratio": 1.0,
                    "anger_ratio": 0.0,
                    "anxiety_ratio": 1.0,
                    "distrust_ratio": 0.0,
                    "sentiment_score": 80.0,
                    "summary": "评论高度担忧人员安全",
                    "uncertainty": "样本量较小",
                },
                LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        raise AssertionError(f"未知 Prompt：{system_prompt}")


async def test_llm_analysis_service_preview_and_execute() -> None:
    item = _clean_item()
    comments = [_comment(item, "希望人员平安"), _comment(item, "一定要平安")]
    service = LLMAnalysisService(CONFIG.llm, env=ENV, client=FakeClient())

    preview = service.preview(item, comments)
    assert [request.task for request in preview] == [
        "classification",
        "geo_extraction",
        "risk_assessment",
        "sentiment_analysis",
    ]

    run = await service.analyze(item, comments, execute=True)
    assert run.executed is True
    assert run.audit is not None
    assert run.audit.status == "succeeded"
    assert run.audit.attempts == 4
    assert run.audit.usage is not None
    assert run.audit.usage.total_tokens == 60
    assert run.result is not None
    assert run.result.category is AlertCategory.SUDDEN_EVENT
    assert run.result.category_confidence == 0.92
    assert run.result.geo_evidence[0].city == "测试市"
    assert run.result.sentiment is not None
    assert run.result.sentiment.sampled_comments == 2
    assert run.result.risk_score == 88.0
    assert "核实官方通报" in run.result.recommended_actions


async def test_llm_analysis_service_without_comments_skips_sentiment_call() -> None:
    item = _clean_item()
    service = LLMAnalysisService(CONFIG.llm, env=ENV, client=FakeClient())
    run = await service.analyze(item, [], execute=True)

    assert run.audit is not None
    assert run.audit.attempts == 3
    assert run.result is not None
    assert run.result.sentiment is not None
    assert run.result.sentiment.total_comments == 0
    assert run.result.sentiment.dominant_sentiment == "unknown"


async def test_llm_analysis_service_records_validation_failure() -> None:
    item = _clean_item()

    class InvalidClient(FakeClient):
        async def chat_json(self, *, system_prompt: str, user_prompt: str) -> tuple[Any, LLMUsage]:
            output, usage = await super().chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            if "属性分类" in system_prompt:
                output["category"] = "invalid-category"
            return output, usage

    service = LLMAnalysisService(CONFIG.llm, env=ENV, client=InvalidClient())
    run = await service.analyze(item, [], execute=True)

    assert run.audit is not None
    assert run.audit.status == "failed"
    assert "输出校验失败" in (run.audit.error or "")
    assert run.result is None


def test_storage_associates_comments_and_saves_llm_analysis(tmp_path: Path) -> None:
    item = _clean_item()
    comment = _comment(item)
    storage = SqliteStorage(tmp_path / "state.db")
    storage.initialise()
    # CleanItem 的来源 RawItem 用于评论关联。
    raw = RawItem(
        id=item.raw_item_id,
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        external_id=item.external_id,
        title=item.title,
        content=item.content,
        url=item.canonical_url,
        published_at=item.published_at,
        collected_at=item.collected_at,
        raw_payload={},
        collector_version="test",
    )
    storage.save_raw_items([raw])
    storage.save_comments([comment])
    processing = CleaningPipeline(CONFIG.processing, CONFIG.rules).run([raw])
    # 使用服务测试中的有效结果结构构造保存记录。
    from opinion_monitor.models import LLMAnalysisResult, LLMAuditRecord

    audit = LLMAuditRecord(
        clean_item_id=item.id,
        status="succeeded",
        model="fake-model",
        started_at=utc_now(),
        completed_at=utc_now(),
        duration_ms=1,
        attempts=1,
        request_digest="digest",
        usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    result = LLMAnalysisResult(
        clean_item_id=item.id,
        model="fake-model",
        classification_prompt_version="classification",
        geo_prompt_version="geo",
        risk_prompt_version="risk",
        category=AlertCategory.SUDDEN_EVENT,
        category_confidence=0.9,
        category_reason="测试",
        risk_score=80,
        risk_reason="测试",
        created_at=utc_now(),
    )
    service_result = LLMAnalysisRun(
        clean_item_id=item.id,
        executed=True,
        prompts=[],
        result=result,
        audit=audit,
    )
    storage.save_processing_result(processing)
    assert storage.list_clean_items_missing_analysis()[0].id == item.id
    assert [entry.id for entry in storage.list_comments_for_clean_item(item.id)] == [comment.id]

    storage.save_llm_analysis_run(service_result)
    assert storage.list_clean_items_missing_analysis() == []
    assert storage.stats()["llm_analysis_results"] == 1


def test_cli_previews_llm_analysis_without_model_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    import yaml

    from opinion_monitor.cli import main

    item = _clean_item()
    config = CONFIG.model_dump(mode="json")
    config["storage"]["sqlite"]["path"] = str(tmp_path / "state.db")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    storage = SqliteStorage(config["storage"]["sqlite"]["path"])
    storage.initialise()
    raw = RawItem(
        id=item.raw_item_id,
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        external_id=item.external_id,
        title=item.title,
        content=item.content,
        collected_at=item.collected_at,
        raw_payload={},
        collector_version="test",
    )
    storage.save_raw_items([raw])
    storage.save_processing_result(CleaningPipeline(CONFIG.processing, CONFIG.rules).run([raw]))

    result = main(["--config", str(config_path), "preview-llm-analysis"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["items"][0]["clean_item_id"] == str(item.id)
    assert payload["items"][0]["comment_count"] == 0
    assert [task["task"] for task in payload["items"][0]["prompts"]] == [
        "classification",
        "geo_extraction",
        "risk_assessment",
    ]
