"""MediaCrawler 固定版本启动包装器。

该包装器只做运行前配置映射，不修改上游源码、不绕过平台验证。
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE_ROOT))

from opinion_monitor.collectors.mediacrawler.xhs_compat import (  # noqa: E402
    patch_xhs_extractor,
)

_TRUE = {"1", "true", "yes", "y", "t"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def main() -> None:
    upstream_root = Path.cwd()
    sys.path.insert(0, str(upstream_root))
    config: Any = __import__("config")
    xhs_extractor: Any = __import__(
        "media_platform.xhs.extractor", fromlist=["XiaoHongShuExtractor"]
    )
    patch_xhs_extractor(xhs_extractor)

    config.ENABLE_CDP_MODE = _env_bool("OPINION_MONITOR_ENABLE_CDP_MODE", True)
    config.CDP_CONNECT_EXISTING = _env_bool("OPINION_MONITOR_CDP_CONNECT_EXISTING", True)
    config.CDP_DEBUG_PORT = _env_int("OPINION_MONITOR_CDP_DEBUG_PORT", 9222)
    config.CDP_HEADLESS = _env_bool("OPINION_MONITOR_CDP_HEADLESS", False)
    config.HEADLESS = config.CDP_HEADLESS
    config.SAVE_LOGIN_STATE = _env_bool("OPINION_MONITOR_SAVE_LOGIN_STATE", True)
    config.CRAWLER_MAX_SLEEP_SEC = _env_int("OPINION_MONITOR_CRAWLER_MAX_SLEEP_SEC", 2)

    entrypoint = upstream_root / "main.py"
    sys.argv = [str(entrypoint), *sys.argv[1:]]
    runpy.run_path(str(entrypoint), run_name="__main__")


if __name__ == "__main__":
    main()
