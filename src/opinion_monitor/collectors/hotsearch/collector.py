"""热搜采集编排器。"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.collectors.hotsearch.http import HotSearchHTTPClient
from opinion_monitor.collectors.hotsearch.parsers import get_hotsearch_parser
from opinion_monitor.collectors.interfaces import HotSearchDocument
from opinion_monitor.config.schema import HotSearchConfig
from opinion_monitor.models import HotSearchPlatform, RawItem, utc_now


class HotSearchFetchClient(Protocol):
    """采集器所需的最小 HTTP 客户端接口。"""

    async def fetch(self, platform: HotSearchPlatform) -> HotSearchDocument:
        """获取平台响应文档。"""
        ...


class HotSearchPlatformOutcome(BaseModel):
    """单平台采集结果。"""

    model_config = ConfigDict(extra="forbid")

    platform: HotSearchPlatform
    enabled: bool
    success: bool
    item_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    error: str | None = None


class HotSearchCollectionResult(BaseModel):
    """一次热搜采集任务的结果。"""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    completed_at: datetime
    outcomes: list[HotSearchPlatformOutcome]
    items: list[RawItem]

    @property
    def successful_platforms(self) -> list[HotSearchPlatform]:
        return [outcome.platform for outcome in self.outcomes if outcome.success]


class HotSearchCollector:
    """顺序执行平台采集，单平台失败不影响其他平台。"""

    def __init__(
        self,
        config: HotSearchConfig,
        *,
        client: HotSearchFetchClient | None = None,
        clock: CallableClock = time.perf_counter,
        allow_private_network: bool = False,
    ) -> None:
        self._config = config
        self._client = client
        self._clock = clock
        self._allow_private_network = allow_private_network

    def enabled_platforms(self) -> list[HotSearchPlatform]:
        return [
            platform
            for platform, platform_config in self._config.platforms.items()
            if self._config.defaults.enabled and platform_config.enabled
        ]

    async def collect(
        self,
        platforms: Iterable[HotSearchPlatform] | None = None,
    ) -> HotSearchCollectionResult:
        requested = list(platforms) if platforms is not None else self.enabled_platforms()
        if not requested:
            raise ValueError("没有可执行的热搜平台")

        unknown = [platform for platform in requested if platform not in self._config.platforms]
        if unknown:
            names = ", ".join(platform.value for platform in unknown)
            raise ValueError(f"平台未配置：{names}")

        fetch_client: HotSearchFetchClient
        owned_http_client: HotSearchHTTPClient | None = None
        if self._client is None:
            owned_http_client = HotSearchHTTPClient(
                self._config,
                allow_private_network=self._allow_private_network,
            )
            fetch_client = owned_http_client
        else:
            fetch_client = self._client

        started_at = utc_now()
        outcomes: list[HotSearchPlatformOutcome] = []
        items: list[RawItem] = []
        try:
            for platform in requested:
                platform_config = self._config.platforms[platform]
                enabled = self._config.defaults.enabled and platform_config.enabled
                started_ms = self._clock()
                if not enabled:
                    outcomes.append(
                        HotSearchPlatformOutcome(
                            platform=platform,
                            enabled=False,
                            success=False,
                            item_count=0,
                            duration_ms=0,
                            error="平台未启用",
                        )
                    )
                    continue
                try:
                    document = await fetch_client.fetch(platform)
                    parsed = get_hotsearch_parser(platform).parse(document)
                except Exception as exc:
                    elapsed = max(0, int((self._clock() - started_ms) * 1000))
                    outcomes.append(
                        HotSearchPlatformOutcome(
                            platform=platform,
                            enabled=True,
                            success=False,
                            item_count=0,
                            duration_ms=elapsed,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
                    continue
                elapsed = max(0, int((self._clock() - started_ms) * 1000))
                outcomes.append(
                    HotSearchPlatformOutcome(
                        platform=platform,
                        enabled=True,
                        success=True,
                        item_count=len(parsed),
                        duration_ms=elapsed,
                    )
                )
                items.extend(parsed)
        finally:
            if owned_http_client is not None:
                await owned_http_client.aclose()

        return HotSearchCollectionResult(
            started_at=started_at,
            completed_at=datetime.now(UTC),
            outcomes=outcomes,
            items=items,
        )


CallableClock = Callable[[], float]
