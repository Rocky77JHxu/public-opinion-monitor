from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerRunResult,
    MediaCrawlerRunStatus,
    MediaCrawlerTask,
)
from opinion_monitor.config import load_config
from opinion_monitor.models import (
    CommentRecord,
    MediaCrawlerPlatform,
    RawItem,
    utc_now,
)
from opinion_monitor.processing import CleaningPipeline
from opinion_monitor.storage import SqliteStorage, ingest_and_process_media_crawler_task
from opinion_monitor.storage.service import process_pending_items


def make_task(workspace: Path) -> MediaCrawlerTask:
    task_id = uuid4()
    root = workspace / str(task_id)
    return MediaCrawlerTask(
        task_id=task_id,
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        crawl_type="search",
        target="火灾",
        keyword_level=1,
        max_items=2,
        max_comments=100,
        timeout_seconds=300,
        workspace_dir=root.as_posix(),
        input_file=(root / "task.json").as_posix(),
        output_file=(root / "output.jsonl").as_posix(),
    )


def make_raw(item_id: str, title: str, url: str) -> RawItem:
    return RawItem(
        id=uuid4(),
        source_type="keyword_search",
        platform=MediaCrawlerPlatform.XHS,
        external_id=f"xhs:{item_id}",
        title=title,
        url=url,
        published_at=datetime(2026, 10, 9, tzinfo=UTC),
        collected_at=utc_now(),
        keyword="火灾",
        keyword_level=1,
        raw_payload={"id": item_id},
        collector_version="test",
    )


def test_sqlite_storage_persists_raw_clean_and_decisions(tmp_path: Path) -> None:
    config = load_config(Path("config/config.example.yaml"), env={})
    storage = SqliteStorage(tmp_path / "state.db")
    storage.initialise()

    raw = make_raw("1", "火灾通报", "https://example.test/a")
    storage.save_raw_items([raw])
    storage.save_media_crawler_run(
        MediaCrawlerRunResult(
            task_id=raw.id,
            status=MediaCrawlerRunStatus.SUCCEEDED,
            started_at=utc_now(),
            completed_at=utc_now(),
            return_code=0,
        ),
        output_files=["output.jsonl"],
    )
    result = CleaningPipeline(config.processing, config.rules).run([raw])
    storage.save_processing_result(result)

    assert storage.stats() == {
        "media_crawler_runs": 1,
        "raw_items": 1,
        "clean_items": 1,
        "comment_records": 0,
        "processing_runs": 1,
        "processing_item_decisions": 1,
        "llm_analysis_audits": 0,
        "llm_analysis_results": 0,
    }
    assert storage.list_pending_raw_items() == []
    clean = storage.list_clean_items()
    assert clean[0].raw_item_id == raw.id
    assert clean[0].source_raw_item_ids == [raw.id]


def test_sqlite_storage_persists_comments(tmp_path: Path) -> None:
    task_id = uuid4()
    comment = CommentRecord(
        id=uuid4(),
        task_id=task_id,
        platform=MediaCrawlerPlatform.XHS,
        note_external_id="xhs:note-1",
        external_comment_id="xhs:comment-1",
        content="评论内容",
        collected_at=utc_now(),
        raw_payload={"test": True},
        collector_version="test",
    )
    storage = SqliteStorage(tmp_path / "state.db")
    storage.initialise()

    assert storage.save_comments([comment]) == 1
    assert storage.save_comments([comment]) == 0
    assert storage.stats()["comment_records"] == 1


def test_ingest_and_process_media_crawler_task(tmp_path: Path) -> None:
    config = load_config(Path("config/config.example.yaml"), env={})
    config.storage.sqlite.path = str(tmp_path / "state.db")
    task = make_task(tmp_path)
    jsonl_dir = Path(task.workspace_dir) / "xhs" / "jsonl"
    jsonl_dir.mkdir(parents=True)
    (jsonl_dir / "search_contents_2026-10-09.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "note_id": "note-1",
                        "title": "某地化工厂爆炸火灾",
                        "desc": "现场正在救援",
                        "note_url": "https://www.xiaohongshu.com/explore/note-1?xsec_token=a&xsec_source=pc_search",
                        "time": 1791470000000,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "note_id": "note-2",
                        "title": "某地化工厂爆炸火灾！",
                        "desc": "现场正在救援。",
                        "note_url": "https://www.xiaohongshu.com/explore/note-2?xsec_token=b&xsec_source=pc_search",
                        "time": 1791470000000,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (jsonl_dir / "search_comments_2026-10-09.jsonl").write_text(
        json.dumps(
            {
                "comment_id": "comment-1",
                "note_id": "note-1",
                "content": "希望没有人员伤亡",
                "create_time": 1791470000000,
                "creator_hash": "hash",
                "nickname": "测试",
                "like_count": "3",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = ingest_and_process_media_crawler_task(config, task)
    assert summary.raw_inserted == 2
    assert summary.comments_inserted == 1
    assert summary.processing.input_count == 2
    assert summary.processing.accepted_count == 1
    assert summary.processing.discarded_count == 1
    assert summary.storage_stats == {
        "media_crawler_runs": 0,
        "raw_items": 2,
        "clean_items": 1,
        "comment_records": 1,
        "processing_runs": 1,
        "processing_item_decisions": 2,
        "llm_analysis_audits": 0,
        "llm_analysis_results": 0,
    }
    assert (
        process_pending_items(config, storage=SqliteStorage(config.storage.sqlite.path)).input_count
        == 0
    )
