"""清洗、去重与预处理模块。"""

from opinion_monitor.processing.normalizer import (
    canonicalize_url,
    normalize_text,
    sha256_hex,
    simhash64,
    similarity_ratio,
)
from opinion_monitor.processing.pipeline import CleaningPipeline, ProcessingRunResult

__all__ = [
    "CleaningPipeline",
    "ProcessingRunResult",
    "canonicalize_url",
    "normalize_text",
    "sha256_hex",
    "simhash64",
    "similarity_ratio",
]
