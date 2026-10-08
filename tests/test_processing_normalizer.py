from __future__ import annotations

from opinion_monitor.processing import (
    canonicalize_url,
    normalize_text,
    sha256_hex,
    simhash64,
    similarity_ratio,
)


def test_normalize_text_handles_unicode_and_punctuation() -> None:
    assert normalize_text("  Ｏｂｖｉｏｕｓ－Ｔｅｓｔ！  ") == "obvious test"
    assert normalize_text(None) == ""


def test_canonicalize_url_normalizes_host_path_query_and_ephemeral_params() -> None:
    result = canonicalize_url(
        "HTTPS://Example.COM:443/a/../b/?xsec_source=pc_search&b=2&xsec_token=abc&a=1#top"
    )

    assert result == "https://example.com/b?a=1&b=2"


def test_canonicalize_url_rejects_non_http() -> None:
    assert canonicalize_url("javascript:alert(1)") is None
    assert canonicalize_url(None) is None


def test_hashes_are_deterministic_and_similar_ratio_is_sensitive() -> None:
    left = "某地发生火灾 消防救援"
    right = "某地发生火灾 消防救援"

    assert simhash64(left) == simhash64(right)
    assert sha256_hex(left) == sha256_hex(right)
    assert similarity_ratio(left, right) == 1.0
    assert similarity_ratio(left, "完全无关内容") < 0.5
