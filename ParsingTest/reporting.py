"""
reporting.py
------------
All human-readable and machine-readable output.

Functions:
    print_result      per-document table (console)
    print_summary     aggregate summary across all documents (console)
    save_json_report  full results as a JSON file
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from models import BlockResult, DocumentResult


# ══════════════════════════════════════════════
# Console output
# ══════════════════════════════════════════════

def _ngram_label(n: int) -> str:
    names = {1: "unigrams", 2: "bigrams", 3: "trigrams", 4: "fourgrams",
             5: "fivegrams", 6: "sixgrams", 7: "sevengrams", 8: "eightgrams"}
    return names.get(n, f"{n}-grams")


def print_result(result: DocumentResult, verbose: bool = False, n: int = 3) -> None:
    thick = "═" * 62
    thin  = "─" * 62

    print("=" * 30)
    print(f"\n{thick}")
    print(f"  Document : {result.doc_name}")
    print(f"  File     : {Path(result.doc_file).name}")
    print(f"  GT words : {result.gt_word_count}   "
          f"Parser words : {result.parser_word_count}")
    print(f"  Total Coverage(document) : {result.coverage_score.fraction}"
          f"   ({result.coverage_pct:.1%})")
    print(f"  Total Noise(document)    : {result.noise_score.fraction}"
          f"   ({result.noise_pct:.1%})  ↑ higher = more noise")

    if verbose and result.extra_words:
        print(f"\n  ☁ Extra (noise) words ({len(result.extra_words)}):")
        _print_word_list(result.extra_words)

    print(thick)

    # ── Per-block coverage ──────────────────────────────────
    for br in result.block_results:
        print(
            f"  Block {br.block_index:<3} Coverage : "
            f"{br.coverage_block_score.fraction:<12}"
            f"  ({br.coverage_block_score.failed} missing"
            f" / {br.coverage_block_score.checked} {_ngram_label(n)})"
        )
        if verbose and br.missing_words:
            print(f"    ✗ Missing {_ngram_label(n)} ({len(br.missing_words)}):")
            _print_word_list(br.missing_words)
        print()

    print(thin)


def print_summary(results: List[DocumentResult]) -> None:
    if not results:
        return
    n         = len(results)
    avg_cov   = sum(r.coverage_pct for r in results) / n
    avg_noise = sum(r.noise_pct    for r in results) / n

    print("\n" + "═" * 62)
    print("  SUMMARY")
    print("═" * 62)
    print(f"  Documents evaluated : {n}")
    print(f"  Avg Coverage Score  : {avg_cov:.1%}")
    print(f"  Avg Noise Score     : {avg_noise:.1%}  ↑ higher = more noise")
    print("═" * 62)


def _print_word_list(words: List[str], per_line: int = 8) -> None:
    for i in range(0, len(words), per_line):
        chunk = words[i : i + per_line]
        print("    " + "  ".join(f"'{w}'" for w in chunk))


# ══════════════════════════════════════════════
# JSON report
# ══════════════════════════════════════════════

def save_json_report(results: List[DocumentResult], path: Path, n: int = 3) -> None:

    def _block(br: BlockResult) -> dict:
        return {
            "block_index": br.block_index,
            "coverage": {
                "total":               br.coverage_block_score.checked,
                "missing":             br.coverage_block_score.failed,
                "coverage_block_rate": br.coverage_block_score.rate,
                "fraction_block":      br.coverage_block_score.fraction,
            },
            f"missing_{_ngram_label(n)}_in_block": br.missing_words,
        }

    def _doc(r: DocumentResult) -> dict:
        return {
            "doc_name": r.doc_name,
            "coverage": {
                "coverage_rate": r.coverage_pct,
                "fraction":      r.coverage_score.fraction,
            },
            "noise": {
                "total":             r.noise_score.checked,
                "extra":             r.noise_score.failed,
                "extra_words_total": r.extra_words,
                "noise_rate":        r.noise_pct,
                "fraction":          r.noise_score.fraction,
            },
            "gt_word_count":     r.gt_word_count,
            "parser_word_count": r.parser_word_count,
            "block_results":     [_block(br) for br in r.block_results],
        }

    SEP = "=" * 30

    doc_count = len(results)
    summary = {
        "documents_evaluated": doc_count,
        "avg_coverage_rate":   round(sum(r.coverage_pct for r in results) / doc_count, 4),
        "avg_noise_rate":      round(sum(r.noise_pct    for r in results) / doc_count, 4),
    }

    lines: list[str] = []
    lines.append(json.dumps({"summary": summary}, ensure_ascii=False, indent=2))
    for r in results:
        lines.append(SEP)
        lines.append(json.dumps(_doc(r), ensure_ascii=False, indent=2))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[✓] JSON report saved to {path}")