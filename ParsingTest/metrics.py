"""
metrics.py
----------
Pure computation functions — no I/O, no side effects.

Three metrics:
    generate_trigrams   build word-level trigrams (with bigram/unigram fallback)
    compute_coverage    fraction of GT trigrams found in parser output
    compute_noise       fraction of parser words NOT present in GT
"""
from __future__ import annotations

from typing import List, Set, Tuple

from models import Score


# ══════════════════════════════════════════════
# Trigram helpers
# ══════════════════════════════════════════════



def generate_ngrams(words: List[str], n: int = 3) -> List[str]:
    """
    Generate word-level n-grams as joined strings.
 
    Fallback for sequences shorter than n:
        len(words) < n  →  one single gram of all available words
        len(words) == 0 →  []
 
    Examples (n=3):
        ["I", "love", "machine", "learning"]
        → ["I love machine", "love machine learning"]
 
    Examples (n=2):
        ["I", "love", "machine"]
        → ["I love", "love machine"]
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
 
    if not words:
        return []
 
    if len(words) < n:
        # fallback: one gram containing all available words
        return [" ".join(words)]
 
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]
 
 


# ══════════════════════════════════════════════
# Coverage
# ══════════════════════════════════════════════

def compute_coverage(
    block_words: List[str],
    parser_ngrams_set: Set[str],
    n: int = 3,
) -> Tuple[Score, List[str]]:
    """
    Measure how many GT n-grams appear in the parser output.

    Args:
        block_words:         tokenised words from one GT block
        parser_ngrams_set: pre-built set of all parser n-grams

    Returns:
        (Score, missing_ngrams)
        Score.rate == 1.0 means full coverage.
    """
    if not block_words:
        return Score(checked=0, failed=0), []

    gt_ngrams_ordered = generate_ngrams(block_words, n)
    gt_unique_ngrams  = set(gt_ngrams_ordered)
    if not gt_unique_ngrams:
        return Score(checked=0, failed=0), []

    seen: set[str] = set()
    missing: list[str] = []
    for t in gt_ngrams_ordered:
        if t not in parser_ngrams_set and t not in seen:
            seen.add(t)
            missing.append(t)

    score = Score(checked=len(gt_unique_ngrams), failed=len(missing))
    return score, missing


# ══════════════════════════════════════════════
# Noise
# ══════════════════════════════════════════════

def compute_noise(
    gt_words_set:     Set[str],
    parser_words_set: Set[str],
) -> Tuple[Score, List[str]]:
    """
    Measure how many parser words are absent from the GT vocabulary.

    A high noise rate means the parser is introducing text not in the GT
    (headers, footers, artefacts, OCR garbage, etc.).

    Returns:
        (Score, extra_words)
        Score.rate == 1.0 means zero noise.
    """
    
    # extra = [w for w in parser_words_set if w not in gt_words_set]
    extra = list(parser_words_set - gt_words_set) # Difference

    score = Score(checked=len(parser_words_set), failed=len(extra))
    return score, extra