"""从主配置生成 MediaCrawler 任务定义。"""

from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from opinion_monitor.collectors.mediacrawler.models import MediaCrawlerTask
from opinion_monitor.config.schema import (
    AccountConfig,
    KeywordLevelConfig,
    MediaCrawlerConfig,
    RootConfig,
)
from opinion_monitor.models import MediaCrawlerPlatform

_TASK_NAMESPACE = uuid5(NAMESPACE_URL, "opinion-monitor/mediacrawler/task/v1")


def _level_number(name: str, fallback: int) -> int:
    suffix = name.rsplit("_", 1)[-1]
    if suffix.isdigit():
        return int(suffix)
    return fallback


def _build_task(
    *,
    source_type: str,
    platform: MediaCrawlerPlatform,
    crawl_type: str,
    target: str,
    config: MediaCrawlerConfig,
    keyword_level: int | None = None,
    account_config_id: str | None = None,
    max_items: int,
) -> MediaCrawlerTask:
    identity = ":".join(
        [
            source_type,
            platform.value,
            crawl_type,
            target,
            str(keyword_level or account_config_id or ""),
        ]
    )
    task_id = uuid5(_TASK_NAMESPACE, identity)
    workspace = (Path(config.task_dir) / str(task_id)).as_posix()
    return MediaCrawlerTask(
        task_id=task_id,
        source_type=source_type,  # type: ignore[arg-type]
        platform=platform,
        crawl_type=crawl_type,  # type: ignore[arg-type]
        target=target,
        keyword_level=keyword_level,
        account_config_id=account_config_id,
        max_items=max_items,
        max_comments=config.max_comments_per_note,
        timeout_seconds=config.task_timeout_seconds,
        workspace_dir=workspace,
        input_file=(Path(workspace) / "task.json").as_posix(),
        output_file=(Path(workspace) / "output.jsonl").as_posix(),
    )


def _keyword_task(
    level_name: str,
    level_order: int,
    level: KeywordLevelConfig,
    platform: MediaCrawlerPlatform,
    keyword: str,
    config: MediaCrawlerConfig,
    max_items: int,
) -> MediaCrawlerTask:
    return _build_task(
        source_type="keyword_search",
        platform=platform,
        crawl_type="search",
        target=keyword,
        config=config,
        keyword_level=_level_number(level_name, level_order),
        max_items=max_items,
    )


def _account_task(
    account_config_id: str,
    account: AccountConfig,
    config: MediaCrawlerConfig,
) -> MediaCrawlerTask:
    return _build_task(
        source_type="account",
        platform=account.platform,
        crawl_type=account.crawl_type,
        target=account.external_id,
        config=config,
        account_config_id=account_config_id,
        max_items=account.max_items,
    )


def build_keyword_tasks(config: RootConfig) -> list[MediaCrawlerTask]:
    """构建已启用关键词层级中的全部平台 / 关键词组合。"""

    keyword_config = config.keyword_search
    if not keyword_config.defaults.enabled:
        return []

    tasks: list[MediaCrawlerTask] = []
    for level_order, (level_name, level) in enumerate(keyword_config.levels.items(), start=1):
        if not level.enabled:
            continue
        for platform in level.platforms:
            for keyword in level.keywords:
                tasks.append(
                    _keyword_task(
                        level_name,
                        level_order,
                        level,
                        platform,
                        keyword,
                        config.mediacrawler,
                        keyword_config.defaults.max_items_per_keyword,
                    )
                )
    return tasks


def build_keyword_tasks_for_level(
    config: RootConfig,
    level_name: str,
) -> list[MediaCrawlerTask]:
    """构建指定关键词层级的全部任务，供调度器独立触发。"""

    keyword_config = config.keyword_search
    level = keyword_config.levels.get(level_name)
    if level is None:
        raise ValueError(f"关键词层级不存在：{level_name}")
    if not keyword_config.defaults.enabled or not level.enabled:
        return []

    tasks: list[MediaCrawlerTask] = []
    for level_order, name in enumerate(keyword_config.levels, start=1):
        if name != level_name:
            continue
        for platform in level.platforms:
            for keyword in level.keywords:
                tasks.append(
                    _keyword_task(
                        level_name,
                        level_order,
                        level,
                        platform,
                        keyword,
                        config.mediacrawler,
                        keyword_config.defaults.max_items_per_keyword,
                    )
                )
    return tasks


def build_account_tasks(config: RootConfig) -> list[MediaCrawlerTask]:
    """构建已启用的指定账号任务。"""

    account_config = config.account_search
    if not account_config.defaults.enabled:
        return []

    return [
        _account_task(account_config_id, account, config.mediacrawler)
        for account_config_id, account in account_config.accounts.items()
        if account.enabled
    ]


def build_keyword_task(
    config: RootConfig,
    *,
    platform: MediaCrawlerPlatform,
    keyword: str,
    keyword_level: int = 1,
    max_items: int | None = None,
) -> MediaCrawlerTask:
    """构建单次关键词任务，用于手动或事件触发执行。"""

    effective_max_items = max_items or config.keyword_search.defaults.max_items_per_keyword
    return _build_task(
        source_type="keyword_search",
        platform=platform,
        crawl_type="search",
        target=keyword,
        config=config.mediacrawler,
        keyword_level=keyword_level,
        max_items=effective_max_items,
    )


def build_account_task(config: RootConfig, account_config_id: str) -> MediaCrawlerTask:
    """按配置 ID 构建单个指定账号任务。"""

    if account_config_id not in config.account_search.accounts:
        raise ValueError(f"账号配置不存在：{account_config_id}")
    account = config.account_search.accounts[account_config_id]
    if not account.enabled:
        raise ValueError(f"账号配置未启用：{account_config_id}")
    return _account_task(account_config_id, account, config.mediacrawler)
