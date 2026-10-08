"""Prompt 文件加载、版本指纹与渲染。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from opinion_monitor.config.schema import LLMConfig


class LLMError(ValueError):
    """Prompt 或 LLM 输出错误。"""


def _prompt_path(config: LLMConfig, name: str) -> Path:
    if not name or "/" in name or "\\" in name:
        raise LLMError(f"非法 Prompt 名称：{name!r}")
    return Path(config.prompt_dir) / f"{name}.md"


def load_prompt(config: LLMConfig, name: str) -> tuple[str, str]:
    """读取 Prompt 文件，返回正文与内容 SHA-256 前 12 位版本号。"""

    path = _prompt_path(config, name)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LLMError(f"无法读取 Prompt 文件 {path}：{exc}") from exc
    if not content.strip():
        raise LLMError(f"Prompt 文件为空：{path}")
    version = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    return content, version


def render_prompt(template: str, payload: dict[str, Any]) -> str:
    """将结构化 payload 序列化为紧凑 JSON 并替换占位符。"""

    import json

    rendered = template.replace("{{PAYLOAD_JSON}}", json.dumps(payload, ensure_ascii=False))
    if "{{PAYLOAD_JSON}}" in template and "{{PAYLOAD_JSON}}" in rendered:
        raise LLMError("Prompt 占位符替换失败")
    return rendered


def system_section(template: str) -> str:
    """提取 Prompt 文件中的 System 段落。"""

    marker = "## System\n"
    if marker not in template:
        return template.strip()
    start = template.index(marker) + len(marker)
    end_marker = "\n## User Payload"
    end = template.find(end_marker, start)
    if end == -1:
        return template[start:].strip()
    return template[start:end].strip()
