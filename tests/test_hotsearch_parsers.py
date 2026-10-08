from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opinion_monitor.collectors.hotsearch.parsers import get_hotsearch_parser
from opinion_monitor.collectors.interfaces import HotSearchDocument, HotSearchParseError
from opinion_monitor.models import HotSearchPlatform

FIXTURE_DIR = Path("tests/fixtures/hotsearch")
COLLECTED_AT = datetime(2026, 10, 8, 2, 30, tzinfo=UTC)
REQUEST_URLS = {
    HotSearchPlatform.WEIBO: "https://s.weibo.com/top/summary",
    HotSearchPlatform.BAIDU: "https://top.baidu.com/board?tab=realtime",
    HotSearchPlatform.ZHIHU: "https://www.zhihu.com/hot",
    HotSearchPlatform.DOUYIN: "https://www.douyin.com/aweme/v1/web/hot/search/list/",
    HotSearchPlatform.BILIBILI: "https://api.bilibili.com/x/web-interface/search/square?limit=50",
}
FIXTURES = {
    HotSearchPlatform.WEIBO: "weibo.html",
    HotSearchPlatform.BAIDU: "baidu.html",
    HotSearchPlatform.ZHIHU: "zhihu.html",
    HotSearchPlatform.DOUYIN: "douyin.json",
    HotSearchPlatform.BILIBILI: "bilibili.json",
}


def load_document(platform: HotSearchPlatform) -> HotSearchDocument:
    path = FIXTURE_DIR / FIXTURES[platform]
    return HotSearchDocument(
        platform=platform,
        request_url=REQUEST_URLS[platform],
        status_code=200,
        content_type="text/html" if path.suffix == ".html" else "application/json",
        body=path.read_text(encoding="utf-8"),
        collected_at=COLLECTED_AT,
    )


@pytest.mark.parametrize(
    ("platform", "first_title", "first_hot_value"),
    [
        (HotSearchPlatform.WEIBO, "示例热搜一", 12345),
        (HotSearchPlatform.BAIDU, "示例百度热搜一", 4_560_000),
        (HotSearchPlatform.ZHIHU, "示例知乎热榜1", 98765),
        (HotSearchPlatform.DOUYIN, "示例抖音热搜一", 987654),
        (HotSearchPlatform.BILIBILI, "示例B站热搜一", 98765),
    ],
)
def test_parses_all_platform_fixtures(
    platform: HotSearchPlatform,
    first_title: str,
    first_hot_value: int,
) -> None:
    items = get_hotsearch_parser(platform).parse(load_document(platform))

    assert len(items) == 3
    assert [item.rank for item in items] == [1, 2, 3]
    assert items[0].title == first_title
    assert items[0].hot_value == first_hot_value
    assert items[0].source_type == "hotsearch"
    assert items[0].collected_at == COLLECTED_AT
    assert items[0].collector_version == "hotsearch-parser-v1"
    assert len({item.id for item in items}) == 3


def test_weibo_parses_relative_and_absolute_urls() -> None:
    items = get_hotsearch_parser(HotSearchPlatform.WEIBO).parse(
        load_document(HotSearchPlatform.WEIBO)
    )

    assert (
        items[0].url == "https://s.weibo.com/weibo?q=%E7%A4%BA%E4%BE%8B%E7%83%AD%E6%90%9C%E4%B8%80"
    )
    assert items[2].url == "https://s.weibo.com/weibo?q=example"
    assert items[0].raw_payload["label"] == "热"


def test_baidu_parses_url_and_content() -> None:
    items = get_hotsearch_parser(HotSearchPlatform.BAIDU).parse(
        load_document(HotSearchPlatform.BAIDU)
    )

    assert items[0].url == "https://example.test/baidu/1"
    assert items[0].content == "示例说明一"
    assert items[1].hot_value == 123456


def test_zhihu_parses_url_and_content() -> None:
    items = get_hotsearch_parser(HotSearchPlatform.ZHIHU).parse(
        load_document(HotSearchPlatform.ZHIHU)
    )

    assert items[0].url == "https://example.test/zhihu/1"
    assert items[0].content == "示例说明1"


def test_parser_rejects_platform_mismatch() -> None:
    with pytest.raises(HotSearchParseError, match="解析器平台不匹配"):
        get_hotsearch_parser(HotSearchPlatform.WEIBO).parse(load_document(HotSearchPlatform.BAIDU))


@pytest.mark.parametrize(
    ("platform", "body"),
    [
        (HotSearchPlatform.WEIBO, "<html><body><table><tbody></tbody></table></body></html>"),
        (HotSearchPlatform.BAIDU, "<html><body></body></html>"),
        (
            HotSearchPlatform.ZHIHU,
            "<html><body><script id='js-initialData'>{}</script></body></html>",
        ),
        (HotSearchPlatform.DOUYIN, '{"data":{"word_list":[]}}'),
        (HotSearchPlatform.BILIBILI, '{"data":{"result":[]}}'),
    ],
)
def test_parser_rejects_empty_results(platform: HotSearchPlatform, body: str) -> None:
    document = HotSearchDocument(
        platform=platform,
        request_url=REQUEST_URLS[platform],
        status_code=200,
        body=body,
        collected_at=COLLECTED_AT,
    )

    with pytest.raises(HotSearchParseError, match="没有可解析"):
        get_hotsearch_parser(platform).parse(document)
