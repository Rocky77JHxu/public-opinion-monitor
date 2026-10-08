"""LLM 分析结果与调用审计模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opinion_monitor.models.enums import AlertCategory


class GeoEvidence(BaseModel):
    """LLM 提取的地域实体。"""

    model_config = ConfigDict(extra="forbid")

    province: str | None = None
    city: str | None = None
    district: str | None = None
    location_text: str | None = None
    confidence: float = Field(ge=0, le=1)


class SentimentEvidence(BaseModel):
    """评论情感分析结果。"""

    model_config = ConfigDict(extra="forbid")

    total_comments: int = Field(ge=0)
    sampled_comments: int = Field(ge=0)
    distribution: dict[str, float] = Field(default_factory=dict)
    dominant_sentiment: str
    negative_ratio: float = Field(ge=0, le=1)
    anger_ratio: float = Field(ge=0, le=1)
    anxiety_ratio: float = Field(ge=0, le=1)
    distrust_ratio: float = Field(ge=0, le=1)
    sentiment_score: float = Field(ge=0, le=100)
    summary: str
    uncertainty: str | None = None


class LLMUsage(BaseModel):
    """模型调用 Token 用量。"""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMAnalysisResult(BaseModel):
    """单个 CleanItem 的 LLM 研判结果。"""

    model_config = ConfigDict(extra="forbid")

    clean_item_id: UUID
    model: str
    classification_prompt_version: str
    geo_prompt_version: str | None = None
    sentiment_prompt_version: str | None = None
    risk_prompt_version: str
    category: AlertCategory
    category_confidence: float = Field(ge=0, le=1)
    category_reason: str
    geo_evidence: list[GeoEvidence] = Field(default_factory=list)
    sentiment: SentimentEvidence | None = None
    risk_score: float = Field(ge=0, le=100)
    risk_reason: str
    key_risk_factors: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    created_at: datetime


class LLMPromptRequest(BaseModel):
    """待发送的 Prompt 预览。"""

    model_config = ConfigDict(extra="forbid")

    task: str
    prompt_version: str
    system_prompt: str
    user_payload: dict[str, Any]
    expected_keys: list[str]


class LLMAuditRecord(BaseModel):
    """LLM 调用审计记录。"""

    model_config = ConfigDict(extra="forbid")

    clean_item_id: UUID
    status: str
    model: str
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    attempts: int = Field(ge=1)
    error: str | None = None
    request_digest: str
    usage: LLMUsage | None = None


class LLMAnalysisRun(BaseModel):
    """一次 LLM 分析执行结果。"""

    model_config = ConfigDict(extra="forbid")

    clean_item_id: UUID
    executed: bool
    prompts: list[LLMPromptRequest]
    result: LLMAnalysisResult | None = None
    audit: LLMAuditRecord | None = None
