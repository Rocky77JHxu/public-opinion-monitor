"""CleanItem 与评论证据的 LLM 结构化分析服务。"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast

from pydantic import ValidationError

from opinion_monitor.config.schema import LLMConfig
from opinion_monitor.llm.client import LLMClient
from opinion_monitor.llm.prompts import load_prompt, render_prompt, system_section
from opinion_monitor.models import (
    AlertCategory,
    CleanItem,
    CommentRecord,
    GeoEvidence,
    LLMAnalysisResult,
    LLMAnalysisRun,
    LLMAuditRecord,
    LLMPromptRequest,
    LLMUsage,
    SentimentEvidence,
    utc_now,
)


class LLMChatClient(Protocol):
    """LLM 分析服务所需的最小客户端接口。"""

    model: str

    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[Any, LLMUsage]:
        """调用模型并返回结构化 JSON 与用量。"""
        ...


class LLMAnalysisService:
    """构建 Prompt、调用 LLM 并校验结构化结果。"""

    def __init__(
        self,
        config: LLMConfig,
        *,
        env: Mapping[str, str],
        client: LLMChatClient | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._config = config
        self._env = env
        self._provided_client = client
        self._client: LLMChatClient | None = client
        self._clock = clock

    def _get_client(self) -> LLMChatClient:
        if self._client is None:
            self._client = cast(
                LLMChatClient,
                LLMClient(self._config, env=self._env),
            )
        if self._client is None:
            raise RuntimeError("LLM 客户端初始化失败")
        return self._client

    def _item_payload(self, item: CleanItem) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "source_type": item.source_type,
            "platform": item.platform.value,
            "title": item.title,
            "content": item.content,
            "url": item.canonical_url,
            "author_name": item.author_name,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "collected_at": item.collected_at.isoformat(),
            "keyword": item.keyword,
            "engagement": item.engagement,
            "rule_category": item.preliminary_category.value,
            "rule_category_confidence": item.preliminary_category_confidence,
        }

    def _comments_payload(
        self,
        comments: Sequence[CommentRecord],
    ) -> list[dict[str, Any]]:
        sampled = list(comments[: self._config.max_input_comments])
        return [
            {
                "content": comment.content,
                "like_count": comment.like_count,
                "published_at": comment.published_at.isoformat() if comment.published_at else None,
            }
            for comment in sampled
        ]

    def _build_requests(
        self,
        item: CleanItem,
        comments: Sequence[CommentRecord],
    ) -> list[tuple[str, LLMPromptRequest, dict[str, Any]]]:
        item_payload = self._item_payload(item)
        definitions: list[tuple[str, str, dict[str, Any], list[str]]] = [
            (
                "classification",
                "classification",
                {"item": item_payload},
                ["category", "confidence", "reason"],
            ),
            (
                "geo_extraction",
                "geo_extraction",
                {"item": item_payload},
                ["geo_evidence"],
            ),
            (
                "risk_assessment",
                "risk_assessment",
                {"item": item_payload},
                [
                    "risk_score",
                    "risk_reason",
                    "key_risk_factors",
                    "information_gaps",
                    "recommended_actions",
                    "uncertainty_notes",
                ],
            ),
        ]
        if comments:
            definitions.append(
                (
                    "sentiment_analysis",
                    "sentiment_analysis",
                    {
                        "item": {"id": str(item.id), "title": item.title},
                        "comments": self._comments_payload(comments),
                    },
                    [
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
                )
            )

        requests: list[tuple[str, LLMPromptRequest, dict[str, Any]]] = []
        for task, name, payload, expected_keys in definitions:
            template, version = load_prompt(self._config, name)
            request = LLMPromptRequest(
                task=task,
                prompt_version=version,
                system_prompt=system_section(template),
                user_payload=payload,
                expected_keys=expected_keys,
            )
            requests.append((name, request, payload))
        return requests

    def preview(
        self,
        item: CleanItem,
        comments: Sequence[CommentRecord],
    ) -> list[LLMPromptRequest]:
        return [request for _name, request, _payload in self._build_requests(item, comments)]

    @staticmethod
    def _empty_sentiment() -> SentimentEvidence:
        return SentimentEvidence(
            total_comments=0,
            sampled_comments=0,
            distribution={},
            dominant_sentiment="unknown",
            negative_ratio=0.0,
            anger_ratio=0.0,
            anxiety_ratio=0.0,
            distrust_ratio=0.0,
            sentiment_score=0.0,
            summary="没有可用评论证据，情感分项置为未知。",
            uncertainty="评论数为 0，情感结论不参与高分判断。",
        )

    async def analyze(
        self,
        item: CleanItem,
        comments: Sequence[CommentRecord],
        *,
        execute: bool,
    ) -> LLMAnalysisRun:
        triples = self._build_requests(item, comments)
        requests = [request for _name, request, _payload in triples]
        request_digest = hashlib.sha256(
            json.dumps(
                [request.model_dump(mode="json") for request in requests],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        if not execute:
            return LLMAnalysisRun(
                clean_item_id=item.id,
                executed=False,
                prompts=requests,
            )

        started_at = utc_now()
        started = self._clock()
        client = self._get_client()
        attempts = 0
        usage_total = LLMUsage()
        versions: dict[str, str] = {}
        outputs: dict[str, Any] = {}
        error: str | None = None
        try:
            for name, request, payload in triples:
                versions[name] = request.prompt_version
                user_prompt = render_prompt(
                    load_prompt(self._config, name)[0],
                    payload,
                )
                output, usage = await client.chat_json(
                    system_prompt=request.system_prompt,
                    user_prompt=user_prompt,
                )
                attempts += 1
                if usage.prompt_tokens or usage.completion_tokens or usage.total_tokens:
                    usage_total = usage_total.model_copy(
                        update={
                            "prompt_tokens": (
                                (usage_total.prompt_tokens or 0) + (usage.prompt_tokens or 0)
                            ),
                            "completion_tokens": (
                                (usage_total.completion_tokens or 0)
                                + (usage.completion_tokens or 0)
                            ),
                            "total_tokens": (
                                (usage_total.total_tokens or 0) + (usage.total_tokens or 0)
                            ),
                        }
                    )
                missing = [key for key in request.expected_keys if key not in output]
                if missing:
                    raise ValueError(f"{name} 输出缺少字段：{', '.join(missing)}")
                outputs[name] = output
        except Exception as exc:  # 保留错误给审计记录，不向上抛失上下文。
            error = f"{type(exc).__name__}: {exc}"

        completed = self._clock()
        audit = LLMAuditRecord(
            clean_item_id=item.id,
            status="failed" if error else "succeeded",
            model=client.model,
            started_at=started_at,
            completed_at=utc_now(),
            duration_ms=max(0, int((completed - started) * 1000)),
            attempts=attempts,
            error=error,
            request_digest=request_digest,
            usage=usage_total if attempts else None,
        )
        if error:
            return LLMAnalysisRun(
                clean_item_id=item.id,
                executed=True,
                prompts=requests,
                audit=audit,
            )

        classification = outputs["classification"]
        geo_output = outputs["geo_extraction"]
        risk_output = outputs["risk_assessment"]
        sentiment = self._empty_sentiment()
        if "sentiment_analysis" in outputs:
            sentiment = SentimentEvidence.model_validate(
                {
                    "total_comments": len(comments),
                    "sampled_comments": min(len(comments), self._config.max_input_comments),
                    **outputs["sentiment_analysis"],
                }
            )

        try:
            result = LLMAnalysisResult(
                clean_item_id=item.id,
                model=client.model,
                classification_prompt_version=versions["classification"],
                geo_prompt_version=versions["geo_extraction"],
                sentiment_prompt_version=versions.get("sentiment_analysis"),
                risk_prompt_version=versions["risk_assessment"],
                category=AlertCategory(classification["category"]),
                category_confidence=classification["confidence"],
                category_reason=classification["reason"],
                geo_evidence=[
                    GeoEvidence.model_validate(entry)
                    for entry in geo_output.get("geo_evidence", [])
                ],
                sentiment=sentiment,
                risk_score=risk_output["risk_score"],
                risk_reason=risk_output["risk_reason"],
                key_risk_factors=risk_output.get("key_risk_factors", []),
                information_gaps=risk_output.get("information_gaps", []),
                recommended_actions=risk_output.get("recommended_actions", []),
                uncertainty_notes=risk_output.get("uncertainty_notes", []),
                created_at=utc_now(),
            )
        except (ValidationError, ValueError) as exc:
            audit = audit.model_copy(update={"status": "failed", "error": f"输出校验失败：{exc}"})
            return LLMAnalysisRun(
                clean_item_id=item.id,
                executed=True,
                prompts=requests,
                audit=audit,
            )

        return LLMAnalysisRun(
            clean_item_id=item.id,
            executed=True,
            prompts=requests,
            result=result,
            audit=audit,
        )
