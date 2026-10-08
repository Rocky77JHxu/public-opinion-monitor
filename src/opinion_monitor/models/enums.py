"""跨模块共享的领域枚举。"""

from enum import StrEnum


class HotSearchPlatform(StrEnum):
    WEIBO = "weibo"
    BAIDU = "baidu"
    ZHIHU = "zhihu"
    DOUYIN = "douyin"
    BILIBILI = "bilibili"


class MediaCrawlerPlatform(StrEnum):
    XHS = "xhs"
    DOUYIN = "dy"
    KUAISHOU = "ks"
    BILIBILI = "bili"
    WEIBO = "wb"
    TIEBA = "tieba"
    ZHIHU = "zhihu"


class AlertCategory(StrEnum):
    SUDDEN_EVENT = "sudden_event"
    MASS_EVENT = "mass_event"
    POLICE_STABILITY = "police_stability"
    LIVELIHOOD_SENSITIVE = "livelihood_sensitive"
    CYBER_FRAUD = "cyber_fraud"
    OTHER = "other"


class AlertLevel(StrEnum):
    RED = "red"
    ORANGE = "orange"
    BLUE = "blue"
    ARCHIVE = "archive"


class SourceType(StrEnum):
    HOTSEARCH = "hotsearch"
    KEYWORD_SEARCH = "keyword_search"
    ACCOUNT = "account"
