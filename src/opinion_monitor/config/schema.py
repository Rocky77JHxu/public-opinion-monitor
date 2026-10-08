"""Pydantic 配置模型。

示例配置中的机器值保持英文；面向使用者展示的标签与说明使用中文。
所有模型默认禁止额外字段，尽早暴露拼写错误和过期配置项。
"""

from __future__ import annotations

import re
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opinion_monitor.models.enums import (
    AlertCategory,
    AlertLevel,
    HotSearchPlatform,
    MediaCrawlerPlatform,
)

PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Score = Annotated[float, Field(ge=0, le=100)]
Probability = Annotated[float, Field(ge=0, le=1)]
EnvVarName = Annotated[str, Field(pattern=r"^[A-Z_][A-Z0-9_]*$")]


class StrictModel(BaseModel):
    """禁止未知字段的模型基类。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["console", "json"]


class AppConfig(StrictModel):
    name: str = Field(min_length=1)
    environment: Literal["development", "testing", "staging", "production"]
    timezone: str
    log_level: LogLevel
    log_format: LogFormat = "console"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"无效 IANA 时区：{value}"
            raise ValueError(msg) from exc
        return value


class SQLiteStorageConfig(StrictModel):
    path: str = Field(min_length=1)


class PostgresStorageConfig(StrictModel):
    dsn_env: EnvVarName


class StorageConfig(StrictModel):
    backend: Literal["sqlite", "postgres"]
    sqlite: SQLiteStorageConfig
    postgres: PostgresStorageConfig
    raw_retention_days: PositiveInt
    processed_retention_days: PositiveInt

    @model_validator(mode="after")
    def check_retention(self) -> StorageConfig:
        if self.processed_retention_days < self.raw_retention_days:
            msg = "processed_retention_days 不应小于 raw_retention_days"
            raise ValueError(msg)
        return self


class SchedulerConfig(StrictModel):
    enabled: bool
    max_concurrent_tasks: PositiveInt
    task_timeout_seconds: PositiveInt
    missed_task_policy: Literal["skip", "run_once"]


class JitterConfig(StrictModel):
    interval_seconds: PositiveInt
    jitter_min_seconds: NonNegativeInt
    jitter_max_seconds: NonNegativeInt

    @model_validator(mode="after")
    def check_window(self) -> JitterConfig:
        if self.jitter_max_seconds < self.jitter_min_seconds:
            msg = "jitter_max_seconds 不能小于 jitter_min_seconds"
            raise ValueError(msg)
        if self.jitter_min_seconds >= self.interval_seconds:
            msg = "jitter_min_seconds 必须小于 interval_seconds"
            raise ValueError(msg)
        return self


class HotSearchDefaults(JitterConfig):
    enabled: bool
    timeout_seconds: PositiveFloat
    max_retries: NonNegativeInt
    retry_backoff_seconds: NonNegativeFloat = 0.5


class HotSearchPlatformConfig(StrictModel):
    enabled: bool
    url: str = Field(pattern=r"^https?://")
    parser: Literal["html", "json"]
    weight: Score
    headers: dict[str, str] = Field(default_factory=dict)
    interval_seconds: PositiveInt | None = None
    jitter_min_seconds: NonNegativeInt | None = None
    jitter_max_seconds: NonNegativeInt | None = None

    @model_validator(mode="after")
    def check_override(self) -> HotSearchPlatformConfig:
        overrides = (
            self.interval_seconds,
            self.jitter_min_seconds,
            self.jitter_max_seconds,
        )
        if any(value is not None for value in overrides) and any(
            value is None for value in overrides
        ):
            msg = (
                "平台自定义调度必须同时提供 interval_seconds、"
                "jitter_min_seconds 和 jitter_max_seconds"
            )
            raise ValueError(msg)
        if (
            self.interval_seconds is not None
            and self.jitter_min_seconds is not None
            and self.jitter_min_seconds >= self.interval_seconds
        ):
            msg = "平台 jitter_min_seconds 必须小于 interval_seconds"
            raise ValueError(msg)
        return self


class HotSearchConfig(StrictModel):
    defaults: HotSearchDefaults
    platforms: dict[HotSearchPlatform, HotSearchPlatformConfig] = Field(min_length=1)


class KeywordSearchDefaults(JitterConfig):
    enabled: bool
    max_items_per_keyword: PositiveInt
    enable_comments: bool
    max_comments_per_item: NonNegativeInt


class KeywordLevelConfig(JitterConfig):
    enabled: bool
    weight: Score
    platforms: list[MediaCrawlerPlatform] = Field(min_length=1)
    keywords: list[str]

    @field_validator("platforms")
    @classmethod
    def check_platforms(cls, value: list[MediaCrawlerPlatform]) -> list[MediaCrawlerPlatform]:
        if len(set(value)) != len(value):
            msg = "platforms 中存在重复平台"
            raise ValueError(msg)
        return value

    @field_validator("keywords")
    @classmethod
    def check_keywords(cls, value: list[str]) -> list[str]:
        if any(not keyword.strip() for keyword in value):
            msg = "keywords 不能包含空字符串"
            raise ValueError(msg)
        if len(set(value)) != len(value):
            msg = "keywords 中存在重复关键词"
            raise ValueError(msg)
        return value


class KeywordSearchConfig(StrictModel):
    defaults: KeywordSearchDefaults
    levels: dict[str, KeywordLevelConfig]


class AccountSearchDefaults(JitterConfig):
    enabled: bool
    max_items_per_account: PositiveInt
    enable_comments: bool
    max_comments_per_item: NonNegativeInt


class AccountConfig(JitterConfig):
    enabled: bool
    name: str = Field(min_length=1)
    platform: MediaCrawlerPlatform
    external_id: str = Field(min_length=1)
    weight: Score
    crawl_type: Literal["creator", "detail"] = "creator"
    max_items: PositiveInt


class AccountSearchConfig(StrictModel):
    defaults: AccountSearchDefaults
    accounts: dict[str, AccountConfig]


class MediaCrawlerConfig(StrictModel):
    root: str = Field(min_length=1)
    save_option: Literal["json", "jsonl", "csv", "db"]
    save_path: str = Field(min_length=1)
    login_type: Literal["qrcode", "phone", "cookie"]
    enable_cdp_mode: bool
    enable_cdp_connect_existing: bool
    cdp_debug_port: Annotated[int, Field(ge=1, le=65535)]
    enable_get_comments: bool
    max_comments_per_note: NonNegativeInt
    enable_sub_comments: bool
    max_concurrency: PositiveInt
    max_sleep_seconds: NonNegativeInt
    allow_execution: bool = False
    pinned_ref: str = ""
    headless: bool = False
    save_login_state: bool = True
    task_timeout_seconds: PositiveInt = 1800
    command_name: str = "uv"
    entrypoint: str = "main.py"
    task_dir: str = "data/media_crawler/tasks"
    watchdog_enabled: bool = True
    watchdog_poll_seconds: PositiveFloat = 0.25

    @model_validator(mode="after")
    def check_execution_safety(self) -> MediaCrawlerConfig:
        if self.allow_execution and not self.pinned_ref:
            msg = "mediacrawler.pinned_ref 不能为空才能允许执行"
            raise ValueError(msg)
        if self.allow_execution and not re.fullmatch(r"[0-9a-f]{40}", self.pinned_ref):
            msg = "mediacrawler.pinned_ref 必须是 40 位小写 Git commit SHA"
            raise ValueError(msg)
        return self


class DateFilterConfig(StrictModel):
    max_age_hours: PositiveInt
    missing_published_at_policy: Literal["drop", "keep_for_manual_review"]


class URLDeduplicationConfig(StrictModel):
    enabled: bool
    strip_query_params: list[str]


class ContentDeduplicationConfig(StrictModel):
    enabled: bool
    algorithm: Literal["simhash", "minhash"]
    title_similarity_threshold: Probability
    content_similarity_threshold: Probability
    cross_platform_merge: bool


class DeduplicationConfig(StrictModel):
    url: URLDeduplicationConfig
    content: ContentDeduplicationConfig


class HotSearchExpansionConfig(StrictModel):
    enabled: bool
    max_items_per_hotword: PositiveInt
    platforms: list[MediaCrawlerPlatform] = Field(min_length=1)

    @field_validator("platforms")
    @classmethod
    def check_platforms(cls, value: list[MediaCrawlerPlatform]) -> list[MediaCrawlerPlatform]:
        if len(set(value)) != len(value):
            msg = "hotsearch_expansion.platforms 中存在重复平台"
            raise ValueError(msg)
        return value


class ProcessingConfig(StrictModel):
    date_filter: DateFilterConfig
    deduplication: DeduplicationConfig
    hotsearch_expansion: HotSearchExpansionConfig


class RuleCategoryConfig(StrictModel):
    label: str = Field(min_length=1)
    weight: Score
    keywords: list[str]

    @field_validator("keywords")
    @classmethod
    def check_keywords(cls, value: list[str]) -> list[str]:
        if any(not keyword.strip() for keyword in value):
            msg = "规则关键词不能为空字符串"
            raise ValueError(msg)
        if len(set(value)) != len(value):
            msg = "规则关键词不能重复"
            raise ValueError(msg)
        return value


class RulesConfig(StrictModel):
    categories: dict[AlertCategory, RuleCategoryConfig]

    @model_validator(mode="after")
    def check_categories(self) -> RulesConfig:
        required = set(AlertCategory)
        if set(self.categories) != required:
            msg = f"rules.categories 必须完整包含 {sorted(required)}"
            raise ValueError(msg)
        return self


class SourceWeightsConfig(StrictModel):
    official_authority: Score
    mainstream_media: Score
    local_media: Score
    verified_institution_account: Score
    verified_personal_account: Score
    ordinary_social_media: Score
    anonymous_or_unverified: Score
    default: Score


class PlatformHeatConfig(StrictModel):
    top_rank_weight: Score
    hot_value_field: str = Field(min_length=1)


class ScoringNormalizationConfig(StrictModel):
    min: Score
    max: Score

    @model_validator(mode="after")
    def check_range(self) -> ScoringNormalizationConfig:
        if self.min >= self.max:
            msg = "scoring.normalization.min 必须小于 max"
            raise ValueError(msg)
        return self


class ScoringWeightsConfig(StrictModel):
    keyword_category: Probability
    source: Probability
    heat: Probability
    llm_category: Probability
    sentiment: Probability
    llm_risk: Probability

    @model_validator(mode="after")
    def check_sum(self) -> ScoringWeightsConfig:
        total = sum(
            (
                self.keyword_category,
                self.source,
                self.heat,
                self.llm_category,
                self.sentiment,
                self.llm_risk,
            ),
            start=0.0,
        )
        if abs(total - 1.0) > 1e-9:
            msg = f"scoring.weights 权重总和必须为 1，当前为 {total:.8f}"
            raise ValueError(msg)
        return self


class ScoringConfig(StrictModel):
    normalization: ScoringNormalizationConfig
    weights: ScoringWeightsConfig
    manual_review_confidence: Probability = 0.6


class AlertLevelConfig(StrictModel):
    label: str = Field(min_length=1)
    min_score: Score


class AlertLevelsConfig(StrictModel):
    red: AlertLevelConfig
    orange: AlertLevelConfig
    blue: AlertLevelConfig
    archive: AlertLevelConfig

    @model_validator(mode="after")
    def check_thresholds(self) -> AlertLevelsConfig:
        if (
            not self.archive.min_score
            < self.blue.min_score
            < self.orange.min_score
            < self.red.min_score
        ):
            msg = "预警阈值必须满足 archive < blue < orange < red"
            raise ValueError(msg)
        return self


class SentimentConfig(StrictModel):
    model: Literal["openai_compatible", "local"]
    categories: list[str] = Field(min_length=1)
    weights: dict[str, Score]

    @field_validator("categories")
    @classmethod
    def check_categories(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            msg = "sentiment.categories 不能重复"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def check_weights(self) -> SentimentConfig:
        if set(self.categories) != set(self.weights):
            missing = sorted(set(self.categories) - set(self.weights))
            extra = sorted(set(self.weights) - set(self.categories))
            msg = f"sentiment.weights 必须与 categories 完全一致；缺失={missing}，额外={extra}"
            raise ValueError(msg)
        return self


class LLMConfig(StrictModel):
    provider: Literal["openai_compatible"]
    base_url_env: EnvVarName
    api_key_env: EnvVarName
    model_env: EnvVarName
    temperature: Annotated[float, Field(ge=0, le=2)]
    max_output_tokens: PositiveInt
    timeout_seconds: PositiveFloat
    max_retries: NonNegativeInt
    enable_structured_output: bool
    prompt_dir: str = Field(min_length=1)
    max_input_comments: PositiveInt = 100


class DingTalkLevelConfig(StrictModel):
    enabled: bool
    immediate: bool = False


class DingTalkOutputConfig(StrictModel):
    enabled: bool
    webhook_url_env: EnvVarName
    timeout_seconds: PositiveFloat
    max_retries: NonNegativeInt
    retry_backoff_seconds: NonNegativeInt
    send_mode: Literal["automation_json", "markdown"]
    dry_run: bool
    levels: dict[AlertLevel, DingTalkLevelConfig]

    @model_validator(mode="after")
    def check_levels(self) -> DingTalkOutputConfig:
        required = set(AlertLevel)
        if set(self.levels) != required:
            msg = f"output.dingtalk.levels 必须完整包含 {sorted(required)}"
            raise ValueError(msg)
        return self


class OutputConfig(StrictModel):
    dingtalk: DingTalkOutputConfig


class SecurityConfig(StrictModel):
    allow_private_network: bool
    validate_ssl: bool
    redact_phone_numbers: bool
    redact_id_numbers: bool
    mask_user_ids_in_output: bool


class RootConfig(StrictModel):
    app: AppConfig
    storage: StorageConfig
    scheduler: SchedulerConfig
    hotsearch: HotSearchConfig
    keyword_search: KeywordSearchConfig
    account_search: AccountSearchConfig
    mediacrawler: MediaCrawlerConfig
    processing: ProcessingConfig
    rules: RulesConfig
    source_weights: SourceWeightsConfig
    platform_heat: dict[HotSearchPlatform, PlatformHeatConfig]
    scoring: ScoringConfig
    alert_levels: AlertLevelsConfig
    sentiment: SentimentConfig
    llm: LLMConfig
    output: OutputConfig
    security: SecurityConfig
