"""舆情监测系统命令行入口。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import structlog
import yaml

from opinion_monitor import __version__
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
