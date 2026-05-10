"""
comparison_models.py
--------------------
Dataclasses for the parser comparison layer.
No logic lives here — only data shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class ParserDocumentScore:
    """Raw numerator/denominator counts for one parser on one document."""
    parser_name: str
    doc_name: str

    # Coverage (raw pass)
    coverage_checked: int
    coverage_failed: int

    # Noise (raw pass)
    noise_checked: int
    noise_failed: int

    # Coverage (postprocessing pass)
    post_coverage_checked: int
    post_coverage_failed: int

    # Noise (postprocessing pass)
    post_noise_checked: int
    post_noise_failed: int


@dataclass
class ParserCorpusScore:
    """Pooled (weighted) scores for one parser across the selected documents."""
    parser_name: str
    docs: List[ParserDocumentScore] = field(default_factory=list)

    # Weighted rates — computed by comparison_engine, not set by callers directly
    weighted_coverage_raw: float = 0.0
    weighted_noise_raw: float = 0.0
    weighted_coverage_post: float = 0.0
    weighted_noise_post: float = 0.0

    # Rank among all compared parsers (1 = best)
    rank_raw: int = 0
    rank_post: int = 0


@dataclass
class ComparisonResult:
    """Full result of a multi-parser comparison over a set of documents."""
    selected_docs: List[str]
    parsers: List[str]
    scores: List[ParserCorpusScore]  # sorted by rank_post ascending
