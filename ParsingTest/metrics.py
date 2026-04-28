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

from typing import List, Set, Tuple, TYPE_CHECKING, Optional

from models import Score

if TYPE_CHECKING:
    from substitutions import SubstitutionTable


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
    parser_words_set: Set[str] | None = None,
    n: int = 3,
    sub_table: Optional[SubstitutionTable] = None,   
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
    
    # Pre-build translated shadow sets once — used only for fallback lookups.
    translated_parser_ngrams: Optional[Set[str]] = (
        {sub_table.translate(p) for p in parser_ngrams_set}
        if sub_table else None
    )
    translated_parser_words: Optional[Set[str]] = (
        {sub_table.translate(w) for w in parser_words_set}
        if (sub_table and parser_words_set) else None
    )

    # When a GT block is shorter than the requested n-gram size, fall back to
    # word-level checks so short blocks still get evaluated instead of being
    # treated as an automatic miss.
    if len(block_words) < n:
        if parser_words_set is None:
            phrase = " ".join(block_words)
            if phrase in parser_ngrams_set:
                return Score(checked=1, failed=0), []
            if translated_parser_ngrams is not None and \
               sub_table.translate(phrase) in translated_parser_ngrams:
                return Score(checked=1, failed=0), []
            return Score(checked=1, failed=1), [phrase]

        seen_words: set[str] = set()
        missing_words: list[str] = []
        for word in block_words:
            if word in seen_words:
                continue
            seen_words.add(word)
            if word not in parser_words_set:
                 # Substitution fallback for individual words.
                if translated_parser_words is not None and \
                   sub_table.translate(word) in translated_parser_words:
                    continue
                missing_words.append(word)

        score = Score(checked=len(seen_words), failed=len(missing_words))
        return score, missing_words

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
            # Substitution fallback for n-grams.
            if translated_parser_ngrams is not None and \
               sub_table.translate(t) in translated_parser_ngrams:
                continue
            missing.append(t)

    score = Score(checked=len(gt_unique_ngrams), failed=len(missing))
    return score, missing


def compute_noise(
    gt_words_set:     Set[str],
    parser_words_set: Set[str],
    sub_table: Optional["SubstitutionTable"] = None,

) -> Tuple[Score, List[str]]:
    """
    Measure how many parser words are absent from the GT vocabulary.

    Returns:
        (Score, extra_words)   Score.rate == 1.0 means zero noise.
    """

    # Pre-build translated GT shadow set once.
    translated_gt: Optional[Set[str]] = (
        {sub_table.translate(w) for w in gt_words_set}
        if sub_table else None
    )

    extra: list[str] = []
    for w in parser_words_set:
        if w not in gt_words_set:
            # Substitution fallback — not noise if translated form is in GT.
            if translated_gt is not None and \
               sub_table.translate(w) in translated_gt:
                continue
            extra.append(w)
 
    score = Score(checked=len(parser_words_set), failed=len(extra))

    return score, extra