"""URL、文本与内容指纹规范化工具。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

_ALWAYS_STRIP_QUERY_PARAMS = {
    "xsec_token",
    "xsec_source",
    "share_token",
    "spm",
    "from",
}
_UNICODE_PUNCTUATION = re.compile(r"[\W_]+", re.UNICODE)


def normalize_text(value: str | None) -> str:
    """统一 Unicode、大小写与分隔符，用于指纹与相似度计算。"""

    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _UNICODE_PUNCTUATION.sub(" ", normalized).strip()


def _normalize_path(path: str) -> str:
    segments: list[str] = []
    for segment in path.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    return "/" + "/".join(segments)


def canonicalize_url(
    url: str | None,
    *,
    strip_query_params: Iterable[str] = (),
) -> str | None:
    """规范化 HTTP(S) URL；无效或空 URL 返回 None。"""

    if not url:
        return None
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    port: int | None = parsed.port
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        port = None
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"

    path = _normalize_path(parsed.path)
    stripped = {name.lower() for name in strip_query_params}
    stripped.update(_ALWAYS_STRIP_QUERY_PARAMS)
    pairs: list[tuple[str, str]] = []
    for pair in parsed.query.split("&"):
        if not pair:
            continue
        key, separator, value = pair.partition("=")
        if key.lower() in stripped:
            continue
        pairs.append((key, value if separator else ""))
    query = "&".join(f"{key}={value}" for key, value in sorted(pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def sha256_hex(value: str) -> str:
    """计算 UTF-8 字符串 SHA-256。"""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _token_hash(token: str) -> int:
    return int.from_bytes(
        hashlib.sha256(token.encode("utf-8")).digest()[:8],
        "big",
    )


def _features(value: str) -> list[str]:
    normalized = normalize_text(value)
    if not normalized:
        return []
    tokens = normalized.split()
    character_grams = [normalized[i : i + 3] for i in range(max(1, len(normalized) - 2))]
    return [*tokens, *character_grams]


def simhash64(value: str) -> str:
    """计算 Unicode 3-gram + token 的 64 位 SimHash。"""

    dimensions = [0] * 64
    for feature in _features(value):
        hashed = _token_hash(feature)
        weight = 1
        for bit in range(64):
            if hashed & (1 << bit):
                dimensions[bit] += weight
            else:
                dimensions[bit] -= weight
    fingerprint = 0
    for bit, score in enumerate(dimensions):
        if score > 0:
            fingerprint |= 1 << bit
    return f"{fingerprint:016x}"


def similarity_ratio(left: str | None, right: str | None) -> float:
    """计算规范化文本的序列相似度，范围 0-1。"""

    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()
