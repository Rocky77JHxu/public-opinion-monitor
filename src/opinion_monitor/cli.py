"""舆情监测系统命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import structlog
import yaml

from opinion_monitor import __version__
from opinion_monitor.collectors.hotsearch import HotSearchCollector
from opinion_monitor.collectors.mediacrawler import (
    MediaCrawlerIntegrationService,
    MediaCrawlerLoadContext,
    MediaCrawlerRunner,
    build_account_task,
    build_account_tasks,
    build_keyword_task,
    build_keyword_tasks,
    load_jsonl,
)
from opinion_monitor.config import (
    ConfigError,
    build_environment,
    collect_env_references,
    find_missing_environment_variables,
    load_config,
    read_yaml_config,
    redact_sensitive_values,
)
from opinion_monitor.config.schema import RootConfig
from opinion_monitor.models import HotSearchPlatform, MediaCrawlerPlatform
from opinion_monitor.observability import configure_logging

DEFAULT_CONFIG_PATH = Path("config/config.example.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opinion-monitor",
        description="舆情采集与研判流水线",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="YAML 配置文件路径",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="KEY=VALUE 环境变量文件路径；进程内已有变量优先",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="覆盖配置文件中的日志级别",
    )
    parser.add_argument(
        "--log-format",
        choices=["console", "json"],
        default=None,
        help="覆盖配置文件中的日志格式",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate-config",
        help="校验 YAML 结构、取值范围与环境变量引用",
    )
    validate.add_argument(
        "--strict-env",
        action="store_true",
        help="要求所有 *_env 引用的环境变量均已存在",
    )
    validate.set_defaults(handler=run_validate_config)

    show = subparsers.add_parser(
        "show-config",
        help="输出脱敏后的规范化配置",
    )
    show.add_argument(
        "--format",
        choices=["json", "yaml"],
        default="json",
        help="输出格式",
    )
    show.set_defaults(handler=run_show_config)

    inspect_env = subparsers.add_parser(
        "inspect-env",
        help="查看配置引用的环境变量与缺失情况",
    )
    inspect_env.set_defaults(handler=run_inspect_env)

    collect_hotsearch = subparsers.add_parser(
        "collect-hotsearch",
        help="采集已启用的热搜平台并输出结构化 JSON",
    )
    collect_hotsearch.add_argument(
        "--platform",
        action="append",
        choices=[platform.value for platform in HotSearchPlatform],
        help="只采集指定平台；可重复传入。默认采集全部已启用平台",
    )
    collect_hotsearch.add_argument(
        "--limit",
        type=int,
        default=None,
        help="每个平台最多输出的条目数",
    )
    collect_hotsearch.add_argument(
        "--fail-on-error",
        action="store_true",
        help="任一平台失败时返回非零退出码；默认仅在全部失败时返回非零",
    )
    collect_hotsearch.set_defaults(handler=run_collect_hotsearch)

    plan_mediacrawler = subparsers.add_parser(
        "plan-mediacrawler",
        help="生成 MediaCrawler 任务与隔离命令计划；不执行采集",
    )
    plan_mediacrawler.add_argument(
        "--source",
        choices=["keyword", "account", "all"],
        default="all",
        help="任务来源",
    )
    plan_mediacrawler.add_argument(
        "--platform",
        action="append",
        choices=[platform.value for platform in MediaCrawlerPlatform],
        help="只保留指定平台；可重复传入",
    )
    plan_mediacrawler.add_argument(
        "--limit",
        type=int,
        default=None,
        help="最多输出的任务数",
    )
    plan_mediacrawler.set_defaults(handler=run_plan_mediacrawler)

    load_mediacrawler = subparsers.add_parser(
        "load-mediacrawler",
        help="加载 MediaCrawler JSONL 并输出统一 RawItem",
    )
    load_mediacrawler.add_argument("--path", type=Path, required=True, help="JSONL 文件路径")
    load_mediacrawler.add_argument(
        "--task-id",
        required=True,
        help="产生该文件的任务 ID",
    )
    load_mediacrawler.add_argument(
        "--platform",
        required=True,
        choices=[platform.value for platform in MediaCrawlerPlatform],
    )
    load_mediacrawler.add_argument(
        "--source-type",
        required=True,
        choices=["keyword_search", "account"],
    )
    load_mediacrawler.add_argument("--keyword", default=None)
    load_mediacrawler.add_argument("--keyword-level", type=int, default=None)
    load_mediacrawler.add_argument("--account-config-id", default=None)
    load_mediacrawler.add_argument("--limit", type=int, default=None)
    load_mediacrawler.set_defaults(handler=run_load_mediacrawler)

    run_media_parser = subparsers.add_parser(
        "run-mediacrawler",
        help="构建并执行单个 MediaCrawler 任务；默认仅输出计划",
    )
    run_media_parser.add_argument(
        "--source",
        choices=["keyword", "account"],
        required=True,
        help="任务来源",
    )
    run_media_parser.add_argument(
        "--platform",
        choices=[platform.value for platform in MediaCrawlerPlatform],
        help="关键词任务平台",
    )
    run_media_parser.add_argument("--keyword", help="关键词")
    run_media_parser.add_argument(
        "--keyword-level",
        type=int,
        default=1,
        help="关键词层级",
    )
    run_media_parser.add_argument("--max-items", type=int, default=None, help="最大条目数")
    run_media_parser.add_argument("--account-config-id", help="账号配置 ID")
    run_media_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="每个 JSONL 文件最多加载条数",
    )
    run_media_parser.add_argument(
        "--execute",
        action="store_true",
        help="显式执行任务；未传时只生成计划",
    )
    run_media_parser.set_defaults(handler=run_mediacrawler)

    return parser


def _environment_and_config(
    args: argparse.Namespace,
    *,
    strict_env: bool = False,
) -> tuple[dict[str, str], RootConfig]:
    environment = dict(build_environment(args.env_file))
    config = load_config(args.config, env=environment, strict_env=strict_env)
    return environment, config


def run_validate_config(args: argparse.Namespace) -> int:
    environment = dict(build_environment(args.env_file))
    config = load_config(args.config, env=environment, strict_env=args.strict_env)
    references = find_missing_environment_variables(
        read_yaml_config(args.config),
        environment,
    )

    logger = structlog.get_logger()
    logger.info(
        "配置校验通过",
        config_path=str(args.config),
        environment=config.app.environment,
        timezone=config.app.timezone,
        strict_env=args.strict_env,
        missing_env=references,
    )
    return 0


def run_show_config(args: argparse.Namespace) -> int:
    _environment, config = _environment_and_config(args)
    payload: dict[str, Any] = redact_sensitive_values(
        config.model_dump(mode="json", by_alias=False)
    )

    if args.format == "yaml":
        print(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), end="")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_inspect_env(args: argparse.Namespace) -> int:
    environment = dict(build_environment(args.env_file))
    document = read_yaml_config(args.config)
    references = find_missing_environment_variables(document, environment)
    # 先做 Schema 校验，确保环境报告来自有效配置。
    load_config(args.config, env=environment)
    payload = {
        "config": str(args.config),
        "env_file": str(args.env_file) if args.env_file else None,
        "references": collect_env_references(document),
        "missing": references,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_collect_hotsearch(args: argparse.Namespace) -> int:
    _environment, config = _environment_and_config(args)
    platforms = (
        [HotSearchPlatform(platform) for platform in args.platform] if args.platform else None
    )
    result = asyncio.run(
        HotSearchCollector(
            config.hotsearch,
            allow_private_network=config.security.allow_private_network,
        ).collect(platforms)
    )

    if args.limit is not None and args.limit >= 0:
        grouped: dict[str, list[int]] = {}
        for index, item in enumerate(result.items):
            grouped.setdefault(item.platform.value, []).append(index)
        keep: set[int] = set()
        for indexes in grouped.values():
            keep.update(indexes[: args.limit])
        result = result.model_copy(
            update={
                "items": [item for index, item in enumerate(result.items) if index in keep],
                "outcomes": [
                    outcome.model_copy(update={"item_count": min(outcome.item_count, args.limit)})
                    if outcome.success
                    else outcome
                    for outcome in result.outcomes
                ],
            }
        )

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))

    successful = any(outcome.success for outcome in result.outcomes)
    has_failure = any(not outcome.success and outcome.enabled for outcome in result.outcomes)
    if not successful or (args.fail_on_error and has_failure):
        return 2
    return 0


def run_plan_mediacrawler(args: argparse.Namespace) -> int:
    _environment, config = _environment_and_config(args)

    tasks = []
    if args.source in {"keyword", "all"}:
        tasks.extend(build_keyword_tasks(config))
    if args.source in {"account", "all"}:
        tasks.extend(build_account_tasks(config))

    if args.platform:
        selected = {MediaCrawlerPlatform(platform) for platform in args.platform}
        tasks = [task for task in tasks if task.platform in selected]
    if args.limit is not None and args.limit >= 0:
        tasks = tasks[: args.limit]

    runner = MediaCrawlerRunner(config.mediacrawler)
    payload = {
        "allow_execution": config.mediacrawler.allow_execution,
        "task_count": len(tasks),
        "tasks": [
            {
                "task": task.model_dump(mode="json"),
                "command": runner.build_plan(task).model_dump(mode="json"),
            }
            for task in tasks
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_load_mediacrawler(args: argparse.Namespace) -> int:
    context = MediaCrawlerLoadContext(
        task_id=args.task_id,
        platform=MediaCrawlerPlatform(args.platform),
        source_type=args.source_type,
        keyword=args.keyword,
        keyword_level=args.keyword_level,
        account_config_id=args.account_config_id,
    )
    result = load_jsonl(args.path, context, limit=args.limit)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.loaded_count > 0 else 2


def run_mediacrawler(args: argparse.Namespace) -> int:
    _environment, config = _environment_and_config(args)

    if args.source == "keyword":
        if not args.platform:
            raise ConfigError("关键词任务必须提供 --platform")
        if not args.keyword:
            raise ConfigError("关键词任务必须提供 --keyword")
        task = build_keyword_task(
            config,
            platform=MediaCrawlerPlatform(args.platform),
            keyword=args.keyword,
            keyword_level=args.keyword_level,
            max_items=args.max_items,
        )
    else:
        if not args.account_config_id:
            raise ConfigError("指定账号任务必须提供 --account-config-id")
        task = build_account_task(config, args.account_config_id)

    result = asyncio.run(
        MediaCrawlerIntegrationService(config.mediacrawler).run(
            task,
            execute=args.execute,
            limit=args.limit,
        )
    )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if args.execute and result.run.status.value != "succeeded":
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config, env=build_environment(args.env_file))
        log_level = args.log_level or config.app.log_level
        log_format = args.log_format or config.app.log_format
    except ConfigError:
        # 配置本身不可用时，仍允许用命令行覆盖初始化日志并返回清晰错误。
        log_level = args.log_level or "INFO"
        log_format = args.log_format or "console"

    configure_logging(log_level, log_format)

    try:
        handler = cast(Callable[[argparse.Namespace], int], args.handler)
        result: int = handler(args)
    except ConfigError as exc:
        structlog.get_logger().error("命令执行失败", command=args.command, error=str(exc))
        return 2
    return result


if __name__ == "__main__":
    raise SystemExit(main())
