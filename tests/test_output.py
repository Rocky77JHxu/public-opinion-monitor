from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from opinion_monitor.config import load_config
from opinion_monitor.config.schema import RootConfig
from opinion_monitor.models import AlertCategory, AlertLevel, StructuredOutputEvent, utc_now
from opinion_monitor.output import DingTalkOutputError, DingTalkOutputService, DingTalkWebhookClient

CONFIG = load_config(Path("config/config.example.yaml"), env={})
ENV = {"DINGTALK_AUTOMATION_WEBHOOK_URL": "https://dingtalk.example.test/webhook"}


def _event(
    *,
    title: str = "某市化工厂发生爆炸火灾",
) -> StructuredOutputEvent:
    clean_item_id = uuid4()
    return StructuredOutputEvent(
        event_id=uuid4(),
        trace_id=clean_item_id,
        clean_item_id=clean_item_id,
        title=title,
        summary="联系人 13800138000，证件 11010119900307861X，需要核实。",
        source_type="keyword_search",
        platform="xhs",
        url="https://example.test/note/1",
        category=AlertCategory.SUDDEN_EVENT,
        alert_level=AlertLevel.ORANGE,
        alert_level_label="橙色 - 关注核实",
        overall_score=76.5,
        geo_evidence=[
            {
                "province": "测试省",
                "city": "测试市",
                "district": None,
                "location_text": "某市化工厂",
                "confidence": 0.8,
                "author_id": "user-should-be-masked",
            }
        ],
        sentiment_summary="anxious，情感分 80.00。",
        key_risk_factors=["事故", "伤亡"],
        recommended_actions=["核实官方通报"],
        uncertainty_notes=["信源仍为社媒内容"],
        created_at=datetime(2026, 10, 9, tzinfo=UTC),
    )


def _public_network_config() -> RootConfig:
    return CONFIG.model_copy(
        update={"security": CONFIG.security.model_copy(update={"allow_private_network": True})}
    )


def test_automation_payload_contains_trigger_keyword_and_redacts_sensitive_text() -> None:
    service = DingTalkOutputService(CONFIG, env=ENV)

    prepared = service.prepare(_event())

    assert prepared.payload["schema_version"] == 1
    assert prepared.payload["source_system"] == "opinion_monitor"
    assert prepared.payload["event_type"] == "opinion_monitor.alert"
    assert prepared.payload["keyword"] == "舆情预警"
    assert prepared.payload["event_id"] == prepared.payload["data"]["event_id"]
    assert prepared.payload["dedup_key"] == prepared.payload["data"]["event_id"]
    assert "13800138000" not in prepared.payload_json
    assert "[手机号]" in prepared.payload_json
    assert "11010119900307861X" not in prepared.payload_json
    assert "[身份证号]" in prepared.payload_json
    assert "user-should-be-masked" not in prepared.payload_json
    assert len(prepared.payload_hash) == 64


def test_markdown_payload_uses_dingtalk_robot_schema() -> None:
    dingtalk = CONFIG.output.dingtalk.model_copy(update={"send_mode": "markdown"})
    output = CONFIG.output.model_copy(update={"dingtalk": dingtalk})
    config = CONFIG.model_copy(update={"output": output})
    service = DingTalkOutputService(config, env=ENV)

    prepared = service.prepare(_event())

    assert prepared.payload["msgtype"] == "markdown"
    assert prepared.payload["markdown"]["title"].startswith("舆情预警｜橙色")
    assert "**来源系统：**`opinion_monitor`" in prepared.payload["markdown"]["text"]
    assert "[手机号]" in prepared.payload["markdown"]["text"]
    assert "[身份证号]" in prepared.payload["markdown"]["text"]
    assert "[查看来源](https://example.test/note/1)" in prepared.payload["markdown"]["text"]


async def test_webhook_client_retries_and_accepts_success_response() -> None:
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = DingTalkWebhookClient(
        _public_network_config(),
        env=ENV,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )
    status_code, body = await client.post({"keyword": "舆情预警"})

    assert status_code == 200
    assert json.loads(body)["errcode"] == 0
    assert len(calls) == 2
    assert json.loads(calls[0].read()) == {"keyword": "舆情预警"}
    assert sleeps == [CONFIG.output.dingtalk.retry_backoff_seconds]


async def test_webhook_client_rejects_business_error_without_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"errcode": 310000, "errmsg": "keyword mismatch"})

    client = DingTalkWebhookClient(
        _public_network_config(),
        env=ENV,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DingTalkOutputError, match="业务错误"):
        await client.post({"keyword": "舆情预警"})
    assert len(calls) == 1


async def test_webhook_client_blocks_private_address() -> None:
    def resolver(hostname: str) -> list[str]:
        assert hostname == "internal.example.test"
        return ["192.168.1.1"]

    client = DingTalkWebhookClient(
        CONFIG,
        env={"DINGTALK_AUTOMATION_WEBHOOK_URL": "https://internal.example.test/hook"},
        resolver=resolver,
    )

    with pytest.raises(DingTalkOutputError, match="禁止访问"):
        await client.post({"keyword": "舆情预警"})


async def test_webhook_client_rejects_placeholder_url() -> None:
    client = DingTalkWebhookClient(
        _public_network_config(),
        env={"DINGTALK_AUTOMATION_WEBHOOK_URL": "replace-me"},
    )

    with pytest.raises(DingTalkOutputError, match="占位符"):
        await client.post({"keyword": "舆情预警"})


async def test_output_service_dry_run_does_not_request_network() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("dry-run 不应发送请求")

    service = DingTalkOutputService(
        _public_network_config(),
        env={},
        transport=httpx.MockTransport(handler),
    )
    result = await service.deliver(_event(), dry_run=True)

    assert result.status == "dry_run"
    assert result.attempt is not None
    assert result.attempt.status == "dry_run"
    assert result.record.attempt_count == 1
    assert result.record.payload_hash == result.attempt.payload_hash


async def test_output_service_records_http_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    service = DingTalkOutputService(
        _public_network_config(),
        env=ENV,
        transport=httpx.MockTransport(handler),
    )
    result = await service.deliver(_event(), dry_run=False)

    assert result.status == "failed"
    assert result.record.response_status_code == 400
    assert result.attempt is not None
    assert result.attempt.response_status_code == 400
    assert "HTTP 状态码异常" in (result.record.error or "")


def _insert_event(storage_path: Path, event: StructuredOutputEvent) -> None:
    from opinion_monitor.storage import SqliteStorage

    storage = SqliteStorage(storage_path)
    storage.initialise()
    with sqlite3.connect(storage.path) as connection:
        connection.execute(
            """
            INSERT INTO structured_output_events (
                event_id, clean_item_id, event_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(event.event_id),
                str(event.clean_item_id),
                event.model_dump_json(),
                event.created_at.isoformat(),
                utc_now().isoformat(),
            ),
        )


async def test_storage_persists_delivery_and_attempt_ledger(tmp_path: Path) -> None:
    from opinion_monitor.storage import SqliteStorage

    database_path = tmp_path / "state.db"
    event = _event()
    _insert_event(database_path, event)
    storage = SqliteStorage(database_path)

    assert storage.list_structured_output_events()[0].event_id == event.event_id

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True})

    service = DingTalkOutputService(
        _public_network_config(),
        env=ENV,
        transport=httpx.MockTransport(handler),
    )
    succeeded = await service.deliver(event, dry_run=False)
    storage.save_dingtalk_delivery_result(succeeded)
    assert storage.list_structured_output_events() == []
    assert storage.get_dingtalk_delivery(event.event_id) is not None
    assert [
        attempt.attempt_number for attempt in storage.list_dingtalk_attempts(event.event_id)
    ] == [1]

    failed = await service.deliver(
        event,
        dry_run=False,
        attempt_offset=succeeded.record.attempt_count,
    )
    storage.save_dingtalk_delivery_result(failed)
    attempts = storage.list_dingtalk_attempts(event.event_id)
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert storage.stats()["dingtalk_deliveries"] == 1
    assert storage.stats()["dingtalk_delivery_attempts"] == 2


def test_cli_previews_dingtalk_payload_without_network_or_ledger(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml

    from opinion_monitor.cli import main
    from opinion_monitor.storage import SqliteStorage

    event = _event()
    database_path = tmp_path / "state.db"
    _insert_event(database_path, event)
    config = CONFIG.model_dump(mode="json")
    config["storage"]["sqlite"]["path"] = str(database_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = main(["--config", str(config_path), "preview-dingtalk-output"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["events"][0]["event_id"] == str(event.event_id)
    assert payload["events"][0]["payload"]["keyword"] == "舆情预警"
    storage = SqliteStorage(database_path)
    assert storage.stats()["dingtalk_deliveries"] == 0
    assert isinstance(UUID(payload["events"][0]["event_id"]), UUID)


def test_cli_send_dingtalk_output_dry_run_writes_ledger(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml

    from opinion_monitor.cli import main
    from opinion_monitor.storage import SqliteStorage

    event = _event()
    database_path = tmp_path / "state.db"
    _insert_event(database_path, event)
    config = CONFIG.model_dump(mode="json")
    config["storage"]["sqlite"]["path"] = str(database_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = main(["--config", str(config_path), "send-dingtalk-output"])
    payload = json.loads(capsys.readouterr().out)
    storage = SqliteStorage(database_path)

    assert result == 0
    assert payload["events"][0]["status"] == "dry_run"
    assert storage.stats()["dingtalk_deliveries"] == 1
    assert storage.stats()["dingtalk_delivery_attempts"] == 1
