from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from opinion_monitor.collectors.hotsearch.collector import HotSearchCollector
from opinion_monitor.collectors.hotsearch.http import HotSearchHTTPClient, HotSearchHTTPError
from opinion_monitor.collectors.interfaces import HotSearchDocument
from opinion_monitor.config import load_config
from opinion_monitor.models import HotSearchPlatform, utc_now

FIXTURE_DIR = Path("tests/fixtures/hotsearch")


def fixture_document(platform: HotSearchPlatform, filename: str) -> HotSearchDocument:
    return HotSearchDocument(
        platform=platform,
        request_url="https://example.test/source",
        status_code=200,
        body=(FIXTURE_DIR / filename).read_text(encoding="utf-8"),
        collected_at=utc_now(),
    )


async def test_collector_collects_one_platform_without_real_network() -> None:
    config = load_config(Path("config/config.example.yaml"), env={}).hotsearch
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text=(FIXTURE_DIR / "weibo.html").read_text(encoding="utf-8"),
        )
    )
    client = HotSearchHTTPClient(
        config,
        client=httpx.AsyncClient(transport=transport),
        url_validator=lambda _url: None,
    )

    result = await HotSearchCollector(config, client=client).collect([HotSearchPlatform.WEIBO])

    assert [outcome.platform for outcome in result.outcomes] == [HotSearchPlatform.WEIBO]
    assert result.outcomes[0].success is True
    assert result.outcomes[0].item_count == 3
    assert len(result.items) == 3


async def test_collector_ignores_parse_failure_for_later_platforms() -> None:
    class SwitchingClient:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, platform: HotSearchPlatform) -> HotSearchDocument:
            self.calls += 1
            if platform is HotSearchPlatform.WEIBO:
                return fixture_document(platform, "weibo.html")
            return HotSearchDocument(
                platform=platform,
                request_url="https://example.test/source",
                status_code=200,
                body="<html></html>",
                collected_at=utc_now(),
            )

    config = load_config(Path("config/config.example.yaml"), env={}).hotsearch
    result = await HotSearchCollector(config, client=SwitchingClient()).collect(
        [HotSearchPlatform.WEIBO, HotSearchPlatform.BAIDU]
    )

    assert result.outcomes[0].success is True
    assert result.outcomes[1].success is False
    assert result.outcomes[1].error is not None
    assert "HotSearchParseError" in result.outcomes[1].error
    assert len(result.items) == 3


def test_public_url_guard_rejects_private_address() -> None:
    def resolver(_host: str) -> list[Any]:
        return [__import__("ipaddress").ip_address("192.168.1.1")]

    with pytest.raises(HotSearchHTTPError, match="禁止访问"):
        __import__("opinion_monitor.collectors.hotsearch.http", fromlist=[""]).validate_public_url(
            "https://192.168.1.1/hot",
            resolver=resolver,
        )
