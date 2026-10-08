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
from opinion_monitor.llm import LLMAnalysisService
from opinion_monitor.models import HotSearchPlatform, MediaCrawlerPlatform
from opinion_monitor.observability import configure_logging
from opinion_monitor.scoring import RiskScoringService
from opinion_monitor.storage import (
    SqliteStorage,
    ingest_and_process_media_crawler_task,
    process_pending_items,
)

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

    init_db = subparsers.add_parser(
        "init-db",
        help="初始化 SQLite 原始层与清洗层表结构",
    )
    init_db.set_defaults(handler=run_init_db)

    ingest_media = subparsers.add_parser(
        "ingest-mediacrawler-task",
        help="读取任务 JSON 与 JSONL，入库并执行 Phase 4 清洗",
    )
    ingest_media.add_argument("--task-file", type=Path, required=True, help="task.json 路径")
    ingest_media.add_argument(
        "--full",
        action="store_true",
        help="输出完整 RawItem 与评论内容；默认只输出加载统计",
    )
    ingest_media.set_defaults(handler=run_ingest_mediacrawler_task)

    process_pending = subparsers.add_parser(
        "process-pending",
        help="清洗数据库中尚未处理的 RawItem",
    )
    process_pending.set_defaults(handler=run_process_pending)

    preview_llm = subparsers.add_parser(
        "preview-llm-analysis",
        help="预览将发送给 LLM 的结构化 Prompt；不调用模型",
    )
    preview_llm.add_argument("--clean-item-id", default=None, help="CleanItem ID")
    preview_llm.set_defaults(handler=run_preview_llm_analysis)

    run_llm = subparsers.add_parser(
        "run-llm-analysis",
        help="对 CleanItem 执行 LLM 分析；默认仅预览",
    )
    run_llm.add_argument("--clean-item-id", default=None, help="CleanItem ID")
    run_llm.add_argument(
        "--all",
        action="store_true",
        help="处理全部尚无 LLM 结果的 CleanItem",
    )
    run_llm.add_argument("--limit", type=int, default=None, help="配合 --all 限制数量")
    run_llm.add_argument(
        "--execute",
        action="store_true",
        help="显式调用 OpenAI-compatible 模型；未传时只预览",
    )
    run_llm.set_defaults(handler=run_llm_analysis)

    preview_scoring = subparsers.add_parser(
        "preview-risk-assessment",
        help="预览综合评分、分项得分与预警级别；不写数据库",
    )
    preview_scoring.add_argument("--clean-item-id", default=None, help="CleanItem ID")
    preview_scoring.add_argument(
        "--all",
        action="store_true",
        help="预览全部已具备 LLM 分析结果的条目",
    )
    preview_scoring.add_argument("--limit", type=int, default=None, help="最多输出条数")
    preview_scoring.set_defaults(handler=run_preview_risk_assessment)

    run_scoring = subparsers.add_parser(
        "run-risk-assessment",
        help="生成综合评分、预警级别与结构化事件并入库",
    )
    run_scoring.add_argument("--clean-item-id", default=None, help="CleanItem ID")
    run_scoring.add_argument(
        "--all",
        action="store_true",
        help="处理全部尚无评分结果的条目",
    )
    run_scoring.add_argument("--limit", type=int, default=None, help="最多处理条数")
    run_scoring.add_argument(
        "--force",
        action="store_true",
        help="指定 CleanItem 或 --all 时允许覆盖已有评分",
    )
    run_scoring.set_defaults(handler=run_risk_assessment)

    return parser


def _environment_and_config(
    args: argparse.Namespace,
    *,
    strict_env: bool = False,
) -> tuple[dict[str, str], RootConfig]:
    environment = dict(build_environment(args.env_file))
    config = load_config(args.config, env=environment, strict_env=strict_env)
    return environment, config


def _sqlite_storage_from_config(config: RootConfig) -> SqliteStorage:
    if config.storage.backend != "sqlite":
        message = "Phase 4 当前仅实现 SQLite；请在 storage.backend 中使用 sqlite"
        raise ConfigError(message)
    return SqliteStorage(config.storage.sqlite.path)


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
            limit=args.limit if args.limit is not None else task.max_items,
        )
    )
    if args.execute:
        storage = _sqlite_storage_from_config(config)
        storage.initialise()
        storage.save_media_crawler_run(
            result.run,
            output_files=result.output_files,
        )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if args.execute and result.run.status.value != "succeeded":
        return 2
    return 0


def run_init_db(args: argparse.Namespace) -> int:
    _environment, config = _environment_and_config(args)
    storage = _sqlite_storage_from_config(config)
    storage.initialise()
    print(json.dumps(storage.stats(), ensure_ascii=False, indent=2))
    return 0


def run_ingest_mediacrawler_task(args: argparse.Namespace) -> int:
    from opinion_monitor.collectors.mediacrawler.models import MediaCrawlerTask

    _environment, config = _environment_and_config(args)
    task = MediaCrawlerTask.model_validate_json(args.task_file.read_text(encoding="utf-8"))
    summary = ingest_and_process_media_crawler_task(config, task)
    payload = summary.model_dump(mode="json")
    if not args.full:
        for load in payload["content_loads"]:
            load["items"] = []
        for load in payload["comment_loads"]:
            load["comments"] = []
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_process_pending(args: argparse.Namespace) -> int:
    _environment, config = _environment_and_config(args)
    result = process_pending_items(config)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def _llm_items_to_process(
    storage: SqliteStorage,
    args: argparse.Namespace,
) -> list[Any]:
    if args.clean_item_id:
        item = storage.get_clean_item(args.clean_item_id)
        if item is None:
            raise ConfigError(f"CleanItem 不存在：{args.clean_item_id}")
        return [item]
    items = storage.list_clean_items_missing_analysis()
    if getattr(args, "all", False):
        if getattr(args, "limit", None) is not None and args.limit >= 0:
            items = items[: args.limit]
        return items
    return items[:1]


def run_preview_llm_analysis(args: argparse.Namespace) -> int:
    _environment, config = _environment_and_config(args)
    storage = _sqlite_storage_from_config(config)
    storage.initialise()
    items = _llm_items_to_process(storage, args)
    if not items:
        print(json.dumps({"items": []}, ensure_ascii=False))
        return 0
    service = LLMAnalysisService(
        config.llm,
        env={},
        sentiment_categories=config.sentiment.categories,
    )
    previews = []
    for item in items:
        comments = storage.list_comments_for_clean_item(item.id)
        previews.append(
            {
                "clean_item_id": str(item.id),
                "comment_count": len(comments),
                "prompts": [
                    prompt.model_dump(mode="json") for prompt in service.preview(item, comments)
                ],
            }
        )
    print(json.dumps({"items": previews}, ensure_ascii=False, indent=2))
    return 0


def run_llm_analysis(args: argparse.Namespace) -> int:
    environment = dict(build_environment(args.env_file))
    _environment, config = _environment_and_config(args)
    storage = _sqlite_storage_from_config(config)
    storage.initialise()
    items = _llm_items_to_process(storage, args)
    if not items:
        print(json.dumps({"items": []}, ensure_ascii=False))
        return 0
    service = LLMAnalysisService(
        config.llm,
        env=environment,
        sentiment_categories=config.sentiment.categories,
    )
    output: list[dict[str, Any]] = []
    failed = False
    for item in items:
        comments = storage.list_comments_for_clean_item(item.id)
        run = asyncio.run(service.analyze(item, comments, execute=args.execute))
        if args.execute:
            storage.save_llm_analysis_run(run)
            if run.audit is not None and run.audit.status != "succeeded":
                failed = True
        output.append(run.model_dump(mode="json"))
    print(json.dumps({"items": output}, ensure_ascii=False, indent=2))
    return 2 if failed else 0


def _scoring_items_to_process(
    storage: SqliteStorage,
    args: argparse.Namespace,
    *,
    force: bool = False,
) -> list[Any]:
    if args.clean_item_id:
        item = storage.get_clean_item(args.clean_item_id)
        if item is None:
            raise ConfigError(f"CleanItem 不存在：{args.clean_item_id}")
        return [item]

    items = (
        storage.list_clean_items()
        if force and getattr(args, "all", False)
        else storage.list_clean_items_ready_for_scoring()
    )
    if getattr(args, "all", False):
        if getattr(args, "limit", None) is not None and args.limit >= 0:
            items = items[: args.limit]
        return items
    return items[:1]


def _run_scoring(
    args: argparse.Namespace,
    *,
    persist: bool,
) -> int:
    _environment, config = _environment_and_config(args)
    storage = _sqlite_storage_from_config(config)
    storage.initialise()
    items = _scoring_items_to_process(storage, args, force=persist and args.force)
    if not items:
        print(json.dumps({"items": []}, ensure_ascii=False))
        return 0

    service = RiskScoringService(config)
    output: list[dict[str, Any]] = []
    failed = False
    for item in items:
        analysis = storage.get_llm_analysis_result(item.id)
        if analysis is None:
            failed = True
            output.append(
                {
                    "clean_item_id": str(item.id),
                    "status": "failed",
                    "error": "缺少 LLM 分析结果，请先执行 run-llm-analysis --execute",
                }
            )
            continue
        raw_items = storage.list_raw_items_for_clean_item(item.id)
        result = service.score(item, analysis, raw_items)
        if persist:
            storage.save_scoring_run(result)
        output.append(
            {
                "status": "succeeded",
                **result.model_dump(mode="json"),
            }
        )
    print(json.dumps({"items": output}, ensure_ascii=False, indent=2))
    return 2 if failed else 0


def run_preview_risk_assessment(args: argparse.Namespace) -> int:
    return _run_scoring(args, persist=False)


def run_risk_assessment(args: argparse.Namespace) -> int:
    return _run_scoring(args, persist=True)


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
