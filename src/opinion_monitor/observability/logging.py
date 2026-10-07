"""structlog 日志初始化。"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from opinion_monitor.config.schema import LogFormat, LogLevel


def configure_logging(
    level: LogLevel = "INFO",
    log_format: LogFormat = "console",
) -> None:
    """初始化应用日志。

    JSON 格式便于后续接入日志平台；console 格式便于本机开发。
    日志调用方必须避免输出 Cookie、令牌、密钥与完整身份证号。
    """

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level),
        force=True,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Any
    if log_format == "json":
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )
