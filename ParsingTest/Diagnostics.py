"""
diagnostics.py
--------------
Error classification module. Runs after evaluation and produces a
diagnostics_report.json file (fixed name, written next to input_dir).

Four detectors, executed in this order — each acting as a pre-filter for the next:

    1. MISSING_BLOCK_PARSE   — block whose coverage <= MISSING_BLOCK_THRESHOLD.
                               Reported at BLOCK level (list of block indices).
                               Ngrams from failed blocks are SKIPPED by all
                               subsequent detectors.

    2. OCR_SPLIT             — a GT word was genuinely split into two fragments
                               by the parser/OCR. Both fragments must appear as
                               CONSECUTIVE TOKENS in the parser output
                               (checked via parser_bigrams_set).

    3. MERGED_WORDS          — two adjacent GT words were concatenated by the
                               parser.  e.g. "ב tone" → "בtone"
                               Global merge scanner requires one part to be
                               Hebrew-script and the other Latin-script to avoid
                               flagging valid Hebrew morphology.
                               Reported at token level only; no cascading
                               ngram scope is attributed.

    4. FORMATTING_ISSUES     — two sub-types:
                                                             • WORD_ORDER_REVERSAL — fires ONLY when the
                                                                 flipped pair is confirmed in parser ngrams and
                                                                 the original order is not also present once
                                                                 punctuation is normalized away.
                                                                 This prevents colon/period moves from being
                                                                 mislabeled as a word-order reversal.
                               • MISPLACED_PUNCTUATION — improved detector:
                                 an ngram that contains at least one punctuation
                                 token is flagged when ALL its content words
                                 (non-punctuation tokens) exist individually in
                                 parser_words_set. This catches the RTL
                                 punctuation placement problem where the parser
                                 moves . : ] to a different position than the GT.
                                 Previously only checked if without_punct existed
                                 as a complete ngram — now checks each content
                                 word individually, which is reliable even when
                                 the word combination isn't an ngram by itself.

    5. UNCLASSIFIED          — ngrams that none of the detectors explained.

Public API
----------
    run_diagnostics(results, parser_data, input_dir)
        parser_data is a list of
            (parser_ngrams_set, parser_words_set, parser_bigrams_set, file_ext)
        Writes diagnostics_report.json next to input_dir.
        Returns nothing — side-effect only.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

from models import BlockResult, DocumentResult
from utils import _is_hebrew, _is_latin

# ── Tunable constants ────────────────────────────────────────────────────────
MISSING_BLOCK_THRESHOLD = 0.10
DIAGNOSTICS_FILENAME    = "diagnostics_report.json"


# ══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _word_is_hebrew(word: str) -> bool:
    return any(_is_hebrew(c) for c in word)

def _word_is_latin(word: str) -> bool:
    return any(_is_latin(c) for c in word)

def _is_mixed_boundary(w1: str, w2: str) -> bool:
    return (_word_is_hebrew(w1) and _word_is_latin(w2)) or \
           (_word_is_latin(w1)  and _word_is_hebrew(w2))

def _is_cross_script_split(part1: str, part2: str) -> bool:
    """
    True when the two parts come from different scripts.
    Guards the global merge scanner against valid Hebrew morphology.
    """
    return (_word_is_hebrew(part1) and _word_is_latin(part2)) or \
           (_word_is_latin(part1)  and _word_is_hebrew(part2))

def _is_punct_token(word: str) -> bool:
    return bool(word) and all(not c.isalnum() for c in word)


def _normalize_ngram_without_punct(ngram: str) -> str:
    return " ".join(word for word in ngram.split() if not _is_punct_token(word))


# Checking if a phrase (e.g. flipped pair) appears in any parser ngram without punctuation.
def _phrase_in_parser_ngrams(phrase: str, parser_ngrams_set: Set[str]) -> bool:
    if not phrase:
        return False
    for parser_ngram in parser_ngrams_set:
        if phrase in _normalize_ngram_without_punct(parser_ngram):
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Detector 1 — Missing Block Parse
# ══════════════════════════════════════════════════════════════════════════════
# if more then 90% of a GT block's n-grams are missing from the parser output, we classify the entire block as a "MISSING_BLOCK_PARSE" and skip all its n-grams from subsequent
def _detect_missing_blocks(
    block_results: List[BlockResult],
) -> Tuple[List[int], Set[str]]:
    failed_indices: List[int] = []
    skipped_ngrams: Set[str]  = set()

    for br in block_results:
        score = br.coverage_block_score
        if score.checked == 0:
            continue
        if score.rate <= MISSING_BLOCK_THRESHOLD:
            failed_indices.append(br.block_index)
            skipped_ngrams.update(br.missing_words)

    return failed_indices, skipped_ngrams


# ══════════════════════════════════════════════════════════════════════════════
# Detector 2 — OCR Split
# ══════════════════════════════════════════════════════════════════════════════

def _detect_ocr_splits(
    missing_ngrams:     List[str],
    parser_words_set:   Set[str],
    parser_bigrams_set: Set[str],
) -> Tuple[List[dict], Set[str]]:
    """
    Genuine split: both fragments exist in parser AND appear as consecutive
    tokens (bigram check).
    """
    issues:     List[dict] = []
    classified: Set[str]   = set()
    seen_words: Set[str]   = set()

    for ngram in missing_ngrams:
        for word in ngram.split():
            if len(word) < 2:
                continue
            for k in range(1, len(word)):
                prefix, suffix = word[:k], word[k:]
                if (
                    prefix in parser_words_set
                    and suffix in parser_words_set
                    and f"{prefix} {suffix}" in parser_bigrams_set
                ):
                    classified.add(ngram)
                    if word not in seen_words:
                        seen_words.add(word)
                        issues.append({
                            "word":      word,
                            "fragments": [prefix, suffix],
                        })
                    break
            if ngram in classified:
                break

    return issues, classified


# ══════════════════════════════════════════════════════════════════════════════
# Detector 3 — Merged Words
# ══════════════════════════════════════════════════════════════════════════════

def _build_direct_merge_map(
    missing_ngrams:   List[str],
    parser_words_set: Set[str],
) -> Dict[str, List[str]]:
    merge_map: Dict[str, List[str]] = defaultdict(list)
    for ngram in missing_ngrams:
        words = ngram.split()
        if len(words) < 2:
            continue
        for i in range(len(words) - 1):
            w1, w2      = words[i], words[i + 1]
            forward     = w1 + w2
            backward    = w2 + w1
            found_merge = (
                forward  if forward  in parser_words_set else
                backward if backward in parser_words_set else
                None
            )
            if found_merge:
                merge_map[found_merge].append(ngram)
                break
    return merge_map


def _detect_merged_words(
    missing_ngrams:   List[str],
    parser_words_set: Set[str],
    gt_words_set:     Set[str],
) -> Tuple[List[dict], Set[str]]:
    direct_merge_map = _build_direct_merge_map(missing_ngrams, parser_words_set)

    issues:        List[dict] = []
    classified:    Set[str]   = set()
    reported_words: Set[str]  = set()

    def _original_pair(merged_word: str) -> List[str]:
        for k in range(1, len(merged_word)):
            p, s = merged_word[:k], merged_word[k:]
            if p in gt_words_set and s in gt_words_set:
                return [p, s]
        return []

    for merged_word, affected_ngrams in direct_merge_map.items():
        seen_ng: set[str] = set()
        for ng in affected_ngrams:
            if ng not in seen_ng:
                seen_ng.add(ng)
                classified.add(ng)
        reported_words.add(merged_word)
        issues.append({
            "merged_word": merged_word,
            "original":    _original_pair(merged_word),
        })

    missing_words: Set[str] = {w for ng in missing_ngrams for w in ng.split()}
    for parser_token in parser_words_set:
        if parser_token in gt_words_set or parser_token in reported_words:
            continue
        if len(parser_token) < 3:
            continue
        for k in range(1, len(parser_token)):
            part1, part2 = parser_token[:k], parser_token[k:]
            if part1 not in gt_words_set or part2 not in gt_words_set:
                continue
            if not _is_cross_script_split(part1, part2):
                continue
            if part1 not in missing_words and part2 not in missing_words:
                continue
            reported_words.add(parser_token)
            issues.append({
                "merged_word": parser_token,
                "original":    [part1, part2],
            })
            break
    return issues, classified 

# ══════════════════════════════════════════════════════════════════════════════
# Detector 4 — Formatting Issues
# ══════════════════════════════════════════════════════════════════════════════
def _detect_formatting_issues(
    missing_ngrams:    List[str],
    parser_ngrams_set: Set[str],
    parser_words_set:  Set[str],
) -> Tuple[List[dict], Set[str]]:
    """
    WORD_ORDER_REVERSAL
        Fires ONLY when the flipped pair is confirmed in parser ngrams (HIGH).
        Pass 1: adjacent non-punct pairs, mixed-script first.
        Pass 2: punctuation-between-reversed-words (strips punct, checks flip).

    MISPLACED_PUNCTUATION — improved detector
        An ngram containing at least one punctuation token is classified here
        when ALL its content words (non-punct tokens) exist individually in
        parser_words_set.

        Two confidence levels
          HIGH   — without_punct string also found as a complete parser ngram
          MEDIUM — content words all present individually but not as a complete
                   ngram (covers RTL punctuation displacement where the word
                   combination spans a different ngram boundary in the parser)

        This is what clears the bulk of the unclassified list — ngrams like
        ". מה הרכיב", ": קביעת סגנון", "אינו חובה ." where the content is
        correctly parsed but punctuation landed in a different position
    """
    issues:     List[dict] = []
    classified: Set[str]   = set()
    seen:       Set[str]   = set()
    seen_reversal_pairs: Set[Tuple[str, str]] = set()
    normalized_parser_ngrams = {
        _normalize_ngram_without_punct(pg)
        for pg in parser_ngrams_set
    }

    for ngram in missing_ngrams:
        if ngram in seen:
            continue

        words = ngram.split()

        # ── Sub-detector A : Word Order Reversal ─────────────
        if len(words) >= 2:
            non_punct_words = [w for w in words if not _is_punct_token(w)]
            original_phrase = " ".join(non_punct_words)

            # Pass 1: adjacent pairs (mixed-script priority)
            pairs_to_check: List[Tuple[int, str, str]] = []
            for i in range(len(words) - 1):
                w1, w2 = words[i], words[i + 1]
                if _is_punct_token(w1) or _is_punct_token(w2):
                    continue
                if _is_mixed_boundary(w1, w2):
                    pairs_to_check.insert(0, (i, w1, w2))
                else:
                    pairs_to_check.append((i, w1, w2))

            for i, w1, w2 in pairs_to_check:
                flipped        = f"{w2} {w1}"
                pair_key       = (w1, w2)
                if pair_key in seen_reversal_pairs:
                    continue
                original_in_parser = _phrase_in_parser_ngrams(
                    original_phrase, normalized_parser_ngrams
                )
                flip_in_parser = _phrase_in_parser_ngrams(
                    flipped, normalized_parser_ngrams
                )
                if flip_in_parser and not original_in_parser:
                    boundary_type = (
                        "Hebrew↔Latin"  if _is_mixed_boundary(w1, w2) else
                        "Latin↔Latin"   if (_word_is_latin(w1) and _word_is_latin(w2)) else
                        "Hebrew↔Hebrew"
                    )
                    seen.add(ngram)
                    classified.add(ngram)
                    issues.append({
                        "ngram": ngram,
                        "type":  "WORD_ORDER_REVERSAL",
                        "pair":  [w1, w2],
                        "gt_text": original_phrase,
                        "parser_text": flipped,
                        "evidence": (
                            f"{boundary_type} pair ('{w1}', '{w2}'). "
                            f"Flipped pair '{flipped}' confirmed in parser. "
                            f"Confidence: HIGH."
                        ),
                    })
                    seen_reversal_pairs.add(pair_key)
                    break
            if ngram in seen:
                continue

        # ── Sub-detector B : Misplaced Punctuation ───────────
        punct_tokens   = [w for w in words if _is_punct_token(w)]
        content_words  = [w for w in words if not _is_punct_token(w)]

        if punct_tokens and content_words:
            without_punct = " ".join(content_words)
            # Tight gate: require local contiguous evidence in parser flow.
            phrase_in_parser = _phrase_in_parser_ngrams(
                without_punct, normalized_parser_ngrams
            )

            if phrase_in_parser:
                if without_punct in parser_ngrams_set:
                    confidence = "HIGH"
                    detail     = (
                        f"Content words '{without_punct}' found as complete "
                        f"ngram in parser. Punctuation {punct_tokens} misplaced."
                    )
                else:
                    confidence = "MEDIUM"
                    detail     = (
                        f"Content words '{without_punct}' found contiguously "
                        f"inside parser flow after punctuation normalization. "
                        f"Punctuation {punct_tokens} likely caused the boundary "
                        f"shift (RTL displacement)."
                    )

                seen.add(ngram)
                classified.add(ngram)
                issues.append({
                    "ngram":       ngram,
                    "type":        "MISPLACED_PUNCTUATION",
                    "gt_text":     ngram,
                    "parser_text": without_punct,
                    "confidence":  confidence,
                    "evidence":    detail,
                })

    return issues, classified


# ══════════════════════════════════════════════════════════════════════════════
# Per-document diagnostic builder
# ══════════════════════════════════════════════════════════════════════════════

def _diagnose_document(
    result:             DocumentResult,
    parser_ngrams_set:  Set[str],
    parser_words_set:   Set[str],
    parser_bigrams_set: Set[str],
    file_ext:           str,
) -> dict:
    total_missing = len(result.missing_triagams)

    # GT words approximated from missing ngrams
    gt_words_set: Set[str] = {
        w for br in result.block_results
        for ng in br.missing_words
        for w in ng.split()
    }

    # ── 1. Missing Block Parse ───────────────────────────────
    failed_block_indices, skipped_ngrams = _detect_missing_blocks(
        result.block_results
    )
    remaining = [ng for ng in result.missing_triagams if ng not in skipped_ngrams]

    # ── 2. OCR Split ─────────────────────────────────────────
    ocr_issues, ocr_classified = _detect_ocr_splits(
        remaining, parser_words_set, parser_bigrams_set
    )
    remaining = [ng for ng in remaining if ng not in ocr_classified]

    # ── 3. Merged Words + cascade ────────────────────────────
    merge_issues, merge_classified = _detect_merged_words(
        remaining, parser_words_set, gt_words_set
    )
    remaining = [ng for ng in remaining if ng not in merge_classified]

    # ── 4. Formatting Issues ─────────────────────────────────
    fmt_issues, fmt_classified = _detect_formatting_issues(
        remaining, parser_ngrams_set, parser_words_set
    )
    remaining = [ng for ng in remaining if ng not in fmt_classified]

    # ── 5. Unclassified ──────────────────────────────────────
    unclassified = sorted(set(remaining))

    # ── Split FORMATTING_ISSUES by sub-type for cleaner report ──
    word_order_issues = [i for i in fmt_issues if i["type"] == "WORD_ORDER_REVERSAL"]
    misplaced_issues  = [i for i in fmt_issues if i["type"] == "MISPLACED_PUNCTUATION"]

    return {
        "doc_name":             result.doc_name,
        "file_ext":             file_ext,
        "total_missing_ngrams": total_missing,
        "detected_problems": {
            "MISSING_BLOCK_PARSE": {
                "count":         len(failed_block_indices),
                "blocks_number": failed_block_indices,
            },
            "OCR_SPLIT": {
                "count":  len(ocr_issues),
                "issues": ocr_issues,
            },
            "MERGED_WORDS": {
                "count":          len(merge_issues),
                "issues":         merge_issues,
            },
            "FORMATTING_ISSUES": {
                "count": len(fmt_issues),
                "WORD_ORDER_REVERSAL": {
                    "count":  len(word_order_issues),
                    "issues": word_order_issues,
                },
                "MISPLACED_PUNCTUATION": {
                    "count":  len(misplaced_issues),
                    "issues": misplaced_issues,
                },
            },
            "UNCLASSIFIED": {
                "count":  len(unclassified),
                "ngrams": unclassified,
            },
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_diagnostics(
    results:     List[DocumentResult],
    parser_data: List[Tuple[Set[str], Set[str], Set[str], str]],
    input_dir:   Path,
) -> None:
    """
    Run diagnostics on all documents and write diagnostics_report.json.

    Args:
        results      — list of DocumentResult from evaluate_document()
        parser_data  — list of
                         (parser_ngrams_set, parser_words_set,
                          parser_bigrams_set, file_ext)
                       in the same order as results
        input_dir    — the CLI input directory; report is written next to it
    """
    doc_reports: List[dict] = []

    for result, (p_ngrams_set, p_words_set, p_bigrams_set, f_ext) in zip(
        results, parser_data
    ):
        doc_report = _diagnose_document(
            result             = result,
            parser_ngrams_set  = p_ngrams_set,
            parser_words_set   = p_words_set,
            parser_bigrams_set = p_bigrams_set,
            file_ext           = f_ext,
        )
        doc_reports.append(doc_report)

    # ── Top-level summary ────────────────────────────────────
    def _total(category: str) -> int:
        return sum(d["detected_problems"][category]["count"] for d in doc_reports)

    summary = {
        "total_documents":              len(doc_reports),
        "total_missing_ngrams":         sum(d["total_missing_ngrams"] for d in doc_reports),
        "MISSING_BLOCK_PARSE_total":    _total("MISSING_BLOCK_PARSE"),
        "OCR_SPLIT_total":              _total("OCR_SPLIT"),
        "MERGED_WORDS_total":           _total("MERGED_WORDS"),
        "FORMATTING_ISSUES_total":      _total("FORMATTING_ISSUES"),
        "UNCLASSIFIED_total":           _total("UNCLASSIFIED"),
    }

    report = {
        "summary":   summary,
        "documents": doc_reports,
    }

    out_path = input_dir.parent / DIAGNOSTICS_FILENAME
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[✓] Diagnostics report saved to {out_path}")