"""受控热搜 HTTP 客户端。"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from collections.abc import Mapping as MappingType
from types import TracebackType
from urllib.parse import urlparse

import httpx

from opinion_monitor.collectors.interfaces import HotSearchDocument
from opinion_monitor.config.schema import HotSearchConfig, HotSearchPlatformConfig
from opinion_monitor.models import HotSearchPlatform, utc_now

_DEFAULT_HEADERS: MappingType[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

Resolver = Callable[[str], list[ipaddress.IPv4Address | ipaddress.IPv6Address]]


class HotSearchHTTPError(RuntimeError):
    """热搜 HTTP 请求失败。"""


def default_resolver(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """解析主机名并返回 IP 地址列表。"""

    try:
        records = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise HotSearchHTTPError(f"无法解析热搜域名：{host}") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for record in records:
        address = record[4][0]
        if isinstance(address, bytes):
            continue
        addresses.append(ipaddress.ip_address(address))
    return addresses


def validate_public_url(
    url: str,
    *,
    resolver: Resolver = default_resolver,
) -> None:
    """拒绝回环、内网、链路本地与未指定地址，降低 SSRF 风险。"""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HotSearchHTTPError(f"热搜 URL 必须是有效 HTTP(S) 地址：{url}")
    addresses = resolver(parsed.hostname)
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            or address.is_multicast
            or address.is_reserved
        ):
            raise HotSearchHTTPError(f"热搜 URL 解析到禁止访问的地址：{address}")


class HotSearchHTTPClient:
    """带超时、重试与公共地址校验的热搜客户端。"""

    def __init__(
        self,
        config: HotSearchConfig,
        *,
        client: httpx.AsyncClient | None = None,
        allow_private_network: bool = False,
        url_validator: Callable[[str], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            timeout=config.defaults.timeout_seconds,
            follow_redirects=True,
            trust_env=False,
        )
        self._owns_client = client is None
        self._allow_private_network = allow_private_network
        self._url_validator = url_validator or validate_public_url
        self._sleep = sleep

    async def __aenter__(self) -> HotSearchHTTPClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _platform_config(self, platform: HotSearchPlatform) -> HotSearchPlatformConfig:
        try:
            return self._config.platforms[platform]
        except KeyError as exc:
            raise HotSearchHTTPError(f"平台未配置：{platform.value}") from exc

    def _headers(self, platform_config: HotSearchPlatformConfig) -> dict[str, str]:
        headers = dict(_DEFAULT_HEADERS)
        headers.update(platform_config.headers)
        return headers

    async def fetch(self, platform: HotSearchPlatform) -> HotSearchDocument:
        platform_config = self._platform_config(platform)
        if not self._allow_private_network:
            self._url_validator(platform_config.url)

        attempts_allowed = 1 + self._config.defaults.max_retries
        last_error: Exception | None = None
        for attempt in range(attempts_allowed):
            try:
                response = await self._client.get(
                    platform_config.url,
                    headers=self._headers(platform_config),
                )
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if 200 <= response.status_code < 300:
                    if not response.text.strip():
                        raise HotSearchHTTPError(f"{platform.value} 返回了空响应体")
                    return HotSearchDocument(
                        platform=platform,
                        request_url=str(response.request.url),
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        body=response.text,
                        collected_at=utc_now(),
                        response_headers={
                            key.lower(): value for key, value in response.headers.items()
                        },
                    )
                last_error = HotSearchHTTPError(
                    f"{platform.value} HTTP 状态码异常：{response.status_code}"
                )
                retryable = response.status_code in {408, 425, 429} or response.status_code >= 500
                if not retryable:
                    raise last_error

            if attempt + 1 < attempts_allowed:
                await self._sleep(self._config.defaults.retry_backoff_seconds)

        raise HotSearchHTTPError(f"{platform.value} 请求失败：{last_error}")
