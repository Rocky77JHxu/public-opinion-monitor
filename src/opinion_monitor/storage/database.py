"""SQLite 持久化仓储。

Phase 4 使用标准库 sqlite3，避免在生产形态确定前引入额外服务依赖。
所有写入均显式开启事务，保持原始数据、清洗结果与处理决策可审计。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerRunResult,
    MediaCrawlerTask,
)
from opinion_monitor.models import (
    CleanItem,
    CommentRecord,
    DiscardedItem,
    LLMAnalysisResult,
    LLMAnalysisRun,
    ProcessingResult,
    RawItem,
    ScoringRunResult,
)
from opinion_monitor.models.enums import HotSearchPlatform, MediaCrawlerPlatform

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_crawler_tasks (
    task_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    crawl_type TEXT NOT NULL,
    target TEXT NOT NULL,
    max_items INTEGER NOT NULL,
    max_comments INTEGER NOT NULL,
    workspace_dir TEXT NOT NULL,
    task_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    content TEXT,
    url TEXT,
    author_id TEXT,
    author_name TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    rank INTEGER,
    hot_value INTEGER,
    engagement TEXT NOT NULL,
    keyword TEXT,
    keyword_level INTEGER,
    account_config_id TEXT,
    raw_payload TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_crawler_runs (
    task_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    return_code INTEGER,
    error TEXT,
    stopped_by_watchdog INTEGER NOT NULL,
    watchdog_content_count INTEGER,
    output_files TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, started_at)
);
CREATE INDEX IF NOT EXISTS idx_raw_platform_external
    ON raw_items(platform, external_id);
CREATE INDEX IF NOT EXISTS idx_raw_collected_at
    ON raw_items(collected_at);

CREATE TABLE IF NOT EXISTS clean_items (
    id TEXT PRIMARY KEY,
    raw_item_id TEXT NOT NULL REFERENCES raw_items(id),
    source_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    content TEXT,
    canonical_url TEXT,
    url_hash TEXT UNIQUE,
    author_id TEXT,
    author_name TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    engagement TEXT NOT NULL,
    keyword TEXT,
    keyword_level INTEGER,
    account_config_id TEXT,
    simhash TEXT NOT NULL,
    title_hash TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    preliminary_category TEXT NOT NULL,
    preliminary_category_confidence REAL NOT NULL,
    preliminary_category_reason TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    processing_run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clean_simhash
    ON clean_items(simhash);
CREATE INDEX IF NOT EXISTS idx_clean_category
    ON clean_items(preliminary_category);

CREATE TABLE IF NOT EXISTS clean_item_sources (
    clean_item_id TEXT NOT NULL REFERENCES clean_items(id) ON DELETE CASCADE,
    raw_item_id TEXT NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    PRIMARY KEY (clean_item_id, raw_item_id)
);

CREATE TABLE IF NOT EXISTS comment_records (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    note_external_id TEXT NOT NULL,
    external_comment_id TEXT NOT NULL,
    parent_comment_id TEXT,
    content TEXT NOT NULL,
    author_id TEXT,
    author_name TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    like_count INTEGER,
    raw_payload TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_note
    ON comment_records(task_id, note_external_id);

CREATE TABLE IF NOT EXISTS processing_runs (
    id TEXT PRIMARY KEY,
    reference_time TEXT NOT NULL,
    input_count INTEGER NOT NULL,
    accepted_count INTEGER NOT NULL,
    discarded_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_item_decisions (
    raw_item_id TEXT PRIMARY KEY REFERENCES raw_items(id) ON DELETE CASCADE,
    processing_run_id TEXT NOT NULL REFERENCES processing_runs(id) ON DELETE CASCADE,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'discarded')),
    reason TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_run
    ON processing_item_decisions(processing_run_id);

CREATE TABLE IF NOT EXISTS llm_analysis_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clean_item_id TEXT NOT NULL,
    status TEXT NOT NULL,
    model TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    error TEXT,
    request_digest TEXT NOT NULL,
    usage_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_audits_item
    ON llm_analysis_audits(clean_item_id, created_at);

CREATE TABLE IF NOT EXISTS llm_analysis_results (
    clean_item_id TEXT PRIMARY KEY REFERENCES clean_items(id) ON DELETE CASCADE,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_assessments (
    clean_item_id TEXT PRIMARY KEY REFERENCES clean_items(id) ON DELETE CASCADE,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS structured_output_events (
    event_id TEXT PRIMARY KEY,
    clean_item_id TEXT NOT NULL UNIQUE REFERENCES clean_items(id) ON DELETE CASCADE,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: str) -> Any:
    return json.loads(value)


class SqliteStorage:
    """SQLite 原始层与清洗层仓储。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialise(self) -> None:
        """初始化数据库并执行当前 Schema。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def save_media_crawler_task(self, task: MediaCrawlerTask) -> None:
        now = datetime.now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO media_crawler_tasks (
                    task_id, source_type, platform, crawl_type, target, max_items,
                    max_comments, workspace_dir, task_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    task_json = excluded.task_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(task.task_id),
                    task.source_type,
                    task.platform.value,
                    task.crawl_type,
                    task.target,
                    task.max_items,
                    task.max_comments,
                    task.workspace_dir,
                    task.model_dump_json(),
                    now,
                ),
            )

    def save_raw_items(self, items: Iterable[RawItem]) -> int:
        inserted = 0
        now = datetime.now().isoformat()
        with self._connect() as connection:
            for item in items:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO raw_items (
                        id, source_type, platform, external_id, title, content, url,
                        author_id, author_name, published_at, collected_at, rank,
                        hot_value, engagement, keyword, keyword_level,
                        account_config_id, raw_payload, collector_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item.id),
                        item.source_type,
                        item.platform.value,
                        item.external_id,
                        item.title,
                        item.content,
                        item.url,
                        item.author_id,
                        item.author_name,
                        _iso(item.published_at),
                        _iso(item.collected_at),
                        item.rank,
                        item.hot_value,
                        _dump(item.engagement),
                        item.keyword,
                        item.keyword_level,
                        item.account_config_id,
                        _dump(item.raw_payload),
                        item.collector_version,
                        now,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def save_media_crawler_run(
        self,
        result: MediaCrawlerRunResult,
        *,
        output_files: Iterable[str] = (),
    ) -> None:
        """保存单次 MediaCrawler 执行状态。"""

        now = datetime.now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO media_crawler_runs (
                    task_id, started_at, completed_at, status, return_code, error,
                    stopped_by_watchdog, watchdog_content_count, output_files, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(result.task_id),
                    result.started_at.isoformat(),
                    result.completed_at.isoformat(),
                    result.status.value,
                    result.return_code,
                    result.error,
                    int(result.stopped_by_watchdog),
                    result.watchdog_content_count,
                    _dump({"files": list(output_files)}),
                    now,
                ),
            )

    def save_comments(self, comments: Iterable[CommentRecord]) -> int:
        inserted = 0
        now = datetime.now().isoformat()
        with self._connect() as connection:
            for comment in comments:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO comment_records (
                        id, task_id, platform, note_external_id, external_comment_id,
                        parent_comment_id, content, author_id, author_name,
                        published_at, collected_at, like_count, raw_payload,
                        collector_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(comment.id),
                        str(comment.task_id),
                        comment.platform.value,
                        comment.note_external_id,
                        comment.external_comment_id,
                        comment.parent_comment_id,
                        comment.content,
                        comment.author_id,
                        comment.author_name,
                        _iso(comment.published_at),
                        _iso(comment.collected_at),
                        comment.like_count,
                        _dump(comment.raw_payload),
                        comment.collector_version,
                        now,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def _row_to_raw(self, row: sqlite3.Row) -> RawItem:
        return RawItem.model_validate(
            {
                "id": UUID(row["id"]),
                "source_type": row["source_type"],
                "platform": row["platform"],
                "external_id": row["external_id"],
                "title": row["title"],
                "content": row["content"],
                "url": row["url"],
                "author_id": row["author_id"],
                "author_name": row["author_name"],
                "published_at": datetime.fromisoformat(row["published_at"])
                if row["published_at"]
                else None,
                "collected_at": datetime.fromisoformat(row["collected_at"]),
                "rank": row["rank"],
                "hot_value": row["hot_value"],
                "engagement": _load_json(row["engagement"]),
                "keyword": row["keyword"],
                "keyword_level": row["keyword_level"],
                "account_config_id": row["account_config_id"],
                "raw_payload": _load_json(row["raw_payload"]),
                "collector_version": row["collector_version"],
            }
        )

    def list_pending_raw_items(self, *, limit: int | None = None) -> list[RawItem]:
        query = """
            SELECT r.* FROM raw_items r
            LEFT JOIN processing_item_decisions d ON d.raw_item_id = r.id
            WHERE d.raw_item_id IS NULL
            ORDER BY r.collected_at, r.id
        """
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_raw(row) for row in rows]

    def _row_to_clean(self, row: sqlite3.Row, source_ids: list[UUID]) -> CleanItem:
        platform: HotSearchPlatform | MediaCrawlerPlatform
        platform_value = row["platform"]
        try:
            platform = MediaCrawlerPlatform(platform_value)
        except ValueError:
            platform = HotSearchPlatform(platform_value)
        return CleanItem.model_validate(
            {
                "id": UUID(row["id"]),
                "raw_item_id": UUID(row["raw_item_id"]),
                "source_raw_item_ids": source_ids,
                "source_type": row["source_type"],
                "platform": platform,
                "external_id": row["external_id"],
                "title": row["title"],
                "content": row["content"],
                "canonical_url": row["canonical_url"],
                "url_hash": row["url_hash"],
                "author_id": row["author_id"],
                "author_name": row["author_name"],
                "published_at": datetime.fromisoformat(row["published_at"])
                if row["published_at"]
                else None,
                "collected_at": datetime.fromisoformat(row["collected_at"]),
                "engagement": _load_json(row["engagement"]),
                "keyword": row["keyword"],
                "keyword_level": row["keyword_level"],
                "account_config_id": row["account_config_id"],
                "simhash": row["simhash"],
                "title_hash": row["title_hash"],
                "content_hash": row["content_hash"],
                "preliminary_category": row["preliminary_category"],
                "preliminary_category_confidence": row["preliminary_category_confidence"],
                "preliminary_category_reason": row["preliminary_category_reason"],
                "collector_version": row["collector_version"],
            }
        )

    def list_clean_items(self, *, limit: int | None = None) -> list[CleanItem]:
        query = "SELECT * FROM clean_items ORDER BY collected_at, id"
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            result: list[CleanItem] = []
            for row in rows:
                source_rows = connection.execute(
                    """
                    SELECT raw_item_id FROM clean_item_sources
                    WHERE clean_item_id = ? ORDER BY rowid
                    """,
                    (row["id"],),
                ).fetchall()
                result.append(
                    self._row_to_clean(
                        row,
                        [UUID(source_row["raw_item_id"]) for source_row in source_rows],
                    )
                )
        return result

    def save_processing_result(self, result: ProcessingResult) -> None:
        now = datetime.now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO processing_runs (
                    id, reference_time, input_count, accepted_count,
                    discarded_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(result.processing_run_id),
                    result.reference_time.isoformat(),
                    result.input_count,
                    result.accepted_count,
                    result.discarded_count,
                    now,
                ),
            )

            for item in result.accepted_items:
                connection.execute(
                    """
                    INSERT INTO clean_items (
                        id, raw_item_id, source_type, platform, external_id, title,
                        content, canonical_url, url_hash, author_id, author_name,
                        published_at, collected_at, engagement, keyword, keyword_level,
                        account_config_id, simhash, title_hash, content_hash,
                        preliminary_category, preliminary_category_confidence,
                        preliminary_category_reason, collector_version,
                        processing_run_id, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        str(item.id),
                        str(item.raw_item_id),
                        item.source_type,
                        item.platform.value,
                        item.external_id,
                        item.title,
                        item.content,
                        item.canonical_url,
                        item.url_hash,
                        item.author_id,
                        item.author_name,
                        _iso(item.published_at),
                        _iso(item.collected_at),
                        _dump(item.engagement),
                        item.keyword,
                        item.keyword_level,
                        item.account_config_id,
                        item.simhash,
                        item.title_hash,
                        item.content_hash,
                        item.preliminary_category.value,
                        item.preliminary_category_confidence,
                        item.preliminary_category_reason,
                        item.collector_version,
                        str(result.processing_run_id),
                        now,
                    ),
                )
                for raw_id in item.source_raw_item_ids:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO clean_item_sources (clean_item_id, raw_item_id)
                        VALUES (?, ?)
                        """,
                        (str(item.id), str(raw_id)),
                    )

            for decision in [*result.accepted_items, *result.discarded_items]:
                if isinstance(decision, CleanItem):
                    raw_id = decision.raw_item_id
                    outcome = "accepted"
                    reason = "accepted"
                    details: dict[str, Any] = {"clean_item_id": str(decision.id)}
                elif isinstance(decision, DiscardedItem):
                    raw_id = decision.raw_item_id
                    outcome = "discarded"
                    reason = decision.reason
                    details = decision.details
                else:
                    raise TypeError(f"未知处理决策类型：{type(decision)}")
                connection.execute(
                    """
                    INSERT INTO processing_item_decisions (
                        raw_item_id, processing_run_id, outcome, reason, details, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(raw_id),
                        str(result.processing_run_id),
                        outcome,
                        reason,
                        _dump(details),
                        now,
                    ),
                )

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            tables = (
                "media_crawler_runs",
                "raw_items",
                "clean_items",
                "comment_records",
                "processing_runs",
                "processing_item_decisions",
                "llm_analysis_audits",
                "llm_analysis_results",
                "risk_assessments",
                "structured_output_events",
            )
            return {
                table: int(
                    connection.execute(  # noqa: S608 - table 名来自常量白名单
                        f"SELECT COUNT(*) FROM {table}"  # noqa: S608
                    ).fetchone()[0]
                )
                for table in tables
            }

    def get_clean_item(self, clean_item_id: UUID | str) -> CleanItem | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM clean_items WHERE id = ?",
                (str(clean_item_id),),
            ).fetchone()
            if row is None:
                return None
            source_rows = connection.execute(
                """
                SELECT raw_item_id FROM clean_item_sources
                WHERE clean_item_id = ? ORDER BY rowid
                """,
                (row["id"],),
            ).fetchall()
            return self._row_to_clean(
                row,
                [UUID(source_row["raw_item_id"]) for source_row in source_rows],
            )

    def list_clean_items_missing_analysis(self) -> list[CleanItem]:
        query = """
            SELECT c.* FROM clean_items c
            LEFT JOIN llm_analysis_results r ON r.clean_item_id = c.id
            WHERE r.clean_item_id IS NULL
            ORDER BY c.collected_at, c.id
        """
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
            result: list[CleanItem] = []
            for row in rows:
                source_rows = connection.execute(
                    """
                    SELECT raw_item_id FROM clean_item_sources
                    WHERE clean_item_id = ? ORDER BY rowid
                    """,
                    (row["id"],),
                ).fetchall()
                result.append(
                    self._row_to_clean(
                        row,
                        [UUID(source_row["raw_item_id"]) for source_row in source_rows],
                    )
                )
        return result

    def list_comments_for_clean_item(self, clean_item_id: UUID | str) -> list[CommentRecord]:
        query = """
            SELECT DISTINCT cm.*
            FROM comment_records cm
            JOIN clean_item_sources s ON s.clean_item_id = ?
            JOIN raw_items r ON r.id = s.raw_item_id
            WHERE cm.note_external_id = r.external_id
            ORDER BY cm.published_at, cm.id
        """
        with self._connect() as connection:
            rows = connection.execute(query, (str(clean_item_id),)).fetchall()

        comments: list[CommentRecord] = []
        for row in rows:
            comments.append(
                CommentRecord.model_validate(
                    {
                        "id": UUID(row["id"]),
                        "task_id": UUID(row["task_id"]),
                        "platform": row["platform"],
                        "note_external_id": row["note_external_id"],
                        "external_comment_id": row["external_comment_id"],
                        "parent_comment_id": row["parent_comment_id"],
                        "content": row["content"],
                        "author_id": row["author_id"],
                        "author_name": row["author_name"],
                        "published_at": datetime.fromisoformat(row["published_at"])
                        if row["published_at"]
                        else None,
                        "collected_at": datetime.fromisoformat(row["collected_at"]),
                        "like_count": row["like_count"],
                        "raw_payload": _load_json(row["raw_payload"]),
                        "collector_version": row["collector_version"],
                    }
                )
            )
        return comments

    def save_llm_analysis_run(self, run: LLMAnalysisRun) -> None:
        now = datetime.now().isoformat()
        with self._connect() as connection:
            if run.audit is not None:
                connection.execute(
                    """
                    INSERT INTO llm_analysis_audits (
                        clean_item_id, status, model, started_at, completed_at,
                        duration_ms, attempts, error, request_digest, usage_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(run.clean_item_id),
                        run.audit.status,
                        run.audit.model,
                        run.audit.started_at.isoformat(),
                        run.audit.completed_at.isoformat(),
                        run.audit.duration_ms,
                        run.audit.attempts,
                        run.audit.error,
                        run.audit.request_digest,
                        run.audit.usage.model_dump_json() if run.audit.usage else None,
                        now,
                    ),
                )
            if run.result is not None:
                connection.execute(
                    """
                    INSERT INTO llm_analysis_results (
                        clean_item_id, result_json, created_at
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(clean_item_id) DO UPDATE SET
                        result_json = excluded.result_json,
                        created_at = excluded.created_at
                    """,
                    (
                        str(run.result.clean_item_id),
                        run.result.model_dump_json(),
                        now,
                    ),
                )

    def get_llm_analysis_result(self, clean_item_id: UUID | str) -> LLMAnalysisResult | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM llm_analysis_results WHERE clean_item_id = ?",
                (str(clean_item_id),),
            ).fetchone()
        if row is None:
            return None
        return LLMAnalysisResult.model_validate_json(row["result_json"])

    def list_raw_items_for_clean_item(self, clean_item_id: UUID | str) -> list[RawItem]:
        query = """
            SELECT r.* FROM raw_items r
            JOIN clean_item_sources s ON s.raw_item_id = r.id
            WHERE s.clean_item_id = ?
            ORDER BY s.rowid
        """
        with self._connect() as connection:
            rows = connection.execute(query, (str(clean_item_id),)).fetchall()
        return [self._row_to_raw(row) for row in rows]

    def list_clean_items_ready_for_scoring(self) -> list[CleanItem]:
        query = """
            SELECT c.* FROM clean_items c
            JOIN llm_analysis_results a ON a.clean_item_id = c.id
            LEFT JOIN risk_assessments r ON r.clean_item_id = c.id
            WHERE r.clean_item_id IS NULL
            ORDER BY c.collected_at, c.id
        """
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
            result: list[CleanItem] = []
            for row in rows:
                source_rows = connection.execute(
                    """
                    SELECT raw_item_id FROM clean_item_sources
                    WHERE clean_item_id = ? ORDER BY rowid
                    """,
                    (row["id"],),
                ).fetchall()
                result.append(
                    self._row_to_clean(
                        row,
                        [UUID(source_row["raw_item_id"]) for source_row in source_rows],
                    )
                )
        return result

    def save_scoring_run(self, run: ScoringRunResult) -> None:
        now = datetime.now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO risk_assessments (
                    clean_item_id, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(clean_item_id) DO UPDATE SET
                    result_json = excluded.result_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(run.clean_item_id),
                    run.assessment.model_dump_json(),
                    run.assessment.created_at.isoformat(),
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO structured_output_events (
                    event_id, clean_item_id, event_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    clean_item_id = excluded.clean_item_id,
                    event_json = excluded.event_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(run.event.event_id),
                    str(run.clean_item_id),
                    run.event.model_dump_json(),
                    run.event.created_at.isoformat(),
                    now,
                ),
            )
