"""跨模块共享的领域枚举。"""

from enum import StrEnum


class HotSearchPlatform(StrEnum):
    WEIBO = "weibo"
    BAIDU = "baidu"
    ZHIHU = "zhihu"
    DOUYIN = "douyin"
    BILIBILI = "bilibili"


class SourceType(StrEnum):
    HOTSEARCH = "hotsearch"
    KEYWORD_SEARCH = "keyword_search"
    ACCOUNT = "account"
