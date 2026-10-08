"""微博、百度、知乎、抖音与 bilibili 的热搜解析器。

解析器只负责把平台响应转换成统一 ``RawItem``，不执行业务分类、评分或持久化。
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from urllib.parse import urljoin
from uuid import UUID, uuid5

from bs4 import BeautifulSoup, Tag

from opinion_monitor.collectors.interfaces import HotSearchDocument, HotSearchParseError
from opinion_monitor.models import HotSearchPlatform, RawItem

COLLECTOR_VERSION = "hotsearch-parser-v1"
_ITEM_NAMESPACE = UUID("63afe19e-4329-4d73-a800-b733e15eb701")


class BaseHotSearchParser(ABC):
    """热搜解析器基类。"""

    platform: HotSearchPlatform

    def parse(self, document: HotSearchDocument) -> list[RawItem]:
        if document.platform is not self.platform:
            msg = f"解析器平台不匹配：expected={self.platform}, actual={document.platform}"
            raise HotSearchParseError(msg)
        items = self._parse_document(document)
        if not items:
            msg = f"{self.platform.value} 响应中没有可解析的热搜条目"
            raise HotSearchParseError(msg)
        return items

    @abstractmethod
    def _parse_document(self, document: HotSearchDocument) -> list[RawItem]:
        raise NotImplementedError


def _text(value: Tag | None) -> str:
    return " ".join(value.get_text(" ", strip=True).split()) if value else ""


def _parse_count(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.strip().replace(",", "").replace(" ", "")
    multiplier = 1
    if normalized.endswith("万"):
        multiplier = 10_000
        normalized = normalized[:-1]
    elif normalized.endswith("亿"):
        multiplier = 100_000_000
        normalized = normalized[:-1]
    try:
        parsed = float(normalized)
    except ValueError:
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return int(parsed * multiplier)


def _make_item(
    *,
    platform: HotSearchPlatform,
    title: str,
    rank: int,
    collected_at: datetime,
    url: str | None,
    hot_value: int | None,
    raw_payload: dict[str, Any],
    content: str | None = None,
) -> RawItem:
    normalized_title = " ".join(title.split())
    if not normalized_title:
        raise HotSearchParseError(f"{platform.value} 第 {rank} 条热搜标题为空")
    item_id = uuid5(
        _ITEM_NAMESPACE,
        f"{platform.value}:{collected_at.isoformat()}:{rank}:{normalized_title}",
    )
    return RawItem(
        id=item_id,
        source_type="hotsearch",
        platform=platform,
        external_id=f"{platform.value}:{rank}",
        title=normalized_title,
        content=content,
        url=url,
        collected_at=collected_at,
        rank=rank,
        hot_value=hot_value,
        raw_payload=raw_payload,
        collector_version=COLLECTOR_VERSION,
    )


class WeiboHotSearchParser(BaseHotSearchParser):
    """微博热搜汇总页解析器。"""

    platform = HotSearchPlatform.WEIBO

    def _parse_document(self, document: HotSearchDocument) -> list[RawItem]:
        soup = BeautifulSoup(document.body, "lxml")
        rows = soup.select("table tbody tr")
        if not rows:
            rows = soup.select('[class*="td-02"]')
        items: list[RawItem] = []
        for row in rows:
            link = row.select_one(".td-02 a[href]") or row.select_one("a[href]")
            if not isinstance(link, Tag):
                continue
            title = _text(link)
            if not title:
                continue
            rank_text = _text(row.select_one(".td-01"))
            rank = _parse_count(rank_text)
            if rank is None or rank < 1:
                rank = len(items) + 1
            href = link.get("href")
            url = urljoin(document.request_url, href) if isinstance(href, str) else None
            hot_value = _parse_count(_text(row.select_one(".td-02 span")))
            label = _text(row.select_one(".td-03"))
            items.append(
                _make_item(
                    platform=self.platform,
                    title=title,
                    rank=int(rank),
                    collected_at=document.collected_at,
                    url=url,
                    hot_value=hot_value,
                    raw_payload={
                        "source": "html",
                        "rank_text": rank_text,
                        "label": label or None,
                        "href": href if isinstance(href, str) else None,
                    },
                )
            )
        return items


class BaiduHotSearchParser(BaseHotSearchParser):
    """百度热搜页面解析器。

    页面 class 会带随机后缀，因此解析使用稳定结构与 ``class*`` 前缀匹配。
    """

    platform = HotSearchPlatform.BAIDU

    def _parse_document(self, document: HotSearchDocument) -> list[RawItem]:
        soup = BeautifulSoup(document.body, "lxml")
        cards = soup.select('[class*="category-wrap"]')
        if not cards:
            cards = soup.select("[data-index]")
        items: list[RawItem] = []
        for card in cards:
            title_node = card.select_one('[class*="c-single-text-raw"]')
            title = _text(title_node)
            if not title:
                title_node = card.select_one('[class*="title"]')
                title = _text(title_node)
            if not title:
                continue

            link = (
                card if card.name == "a" and card.has_attr("href") else card.select_one("a[href]")
            )
            href = link.get("href") if isinstance(link, Tag) else None
            url = urljoin(document.request_url, href) if isinstance(href, str) else None

            rank_node = card.select_one('[class*="hot-index"]')
            data_index = card.get("data-index")
            rank = _parse_count(rank_node.get_text(strip=True) if rank_node else None)
            if rank is None and isinstance(data_index, str):
                rank = _parse_count(data_index)
            if rank is None or rank < 1:
                rank = len(items) + 1

            score_node = card.select_one(
                '[class*="hot-score"], [class*="hot_value"], [class*="heat"]'
            )
            hot_value = _parse_count(_text(score_node))
            excerpt = _text(card.select_one('[class*="hot-desc"], [class*="excerpt"]'))
            items.append(
                _make_item(
                    platform=self.platform,
                    title=title,
                    rank=int(rank),
                    collected_at=document.collected_at,
                    url=url,
                    hot_value=hot_value,
                    content=excerpt or None,
                    raw_payload={
                        "source": "html",
                        "rank_text": rank_node.get_text(strip=True) if rank_node else None,
                        "data_index": data_index if isinstance(data_index, str) else None,
                    },
                )
            )
        return items


class ZhihuHotSearchParser(BaseHotSearchParser):
    """知乎热榜页面内嵌初始 JSON 解析器。"""

    platform = HotSearchPlatform.ZHIHU

    @staticmethod
    def _hot_list(document_json: dict[str, Any]) -> list[dict[str, Any]]:
        state = document_json.get("initialState")
        if not isinstance(state, dict):
            return []
        topstory = state.get("topstory")
        if not isinstance(topstory, dict):
            return []
        hot_list = topstory.get("hotList")
        return hot_list if isinstance(hot_list, list) else []

    def _parse_document(self, document: HotSearchDocument) -> list[RawItem]:
        soup = BeautifulSoup(document.body, "lxml")
        script = soup.select_one("script#js-initialData")
        content = script.string if script else None
        if not isinstance(content, str):
            raise HotSearchParseError("知乎页面缺少 js-initialData 数据")
        try:
            document_json = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HotSearchParseError(f"知乎 js-initialData 不是有效 JSON：{exc}") from exc

        entries = self._hot_list(document_json)
        items: list[RawItem] = []
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                continue
            target = entry.get("target")
            if not isinstance(target, dict):
                continue
            title_area = target.get("titleArea")
            title = None
            url = None
            if isinstance(title_area, dict):
                title = title_area.get("text")
                link = title_area.get("link")
                if isinstance(link, dict):
                    url = link.get("url")
            title = str(title or "").strip()
            if not title:
                continue
            excerpt_area = target.get("excerptArea")
            excerpt = excerpt_area.get("text") if isinstance(excerpt_area, dict) else None
            entry_metrics = entry.get("metrics")
            metrics = entry_metrics if isinstance(entry_metrics, dict) else {}
            hot_text = metrics.get("hot")
            hot_value = _parse_count(str(hot_text) if hot_text is not None else None)
            items.append(
                _make_item(
                    platform=self.platform,
                    title=title,
                    rank=index,
                    collected_at=document.collected_at,
                    url=str(url) if isinstance(url, str) and url.startswith("http") else None,
                    hot_value=hot_value,
                    content=str(excerpt) if isinstance(excerpt, str) and excerpt else None,
                    raw_payload={"source": "initial_data", "card_id": entry.get("id")},
                )
            )
        return items


class DouyinHotSearchParser(BaseHotSearchParser):
    """抖音热搜 JSON 接口解析器。"""

    platform = HotSearchPlatform.DOUYIN

    @staticmethod
    def _word_list(document_json: dict[str, Any]) -> list[dict[str, Any]]:
        data = document_json.get("data")
        if not isinstance(data, dict):
            return []
        words = data.get("word_list")
        return words if isinstance(words, list) else []

    def _parse_document(self, document: HotSearchDocument) -> list[RawItem]:
        try:
            document_json = json.loads(document.body)
        except json.JSONDecodeError as exc:
            raise HotSearchParseError(f"抖音响应不是有效 JSON：{exc}") from exc
        if not isinstance(document_json, dict):
            raise HotSearchParseError("抖音响应根节点必须是对象")

        entries = self._word_list(document_json)
        items: list[RawItem] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("word") or entry.get("keyword") or "").strip()
            if not title:
                continue
            position = entry.get("position")
            rank = int(position) if isinstance(position, int) and position >= 1 else len(items) + 1
            hot_value = entry.get("hot_value")
            items.append(
                _make_item(
                    platform=self.platform,
                    title=title,
                    rank=rank,
                    collected_at=document.collected_at,
                    url=None,
                    hot_value=int(hot_value)
                    if isinstance(hot_value, int) and hot_value >= 0
                    else None,
                    raw_payload={"source": "json", "original": entry},
                )
            )
        return items


class BilibiliHotSearchParser(BaseHotSearchParser):
    """bilibili 搜索广场 JSON 接口解析器。"""

    platform = HotSearchPlatform.BILIBILI

    @staticmethod
    def _result(document_json: dict[str, Any]) -> list[dict[str, Any]]:
        data = document_json.get("data")
        if not isinstance(data, dict):
            return []
        result = data.get("result")
        return result if isinstance(result, list) else []

    def _parse_document(self, document: HotSearchDocument) -> list[RawItem]:
        try:
            document_json = json.loads(document.body)
        except json.JSONDecodeError as exc:
            raise HotSearchParseError(f"bilibili 响应不是有效 JSON：{exc}") from exc
        if not isinstance(document_json, dict):
            raise HotSearchParseError("bilibili 响应根节点必须是对象")

        entries = self._result(document_json)
        items: list[RawItem] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str(
                entry.get("show_name") or entry.get("keyword") or entry.get("name") or ""
            ).strip()
            if not title:
                continue
            position = entry.get("position")
            rank = int(position) if isinstance(position, int) and position >= 1 else len(items) + 1
            score = entry.get("score")
            uri = entry.get("uri")
            items.append(
                _make_item(
                    platform=self.platform,
                    title=title,
                    rank=rank,
                    collected_at=document.collected_at,
                    url=str(uri) if isinstance(uri, str) and uri.startswith("http") else None,
                    hot_value=int(score) if isinstance(score, int) and score >= 0 else None,
                    raw_payload={"source": "json", "original": entry},
                )
            )
        return items


_PARSERS: dict[HotSearchPlatform, BaseHotSearchParser] = {
    HotSearchPlatform.WEIBO: WeiboHotSearchParser(),
    HotSearchPlatform.BAIDU: BaiduHotSearchParser(),
    HotSearchPlatform.ZHIHU: ZhihuHotSearchParser(),
    HotSearchPlatform.DOUYIN: DouyinHotSearchParser(),
    HotSearchPlatform.BILIBILI: BilibiliHotSearchParser(),
}


def get_hotsearch_parser(platform: HotSearchPlatform) -> BaseHotSearchParser:
    """获取平台解析器单例。"""

    return _PARSERS[platform]
