"""
comparison_engine.py
--------------------
Pure aggregation: reads pre-loaded report dicts, produces ComparisonResult.
No I/O, no Flask, no side effects.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from comparison_models import ComparisonResult, ParserCorpusScore, ParserDocumentScore


def _find_doc(report: dict, doc_name: str) -> Optional[dict]:
    """Return the document entry for doc_name from a general_report dict, or None."""
    if not report:
        return None
    return next(
        (d for d in report.get("documents", []) if d.get("doc_name") == doc_name),
        None,
    )


def _extract_counts(doc: Optional[dict]) -> tuple[int, int, int, int]:
    """
    Extract (coverage_checked, coverage_failed, noise_checked, noise_failed)
    from a document entry in general_report.json.
    Returns (0, 0, 0, 0) when the doc is missing.
    """
    if doc is None:
        return 0, 0, 0, 0
    cov  = doc.get("coverage", {})
    nois = doc.get("noise", {})
    coverage_checked = cov.get("unique_ngrams_checked_count", 0)
    coverage_failed  = cov.get("missing_unique_ngrams_count", 0)
    noise_checked    = nois.get("unique_parser_words_checked", 0)
    noise_failed     = nois.get("noise_words_count", 0)
    return coverage_checked, coverage_failed, noise_checked, noise_failed


def _pool_coverage(docs: List[ParserDocumentScore], checked_attr: str, failed_attr: str) -> float:
    """Coverage: 1 - failed/checked. Higher is better. Returns 1.0 when nothing to check."""
    total_checked = sum(getattr(d, checked_attr) for d in docs)
    total_failed  = sum(getattr(d, failed_attr)  for d in docs)
    if total_checked == 0:
        return 1.0
    return round(1.0 - total_failed / total_checked, 4)


def _pool_noise(docs: List[ParserDocumentScore], checked_attr: str, failed_attr: str) -> float:
    """Noise: failed/checked. Lower is better. Returns 0.0 when nothing to check."""
    total_checked = sum(getattr(d, checked_attr) for d in docs)
    total_failed  = sum(getattr(d, failed_attr)  for d in docs)
    if total_checked == 0:
        return 0.0
    return round(total_failed / total_checked, 4)


def compare_parsers(
    reports_by_parser: Dict[str, Dict[str, dict]],
    selected_docs: List[str],
) -> ComparisonResult:
    """
    Build a ComparisonResult from cached report dicts.

    Args:
        reports_by_parser: mapping of
            parser_id -> {
                "general":    general_report dict  (Pass 1),
                "general_pp": general_report dict  (Pass 2 / postprocessing),
            }
        selected_docs: subset of doc names to include in pooling.

    Returns:
        ComparisonResult with one ParserCorpusScore per parser, sorted by
        rank_post ascending (best first).
    """
    corpus_scores: List[ParserCorpusScore] = []

    for parser_name, reports in reports_by_parser.items():
        general    = reports.get("general")    or {}
        general_pp = reports.get("general_pp") or {}

        doc_scores: List[ParserDocumentScore] = []

        for doc_name in selected_docs:
            raw_doc = _find_doc(general,    doc_name)
            pp_doc  = _find_doc(general_pp, doc_name)

            cov_chk, cov_fail, noi_chk, noi_fail          = _extract_counts(raw_doc)
            pp_cov_chk, pp_cov_fail, pp_noi_chk, pp_noi_fail = _extract_counts(pp_doc)

            doc_scores.append(ParserDocumentScore(
                parser_name=parser_name,
                doc_name=doc_name,
                coverage_checked=cov_chk,
                coverage_failed=cov_fail,
                noise_checked=noi_chk,
                noise_failed=noi_fail,
                post_coverage_checked=pp_cov_chk,
                post_coverage_failed=pp_cov_fail,
                post_noise_checked=pp_noi_chk,
                post_noise_failed=pp_noi_fail,
            ))

        corpus = ParserCorpusScore(parser_name=parser_name, docs=doc_scores)
        corpus.weighted_coverage_raw  = _pool_coverage(doc_scores, "coverage_checked", "coverage_failed")
        corpus.weighted_noise_raw     = _pool_noise(doc_scores, "noise_checked",    "noise_failed")
        corpus.weighted_coverage_post = _pool_coverage(doc_scores, "post_coverage_checked", "post_coverage_failed")
        corpus.weighted_noise_post    = _pool_noise(doc_scores, "post_noise_checked",    "post_noise_failed")
        corpus_scores.append(corpus)

    # Rank by post coverage descending (higher coverage = better rank)
    sorted_post = sorted(corpus_scores, key=lambda c: c.weighted_coverage_post, reverse=True)
    for rank, corpus in enumerate(sorted_post, start=1):
        corpus.rank_post = rank

    sorted_raw = sorted(corpus_scores, key=lambda c: c.weighted_coverage_raw, reverse=True)
    for rank, corpus in enumerate(sorted_raw, start=1):
        corpus.rank_raw = rank

    # Final list sorted by rank_post
    corpus_scores.sort(key=lambda c: c.rank_post)

    return ComparisonResult(
        selected_docs=list(selected_docs),
        parsers=list(reports_by_parser.keys()),
        scores=corpus_scores,
    )
