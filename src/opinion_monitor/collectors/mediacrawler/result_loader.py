"""MediaCrawler JSONL 结果加载与平台字段归一化。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from pydantic import ValidationError

from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerCommentLoadResult,
    MediaCrawlerLoadContext,
    MediaCrawlerLoadError,
    MediaCrawlerLoadResult,
)
from opinion_monitor.models import CommentRecord, MediaCrawlerPlatform, RawItem

COLLECTOR_VERSION = "mediacrawler-jsonl-v1"
_ITEM_NAMESPACE = UUID("02e57f8f-99c4-4a30-b678-514df842a70b")


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
        if normalized.isdigit():
            return int(normalized)
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        return datetime.fromtimestamp(seconds, tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_datetime(int(text))
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _external_id(record: dict[str, Any], platform: MediaCrawlerPlatform) -> str:
    value = _first(
        record,
        (
            "note_id",
            "note_id_str",
            "aweme_id",
            "video_id",
            "content_id",
            "post_id",
            "id",
        ),
    )
    if value is not None:
        return f"{platform.value}:{value}"
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{platform.value}:hash:{digest}"


def _title(record: dict[str, Any]) -> str:
    title = _first(record, ("title", "display_title", "name", "subject"))
    if title is not None:
        return str(title).strip()
    content = _first(record, ("desc", "description", "content", "text", "excerpt"))
    if content is not None:
        return str(content).strip()[:120]
    return ""


def _map_record(
    record: dict[str, Any],
    context: MediaCrawlerLoadContext,
    line_number: int,
) -> RawItem:
    title = _title(record)
    if not title:
        raise ValueError("记录缺少标题或可作为标题的正文")

    external_id = _external_id(record, context.platform)
    url_value = _first(record, ("note_url", "url", "content_url", "link", "uri"))
    url = str(url_value) if isinstance(url_value, str) and url_value.startswith("http") else None
    published_at = _parse_datetime(
        _first(
            record,
            (
                "publish_time",
                "published_at",
                "publish_date",
                "create_time",
                "created_at",
                "time",
            ),
        )
    )
    author_id = _first(record, ("user_id", "user_id_str", "author_id", "user_id"))
    author_name = _first(record, ("nickname", "author_name", "username", "user_name"))
    content = _first(record, ("desc", "description", "content", "text", "excerpt"))

    engagement = {
        key: count
        for key, count in {
            "like": _as_int(_first(record, ("liked_count", "like_count", "digg_count"))),
            "comment": _as_int(_first(record, ("comment_count", "comments_count"))),
            "share": _as_int(_first(record, ("share_count", "forward_count", "reposts_count"))),
            "read": _as_int(_first(record, ("read_count", "view_count", "play_count"))),
            "collect": _as_int(_first(record, ("collected_count", "collect_count"))),
        }.items()
        if count is not None
    }

    item_id = uuid5(
        _ITEM_NAMESPACE,
        f"{context.task_id}:{line_number}:{external_id}:{title}",
    )
    return RawItem(
        id=item_id,
        source_type=context.source_type,
        platform=context.platform,
        external_id=external_id,
        title=title,
        content=str(content) if content is not None else None,
        url=url,
        author_id=str(author_id) if author_id is not None else None,
        author_name=str(author_name) if author_name is not None else None,
        published_at=published_at,
        collected_at=datetime.now(UTC),
        engagement=engagement,
        keyword=context.keyword,
        keyword_level=context.keyword_level,
        account_config_id=context.account_config_id,
        raw_payload={"source": "mediacrawler_jsonl", "original": record},
        collector_version=COLLECTOR_VERSION,
    )


def load_jsonl(
    path: str | Path,
    context: MediaCrawlerLoadContext,
    *,
    limit: int | None = None,
) -> MediaCrawlerLoadResult:
    """逐行加载 JSONL；单行失败不会丢弃整个文件。"""

    file_path = Path(path)
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return MediaCrawlerLoadResult(
            path=str(file_path),
            total_lines=0,
            loaded_count=0,
            failed_count=0,
            items=[],
            errors=[MediaCrawlerLoadError(line_number=1, reason=f"无法读取文件：{exc}")],
        )

    items: list[RawItem] = []
    errors: list[MediaCrawlerLoadError] = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if limit is not None and len(items) >= limit:
            break
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise TypeError("JSONL 行根节点必须是对象")
            items.append(_map_record(record, context, index))
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            errors.append(MediaCrawlerLoadError(line_number=index, reason=str(exc)))

    return MediaCrawlerLoadResult(
        path=str(file_path),
        total_lines=len(lines),
        loaded_count=len(items),
        failed_count=len(errors),
        items=items,
        errors=errors,
    )


def discover_jsonl_files(directory: str | Path) -> list[Path]:
    """发现任务目录内 MediaCrawler 生成的 JSONL 文件。"""

    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.rglob("*.jsonl") if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.as_posix()),
        reverse=True,
    )


def _map_comment_record(
    record: dict[str, Any],
    context: MediaCrawlerLoadContext,
    line_number: int,
) -> CommentRecord:
    comment_id = _first(record, ("comment_id", "id", "commentId"))
    note_id = _first(record, ("note_id", "noteId", "source_note_id"))
    content = _first(record, ("content", "text", "comment_content"))
    if not comment_id or not note_id or not content:
        raise ValueError("评论缺少 comment_id、note_id 或 content")
    comment_id = str(comment_id)
    note_id = str(note_id)
    parent = _first(record, ("parent_comment_id", "parentId"))
    published_at = _parse_datetime(_first(record, ("create_time", "created_at", "create_at")))
    like_count = _as_int(_first(record, ("like_count", "liked_count", "digg_count")))
    return CommentRecord(
        id=uuid5(
            _ITEM_NAMESPACE,
            f"comment:{context.task_id}:{line_number}:{note_id}:{comment_id}",
        ),
        task_id=context.task_id,
        platform=context.platform,
        note_external_id=f"{context.platform.value}:{note_id}",
        external_comment_id=f"{context.platform.value}:{comment_id}",
        parent_comment_id=str(parent) if parent else None,
        content=str(content),
        author_id=(
            str(author)
            if (author := _first(record, ("creator_hash", "user_id", "author_id"))) is not None
            else None
        ),
        author_name=(
            str(author_name)
            if (author_name := _first(record, ("nickname", "author_name"))) is not None
            else None
        ),
        published_at=published_at,
        collected_at=datetime.now(UTC),
        like_count=like_count,
        raw_payload={"source": "mediacrawler_jsonl", "original": record},
        collector_version=COLLECTOR_VERSION,
    )


def load_comment_jsonl(
    path: str | Path,
    context: MediaCrawlerLoadContext,
    *,
    limit: int | None = None,
) -> MediaCrawlerCommentLoadResult:
    """加载评论 JSONL；单行失败不丢弃整个文件。"""

    file_path = Path(path)
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return MediaCrawlerCommentLoadResult(
            path=str(file_path),
            total_lines=0,
            loaded_count=0,
            failed_count=0,
            comments=[],
            errors=[MediaCrawlerLoadError(line_number=1, reason=f"无法读取文件：{exc}")],
        )

    comments: list[CommentRecord] = []
    errors: list[MediaCrawlerLoadError] = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if limit is not None and len(comments) >= limit:
            break
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise TypeError("评论 JSONL 行根节点必须是对象")
            comments.append(_map_comment_record(record, context, index))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(MediaCrawlerLoadError(line_number=index, reason=str(exc)))

    return MediaCrawlerCommentLoadResult(
        path=str(file_path),
        total_lines=len(lines),
        loaded_count=len(comments),
        failed_count=len(errors),
        comments=comments,
        errors=errors,
    )
