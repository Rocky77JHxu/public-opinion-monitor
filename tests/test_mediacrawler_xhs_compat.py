from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from opinion_monitor.collectors.mediacrawler.xhs_compat import (
    extract_initial_state,
    patch_xhs_extractor,
)


def page(state: str) -> str:
    return (
        "<html><head><script>window.__SSR__=true</script>"
        f"<script>window.__INITIAL_STATE__={state}</script>"
        '<script src="https://example.test/a.js"></script>'
        '<script src="https://example.test/b.js"></script></head></html>'
    )


def test_extracts_javascript_initial_state_literals() -> None:
    state = extract_initial_state(
        page(
            '{"user":{"userPageData":{"nickname":"tester","missing":undefined}},'
            '"layout":{"selectedIds":new Set([]),"excludedIds":new Set([])}}'
        )
    )

    assert state == {
        "user": {"userPageData": {"nickname": "tester", "missing": None}},
        "layout": {"selectedIds": [], "excludedIds": []},
    }


def test_invalid_initial_state_returns_none() -> None:
    assert extract_initial_state(page('{"user":')) is None


def test_patches_creator_and_note_extractors() -> None:
    class Extractor:
        pass

    def decamelize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): decamelize(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [decamelize(item) for item in value]
        return value

    module = SimpleNamespace(
        XiaoHongShuExtractor=Extractor,
        humps=SimpleNamespace(decamelize=decamelize),
    )
    patch_xhs_extractor(module)

    extractor: Any = Extractor()
    creator = extractor.extract_creator_info_from_html(
        page('{"user":{"userPageData":{"nickname":"tester"}}}')
    )
    note = extractor.extract_note_detail_from_html(
        "note-1",
        page('{"note":{"noteDetailMap":{"note-1":{"note":{"noteId":"note-1"}}}}}'),
    )

    assert creator == {"nickname": "tester"}
    assert note == {"note_id": "note-1"}
