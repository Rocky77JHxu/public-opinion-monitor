"""综合评分、预警级别分类与结构化事件生成服务。"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Sequence
from typing import Any

from opinion_monitor.config.schema import RootConfig
from opinion_monitor.models import (
    AlertLevel,
    CleanItem,
    HotSearchPlatform,
    LLMAnalysisResult,
    RawItem,
    RiskAssessmentResult,
    ScoreComponent,
    ScoreComponentName,
    ScoringRunResult,
    StructuredOutputEvent,
    utc_now,
)

_HOTSEARCH_RANK_BASELINE = 50
_ENGAGEMENT_SCORE_REFERENCE = 1_000_000


class RiskScoringService:
    """按配置把规则证据、LLM 证据与热度证据合成为可审计研判。"""

    def __init__(self, config: RootConfig) -> None:
        self._config = config
        self._config_version = self._calculate_config_version(config)

    @property
    def config_version(self) -> str:
        return self._config_version

    @staticmethod
    def _calculate_config_version(config: RootConfig) -> str:
        payload = {
            "rules": config.rules.model_dump(mode="json"),
            "source_weights": config.source_weights.model_dump(mode="json"),
            "platform_heat": {
                platform.value: platform_config.model_dump(mode="json")
                for platform, platform_config in config.platform_heat.items()
            },
            "scoring": config.scoring.model_dump(mode="json"),
            "alert_levels": config.alert_levels.model_dump(mode="json"),
            "sentiment_weights": config.sentiment.weights,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:12]

    @staticmethod
    def _clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
        return max(minimum, min(maximum, value))

    @staticmethod
    def _component(
        name: ScoreComponentName,
        *,
        score: float,
        weight: float,
        evidence: dict[str, Any],
        explanation: str,
    ) -> ScoreComponent:
        normalized_score = RiskScoringService._clamp(score)
        return ScoreComponent(
            name=name,
            score=round(normalized_score, 4),
            weight=weight,
            weighted_score=round(normalized_score * weight, 4),
            evidence=evidence,
            explanation=explanation,
        )

    def _keyword_category_score(self, item: CleanItem) -> ScoreComponent:
        category = item.preliminary_category
        config = self._config.rules.categories[category]
        score = config.weight * item.preliminary_category_confidence
        return self._component(
            "keyword_category",
            score=score,
            weight=self._config.scoring.weights.keyword_category,
            evidence={
                "category": category.value,
                "category_weight": config.weight,
                "confidence": item.preliminary_category_confidence,
                "reason": item.preliminary_category_reason,
            },
            explanation=(
                f"规则分类 {category.value} 的类别权重 {config.weight} 乘以置信度 "
                f"{item.preliminary_category_confidence}。"
            ),
        )

    def _source_score(self, item: CleanItem) -> ScoreComponent:
        source_kind = "default"
        score = self._config.source_weights.default

        if item.source_type == "account":
            account = self._config.account_search.accounts.get(item.account_config_id or "")
            if account is not None:
                source_kind = f"account:{item.account_config_id}"
                score = account.weight
                detail = "使用指定账号配置中的来源权重。"
            else:
                source_kind = "ordinary_social_media"
                score = self._config.source_weights.ordinary_social_media
                detail = "账号配置不可用，按普通社媒来源降权处理。"
        elif item.source_type == "keyword_search":
            source_kind = "ordinary_social_media"
            score = self._config.source_weights.ordinary_social_media
            detail = "关键词检索结果按普通社媒来源处理。"
        else:
            detail = "热搜来源缺少权威性标注，使用默认来源权重。"

        return self._component(
            "source",
            score=score,
            weight=self._config.scoring.weights.source,
            evidence={
                "source_type": item.source_type,
                "source_kind": source_kind,
                "account_config_id": item.account_config_id,
            },
            explanation=detail,
        )

    @staticmethod
    def _logarithmic_engagement_score(total: int) -> float:
        if total <= 0:
            return 0.0
        reference_log = math.log10(1 + _ENGAGEMENT_SCORE_REFERENCE)
        return RiskScoringService._clamp(100 * math.log10(1 + total) / reference_log)

    def _heat_score(self, item: CleanItem, raw_items: Sequence[RawItem]) -> ScoreComponent:
        engagement_totals = [sum(item.engagement.values()) for item in raw_items]
        hot_values = [raw.hot_value or 0 for raw in raw_items]
        interaction_total = max([*engagement_totals, *hot_values, 0])
        engagement_score = self._logarithmic_engagement_score(interaction_total)

        ranked = [raw for raw in raw_items if raw.rank is not None]
        platform_weight: float | None = None
        rank_score: float | None = None
        rank_value: int | None = None
        if ranked:
            rank_value = min(raw.rank or _HOTSEARCH_RANK_BASELINE for raw in ranked)
            platform_value = ranked[0].platform.value
            platform_config = self._config.platform_heat.get(HotSearchPlatform(platform_value))
            platform_weight = (
                platform_config.top_rank_weight if platform_config is not None else None
            )
            rank_base = self._clamp(100 * (1 - (rank_value - 1) / _HOTSEARCH_RANK_BASELINE))
            rank_score = rank_base
            if platform_weight is not None:
                rank_score = self._clamp(rank_base * platform_weight / 100)

        if rank_score is not None:
            score = self._clamp(0.6 * rank_score + 0.4 * engagement_score)
            method = "热搜排名 60% + 互动/热度值 40%"
        else:
            score = engagement_score
            method = "互动量对数基线"

        evidence: dict[str, Any] = {
            "source_count": len(raw_items),
            "interaction_total": interaction_total,
            "engagement_score": round(engagement_score, 4),
            "method": method,
            "rank": rank_value,
            "rank_score": round(rank_score, 4) if rank_score is not None else None,
            "platform_top_rank_weight": platform_weight,
            "engagement_reference": _ENGAGEMENT_SCORE_REFERENCE,
        }
        if interaction_total == 0:
            explanation = "没有可用排名、热度值或互动量，热度分项按 0 处理。"
        elif rank_score is not None:
            explanation = f"按 {method} 计算；最高排名为 {rank_value}。"
        else:
            explanation = "没有热搜排名，按互动量对数基线计算。"

        return self._component(
            "heat",
            score=score,
            weight=self._config.scoring.weights.heat,
            evidence=evidence,
            explanation=explanation,
        )

    def _llm_category_score(self, analysis: LLMAnalysisResult) -> ScoreComponent:
        category = analysis.category
        config = self._config.rules.categories[category]
        score = config.weight * analysis.category_confidence
        return self._component(
            "llm_category",
            score=score,
            weight=self._config.scoring.weights.llm_category,
            evidence={
                "category": category.value,
                "category_weight": config.weight,
                "confidence": analysis.category_confidence,
                "reason": analysis.category_reason,
                "prompt_version": analysis.classification_prompt_version,
            },
            explanation=(
                f"LLM 分类 {category.value} 的类别权重 {config.weight} 乘以置信度 "
                f"{analysis.category_confidence}。"
            ),
        )

    def _sentiment_score(self, analysis: LLMAnalysisResult) -> ScoreComponent:
        sentiment = analysis.sentiment
        if sentiment is None:
            return self._component(
                "sentiment",
                score=0,
                weight=self._config.scoring.weights.sentiment,
                evidence={"available": False},
                explanation="没有可用的 LLM 情感证据，情感分项按 0 分处理。",
            )
        # 兼容早期模型把 0-100 分误解为 0-1 比例的输出；Prompt 已明确要求 0-100。
        normalized_score = sentiment.sentiment_score
        scale_normalized = 0 < normalized_score <= 1
        if scale_normalized:
            normalized_score *= 100
        return self._component(
            "sentiment",
            score=normalized_score,
            weight=self._config.scoring.weights.sentiment,
            evidence={
                "available": True,
                "raw_score": sentiment.sentiment_score,
                "scale_normalized": scale_normalized,
                "total_comments": sentiment.total_comments,
                "sampled_comments": sentiment.sampled_comments,
                "dominant_sentiment": sentiment.dominant_sentiment,
                "negative_ratio": sentiment.negative_ratio,
                "distribution": sentiment.distribution,
                "summary": sentiment.summary,
            },
            explanation=(
                f"评论情感分由 LLM 聚合结果给出；采样 {sentiment.sampled_comments} / "
                f"{sentiment.total_comments} 条，主导情感为 {sentiment.dominant_sentiment}。"
                + ("检测到 0-1 分值，已按 0-100 标尺归一化。" if scale_normalized else "")
            ),
        )

    def _llm_risk_score(self, analysis: LLMAnalysisResult) -> ScoreComponent:
        return self._component(
            "llm_risk",
            score=analysis.risk_score,
            weight=self._config.scoring.weights.llm_risk,
            evidence={
                "risk_score": analysis.risk_score,
                "risk_reason": analysis.risk_reason,
                "key_risk_factors": analysis.key_risk_factors,
                "information_gaps": analysis.information_gaps,
                "prompt_version": analysis.risk_prompt_version,
            },
            explanation="直接采用 LLM 风险研判分数，并保留理由与信息缺口。",
        )

    def _alert_level(self, score: float) -> tuple[AlertLevel, str, str]:
        levels = [
            (AlertLevel.RED, self._config.alert_levels.red),
            (AlertLevel.ORANGE, self._config.alert_levels.orange),
            (AlertLevel.BLUE, self._config.alert_levels.blue),
            (AlertLevel.ARCHIVE, self._config.alert_levels.archive),
        ]
        for level, config in levels:
            if score >= config.min_score:
                return (
                    level,
                    config.label,
                    f"综合得分 {score:.2f}，达到 {config.label} 阈值 {config.min_score}。",
                )
        archive = self._config.alert_levels.archive
        return (
            AlertLevel.ARCHIVE,
            archive.label,
            f"综合得分 {score:.2f}，低于全部显式阈值，归入 {archive.label}。",
        )

    @staticmethod
    def _event_id(clean_item_id: uuid.UUID) -> uuid.UUID:
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"opinion-monitor:structured-event:{clean_item_id}",
        )

    def score(
        self,
        item: CleanItem,
        analysis: LLMAnalysisResult,
        raw_items: Sequence[RawItem],
    ) -> ScoringRunResult:
        """生成综合评分、预警级别和面向产出层的事件。"""

        if analysis.clean_item_id != item.id:
            raise ValueError("LLM 分析结果的 clean_item_id 与清洗条目不一致")

        components: dict[ScoreComponentName, ScoreComponent] = {}
        for component in (
            self._keyword_category_score(item),
            self._source_score(item),
            self._heat_score(item, raw_items),
            self._llm_category_score(analysis),
            self._sentiment_score(analysis),
            self._llm_risk_score(analysis),
        ):
            components[component.name] = component

        overall_score = round(sum(part.weighted_score for part in components.values()), 4)
        alert_level, alert_label, alert_reason = self._alert_level(overall_score)
        category_conflict = item.preliminary_category != analysis.category
        conflict_reason = (
            f"规则分类为 {item.preliminary_category.value}，"
            f"LLM 分类为 {analysis.category.value}；最终采用 LLM 分类。"
            if category_conflict
            else None
        )
        review_reasons: list[str] = []
        if analysis.category_confidence < self._config.scoring.manual_review_confidence:
            review_reasons.append(
                f"LLM 分类置信度 {analysis.category_confidence} 低于人工复核阈值 "
                f"{self._config.scoring.manual_review_confidence}。"
            )
        if category_conflict:
            review_reasons.append("规则分类与 LLM 分类存在冲突。")
        if analysis.sentiment is None:
            review_reasons.append("缺少评论情感证据。")

        assessment = RiskAssessmentResult(
            clean_item_id=item.id,
            final_category=analysis.category,
            final_category_confidence=analysis.category_confidence,
            category_conflict=category_conflict,
            category_conflict_reason=conflict_reason,
            preliminary_category=item.preliminary_category,
            preliminary_category_confidence=item.preliminary_category_confidence,
            llm_category=analysis.category,
            components=components,
            overall_score=overall_score,
            alert_level=alert_level,
            alert_level_label=alert_label,
            alert_level_reason=alert_reason,
            requires_manual_review=bool(review_reasons),
            review_reasons=review_reasons,
            risk_reason=analysis.risk_reason,
            key_risk_factors=analysis.key_risk_factors,
            information_gaps=analysis.information_gaps,
            recommended_actions=analysis.recommended_actions,
            uncertainty_notes=analysis.uncertainty_notes,
            model=analysis.model,
            scoring_config_version=self._config_version,
            created_at=utc_now(),
        )

        sentiment_summary = (
            f"{analysis.sentiment.dominant_sentiment}，情感分 "
            f"{analysis.sentiment.sentiment_score:.2f}。"
            if analysis.sentiment is not None
            else None
        )
        event = StructuredOutputEvent(
            event_id=self._event_id(item.id),
            trace_id=item.id,
            clean_item_id=item.id,
            title=item.title,
            summary=analysis.risk_reason,
            source_type=item.source_type,
            platform=item.platform.value,
            url=item.canonical_url,
            category=assessment.final_category,
            alert_level=assessment.alert_level,
            alert_level_label=alert_label,
            overall_score=overall_score,
            geo_evidence=[evidence.model_dump(mode="json") for evidence in analysis.geo_evidence],
            sentiment_summary=sentiment_summary,
            key_risk_factors=analysis.key_risk_factors,
            recommended_actions=analysis.recommended_actions,
            uncertainty_notes=analysis.uncertainty_notes,
            created_at=assessment.created_at,
        )
        return ScoringRunResult(clean_item_id=item.id, assessment=assessment, event=event)
