"""综合评分、预警级别与结构化输出事件模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.models.enums import AlertCategory, AlertLevel

ScoreComponentName = Literal[
    "keyword_category",
    "source",
    "heat",
    "llm_category",
    "sentiment",
    "llm_risk",
]


class ScoreComponent(BaseModel):
    """单个评分分项的可审计记录。"""

    model_config = ConfigDict(extra="forbid")

    name: ScoreComponentName
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    weighted_score: float = Field(ge=0, le=100)
    evidence: dict[str, Any] = Field(default_factory=dict)
    explanation: str = Field(min_length=1)


class RiskAssessmentResult(BaseModel):
    """CleanItem 与 LLM 分析结果合成后的最终研判。"""

    model_config = ConfigDict(extra="forbid")

    clean_item_id: UUID
    final_category: AlertCategory
    final_category_source: Literal["llm"] = "llm"
    final_category_confidence: float = Field(ge=0, le=1)
    category_conflict: bool
    category_conflict_reason: str | None = None
    preliminary_category: AlertCategory
    preliminary_category_confidence: float = Field(ge=0, le=1)
    llm_category: AlertCategory
    components: dict[ScoreComponentName, ScoreComponent]
    overall_score: float = Field(ge=0, le=100)
    alert_level: AlertLevel
    alert_level_label: str
    alert_level_reason: str
    requires_manual_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    risk_reason: str
    key_risk_factors: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    model: str
    scoring_config_version: str = Field(min_length=12)
    created_at: datetime


class StructuredOutputEvent(BaseModel):
    """面向产出层的最小结构化事件，不包含自然人不必要身份信息。"""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    trace_id: UUID
    clean_item_id: UUID
    title: str
    summary: str
    source_type: str
    platform: str
    url: str | None = None
    category: AlertCategory
    alert_level: AlertLevel
    alert_level_label: str
    overall_score: float = Field(ge=0, le=100)
    geo_evidence: list[dict[str, Any]] = Field(default_factory=list)
    sentiment_summary: str | None = None
    key_risk_factors: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ScoringRunResult(BaseModel):
    """一次评分执行返回的研判与结构化事件。"""

    model_config = ConfigDict(extra="forbid")

    clean_item_id: UUID
    assessment: RiskAssessmentResult
    event: StructuredOutputEvent
