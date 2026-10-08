"""小红书初始状态解析兼容层。

该兼容层移植自本地已验证的 MediaCrawler 修复，用于处理小红书页面中的
JavaScript 字面量，例如 ``undefined``、``new Set([])`` 与 ``new Map([])``。
补丁通过运行时替换固定版本上游类方法实现，不修改子模块源码。
"""

from __future__ import annotations

import json
import re
from typing import Any

_INITIAL_STATE_PATTERN = re.compile(
    r"<script[^>]*>\s*window\.__INITIAL_STATE__\s*=\s*(.*?)\s*;?\s*</script>",
    re.DOTALL,
)
_EMPTY_SET_PATTERN = re.compile(r"\bnew\s+Set\s*\(\s*\[\s*\]\s*\)")
_EMPTY_MAP_PATTERN = re.compile(r"\bnew\s+Map\s*\(\s*\[\s*\]\s*\)")
_JS_LITERAL_PATTERN = re.compile(r"(?<=[:,\[])\s*(?:undefined|NaN|Infinity)(?=\s*[,}\]])")


def extract_initial_state(html: str) -> dict[str, Any] | None:
    """从 HTML 中提取并解析 ``window.__INITIAL_STATE__``。"""

    match = _INITIAL_STATE_PATTERN.search(html)
    if match is None:
        return None

    state = match.group(1)
    state = _EMPTY_SET_PATTERN.sub("[]", state)
    state = _EMPTY_MAP_PATTERN.sub("{}", state)
    state = _JS_LITERAL_PATTERN.sub("null", state)
    try:
        parsed = json.loads(state, strict=False)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_note_detail_from_html(
    extractor_module: Any,
    note_id: str,
    html: str,
) -> dict[str, Any] | None:
    if "noteDetailMap" not in html:
        return None
    state = extract_initial_state(html)
    if state is None:
        return None
    try:
        decamelized = extractor_module.humps.decamelize(state)
        result = decamelized["note"]["note_detail_map"][note_id]["note"]
    except (KeyError, TypeError):
        return None
    return result if isinstance(result, dict) else None


def _extract_creator_info_from_html(html: str) -> dict[str, Any] | None:
    state = extract_initial_state(html)
    if state is None:
        return None
    try:
        result = state["user"]["userPageData"]
    except (KeyError, TypeError):
        return None
    return result if isinstance(result, dict) else None


def patch_xhs_extractor(extractor_module: Any) -> None:
    """为固定版本上游替换小红书 HTML 解析方法。"""

    extractor_class = extractor_module.XiaoHongShuExtractor
    extractor_class._extract_initial_state = staticmethod(extract_initial_state)
    extractor_class.extract_note_detail_from_html = lambda self, note_id, html: (
        _extract_note_detail_from_html(extractor_module, note_id, html)
    )
    extractor_class.extract_creator_info_from_html = lambda self, html: (
        _extract_creator_info_from_html(html)
    )
