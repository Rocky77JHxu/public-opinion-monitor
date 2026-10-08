"""LLM 分析任务的 OpenAI Structured Outputs JSON Schema。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

from opinion_monitor.models import AlertCategory


class SchemaError(ValueError):
    """任务响应 Schema 不存在或配置非法。"""


_NULLABLE_STRING: Final[dict[str, Any]] = {"type": ["string", "null"]}
_STRING_ARRAY: Final[dict[str, Any]] = {"type": "array", "items": {"type": "string"}}

_CLASSIFICATION_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": [category.value for category in AlertCategory],
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["category", "confidence", "reason"],
    "additionalProperties": False,
}

_GEO_EXTRACTION_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "geo_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "province": _NULLABLE_STRING,
                    "city": _NULLABLE_STRING,
                    "district": _NULLABLE_STRING,
                    "location_text": _NULLABLE_STRING,
                    "confidence": {"type": "number"},
                },
                "required": [
                    "province",
                    "city",
                    "district",
                    "location_text",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["geo_evidence"],
    "additionalProperties": False,
}

_RISK_ASSESSMENT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "risk_score": {"type": "number"},
        "risk_reason": {"type": "string"},
        "key_risk_factors": _STRING_ARRAY,
        "information_gaps": _STRING_ARRAY,
        "recommended_actions": _STRING_ARRAY,
        "uncertainty_notes": _STRING_ARRAY,
    },
    "required": [
        "risk_score",
        "risk_reason",
        "key_risk_factors",
        "information_gaps",
        "recommended_actions",
        "uncertainty_notes",
    ],
    "additionalProperties": False,
}

_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "classification": _CLASSIFICATION_SCHEMA,
    "geo_extraction": _GEO_EXTRACTION_SCHEMA,
    "risk_assessment": _RISK_ASSESSMENT_SCHEMA,
}


def _sentiment_schema(categories: list[str]) -> dict[str, Any]:
    """为配置的情感类别生成固定的 distribution 键。"""

    normalized: list[str] = []
    for category in categories:
        if not category or category in normalized:
            raise SchemaError("sentiment.categories 必须是非空且不重复的类别名")
        normalized.append(category)
    if not normalized:
        raise SchemaError("sentiment.categories 不能为空")

    distribution_properties = {category: {"type": "number"} for category in normalized}
    return {
        "type": "object",
        "properties": {
            "distribution": {
                "type": "object",
                "properties": distribution_properties,
                "required": normalized,
                "additionalProperties": False,
            },
            "dominant_sentiment": {"type": "string", "enum": normalized},
            "negative_ratio": {"type": "number"},
            "anger_ratio": {"type": "number"},
            "anxiety_ratio": {"type": "number"},
            "distrust_ratio": {"type": "number"},
            "sentiment_score": {"type": "number"},
            "summary": {"type": "string"},
            "uncertainty": _NULLABLE_STRING,
        },
        "required": [
            "distribution",
            "dominant_sentiment",
            "negative_ratio",
            "anger_ratio",
            "anxiety_ratio",
            "distrust_ratio",
            "sentiment_score",
            "summary",
            "uncertainty",
        ],
        "additionalProperties": False,
    }


def build_response_schema(
    task: str,
    *,
    sentiment_categories: list[str] | None = None,
) -> dict[str, Any]:
    """返回指定任务的严格 JSON Schema，并隔离内部常量。"""

    if task == "sentiment_analysis":
        return _sentiment_schema(sentiment_categories or [])
    try:
        return deepcopy(_SCHEMAS[task])
    except KeyError as exc:
        raise SchemaError(f"未知的 LLM 结构化输出任务：{task}") from exc
