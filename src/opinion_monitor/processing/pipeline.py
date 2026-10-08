"""日期过滤、规则分类、URL 去重与内容相似度去重流水线。"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict

from opinion_monitor.config.schema import ProcessingConfig, RulesConfig
from opinion_monitor.models import AlertCategory
from opinion_monitor.models.clean import CleanItem, DiscardedItem
from opinion_monitor.models.processing import ProcessingResult
from opinion_monitor.models.raw import RawItem, utc_now
from opinion_monitor.processing.normalizer import (
    canonicalize_url,
    normalize_text,
    sha256_hex,
    simhash64,
    similarity_ratio,
)

_CLEAN_NAMESPACE = UUID("e6dd4bc1-961f-4b73-a50e-f00a95d45d3f")


class ProcessingRunResult(BaseModel):
    """兼容旧命名的清洗结果别名模型。"""

    model_config = ConfigDict(extra="forbid")

    result: ProcessingResult


class CleaningPipeline:
    """执行 Phase 4 清洗与去重。"""

    def __init__(self, processing: ProcessingConfig, rules: RulesConfig) -> None:
        self._processing = processing
        self._rules = rules

    def _classify(self, item: RawItem) -> tuple[AlertCategory, float, str]:
        searchable = normalize_text(
            " ".join(
                part
                for part in (
                    item.title,
                    item.content,
                    item.keyword,
                    item.account_config_id,
                    item.author_name,
                )
                if part
            )
        )
        matched: list[tuple[AlertCategory, float, list[str]]] = []
        for category, rule in self._rules.categories.items():
            keywords = [
                keyword for keyword in rule.keywords if normalize_text(keyword) in searchable
            ]
            if keywords:
                matched.append((category, rule.weight, keywords))
        if not matched:
            return AlertCategory.OTHER, 0.30, "未命中规则关键词，归入其他"
        matched.sort(key=lambda entry: entry[1], reverse=True)
        category, _, keywords = matched[0]
        confidence = min(0.95, 0.60 + 0.10 * (len(keywords) - 1))
        return category, confidence, f"命中关键词：{'、'.join(keywords[:5])}"

    def _is_expired(self, item: RawItem, reference_time: datetime) -> bool:
        if item.published_at is None:
            return self._processing.date_filter.missing_published_at_policy == "drop"
        age = reference_time - item.published_at
        return age > timedelta(hours=self._processing.date_filter.max_age_hours)

    def _make_clean_item(self, item: RawItem) -> CleanItem:
        category, confidence, reason = self._classify(item)
        canonical_url = canonicalize_url(
            item.url,
            strip_query_params=self._processing.deduplication.url.strip_query_params,
        )
        url_hash = sha256_hex(canonical_url) if canonical_url else None
        combined = "\n".join(part for part in (item.title, item.content) if part)
        return CleanItem(
            id=uuid5(_CLEAN_NAMESPACE, f"clean:{item.id}"),
            raw_item_id=item.id,
            source_raw_item_ids=[item.id],
            source_type=item.source_type,
            platform=item.platform,
            external_id=item.external_id,
            title=" ".join(item.title.split()),
            content=" ".join(item.content.split()) if item.content else None,
            canonical_url=canonical_url,
            url_hash=url_hash,
            author_id=item.author_id,
            author_name=item.author_name,
            published_at=item.published_at,
            collected_at=item.collected_at,
            engagement=item.engagement,
            keyword=item.keyword,
            keyword_level=item.keyword_level,
            account_config_id=item.account_config_id,
            simhash=simhash64(combined),
            title_hash=sha256_hex(normalize_text(item.title)),
            content_hash=sha256_hex(normalize_text(combined)),
            preliminary_category=category,
            preliminary_category_confidence=confidence,
            preliminary_category_reason=reason,
            collector_version=item.collector_version,
        )

    @staticmethod
    def _same_identifier(left: CleanItem, right: CleanItem) -> bool:
        if left.url_hash and left.url_hash == right.url_hash:
            return True
        return bool(
            left.platform == right.platform
            and left.external_id
            and left.external_id == right.external_id
        )

    @staticmethod
    def _simhash_ratio(left: CleanItem, right: CleanItem) -> float:
        left_value = int(left.simhash, base=16)
        right_value = int(right.simhash, base=16)
        distance = (left_value ^ right_value).bit_count()
        return 1.0 - distance / 64.0

    def _similar(self, left: CleanItem, right: CleanItem) -> bool:
        if (
            not self._processing.deduplication.content.cross_platform_merge
            and left.platform != right.platform
        ):
            return False
        if self._simhash_ratio(left, right) < 0.65:
            return False
        title_threshold = self._processing.deduplication.content.title_similarity_threshold
        if similarity_ratio(left.title, right.title) >= title_threshold:
            return True
        left_text = "\n".join(part for part in (left.title, left.content) if part)
        right_text = "\n".join(part for part in (right.title, right.content) if part)
        content_threshold = self._processing.deduplication.content.content_similarity_threshold
        return similarity_ratio(left_text, right_text) >= content_threshold

    def run(
        self,
        items: list[RawItem],
        *,
        reference_time: datetime | None = None,
        existing_items: list[CleanItem] | None = None,
    ) -> ProcessingResult:
        reference = reference_time or utc_now()
        anchors = list(existing_items or [])
        accepted: list[CleanItem] = []
        discarded: list[DiscardedItem] = []

        ordered = sorted(
            items,
            key=lambda item: (item.published_at or item.collected_at, item.collected_at),
        )
        for item in ordered:
            if self._is_expired(item, reference):
                reason = "missing_published_at" if item.published_at is None else "expired"
                discarded.append(
                    DiscardedItem(
                        raw_item_id=item.id,
                        reason=reason,
                        details={
                            "published_at": (
                                item.published_at.isoformat() if item.published_at else None
                            ),
                            "max_age_hours": self._processing.date_filter.max_age_hours,
                        },
                    )
                )
                continue

            candidate = self._make_clean_item(item)
            duplicate_of: CleanItem | None = None
            for existing in [*anchors, *accepted]:
                if self._same_identifier(candidate, existing) or (
                    self._processing.deduplication.content.enabled
                    and self._similar(candidate, existing)
                ):
                    duplicate_of = existing
                    break

            if duplicate_of is not None:
                duplicate_of.source_raw_item_ids.append(item.id)
                discarded.append(
                    DiscardedItem(
                        raw_item_id=item.id,
                        reason="duplicate",
                        details={
                            "duplicate_of_clean_id": str(duplicate_of.id),
                            "canonical_url": candidate.canonical_url,
                            "simhash": candidate.simhash,
                        },
                    )
                )
                continue
            accepted.append(candidate)

        return ProcessingResult(
            processing_run_id=uuid4(),
            reference_time=reference,
            input_count=len(items),
            accepted_count=len(accepted),
            discarded_count=len(discarded),
            accepted_items=accepted,
            discarded_items=discarded,
        )
