"""
metrics.py
----------
Pure computation functions — no I/O, no side effects.

Three metrics:
    generate_ngrams   build word-level n-grams (with fallback for short sequences)
    compute_coverage  fraction of GT n-grams found in parser output
    compute_noise     fraction of parser words NOT present in GT

Mixed-script note
-----------------
Hebrew<->Latin boundary normalisation is handled upstream in clean_text()
(utils.py) before tokenisation, so this module needs no special handling.
"""
from __future__ import annotations

from typing import List, Set, Tuple

from models import Score


def generate_ngrams(words: List[str], n: int = 3) -> List[str]:
    """
    Generate word-level n-grams as joined strings.

    Fallback for sequences shorter than n:
        len(words) < n  ->  one single gram of all available words
        len(words) == 0 ->  []
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if not words:
        return []
    if len(words) < n:
        return [" ".join(words)]
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def compute_coverage(
    block_words: List[str],
    parser_ngrams_set: Set[str],
    n: int = 3,
) -> Tuple[Score, List[str]]:
    """
    Measure how many GT n-grams appear in the parser output.

    Args:
        block_words:       tokenised words from one GT block
        parser_ngrams_set: pre-built set of all parser n-grams

    Returns:
        (Score, missing_ngrams)   Score.rate == 1.0 means full coverage.
    """
    if not block_words:
        return Score(checked=0, failed=0), []

    gt_ngrams_ordered = generate_ngrams(block_words, n)
    gt_unique_ngrams  = set(gt_ngrams_ordered)
    if not gt_unique_ngrams:
        return Score(checked=0, failed=0), []

    seen:    set[str]  = set()
    missing: list[str] = []
    for t in gt_ngrams_ordered:
        if t in seen:
            continue
        seen.add(t)
        if t not in parser_ngrams_set:
            missing.append(t)

    score = Score(checked=len(gt_unique_ngrams), failed=len(missing))
    return score, missing


def compute_noise(
    gt_words_set:     Set[str],
    parser_words_set: Set[str],
) -> Tuple[Score, List[str]]:
    """
    Measure how many parser words are absent from the GT vocabulary.

    Returns:
        (Score, extra_words)   Score.rate == 1.0 means zero noise.
    """
    extra = list(parser_words_set - gt_words_set)
    score = Score(checked=len(parser_words_set), failed=len(extra))
    return score, extra