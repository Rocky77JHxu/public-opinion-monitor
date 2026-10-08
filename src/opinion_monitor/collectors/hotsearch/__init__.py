"""热搜采集器。"""

from opinion_monitor.collectors.hotsearch.collector import (
    HotSearchCollectionResult,
    HotSearchCollector,
    HotSearchPlatformOutcome,
)
from opinion_monitor.collectors.hotsearch.http import (
    HotSearchHTTPClient,
    HotSearchHTTPError,
)
from opinion_monitor.collectors.hotsearch.parsers import (
    BaiduHotSearchParser,
    BilibiliHotSearchParser,
    DouyinHotSearchParser,
    WeiboHotSearchParser,
    ZhihuHotSearchParser,
    get_hotsearch_parser,
)

__all__ = [
    "BaiduHotSearchParser",
    "BilibiliHotSearchParser",
    "DouyinHotSearchParser",
    "HotSearchCollectionResult",
    "HotSearchCollector",
    "HotSearchHTTPClient",
    "HotSearchHTTPError",
    "HotSearchPlatformOutcome",
    "WeiboHotSearchParser",
    "ZhihuHotSearchParser",
    "get_hotsearch_parser",
]
