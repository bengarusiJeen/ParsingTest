"""
main.py
-------
CLI entry point and evaluation orchestrator.

Usage
1. cd "C:/Users/BenGarusi/Desktop/Parsing Test/ParsingTest"
-----
  # Clean overview of all documents
  python main.py "C:/Users/.../files_to_test"

  # Full details + JSON report
  python main.py "C:/Users/.../files_to_test" --verbose --output results.json

  # Summary only (no per-document output)
  python main.py "C:/Users/.../files_to_test" --quiet
"""
from __future__ import annotations

import sys
from pathlib import Path

# Must come before any local imports so Python can find them from any directory
sys.path.insert(0, str(Path(__file__).parent))

# Ensure stdout/stderr handle Unicode (e.g. Hebrew filenames) on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
from typing import List, Optional, Set, Tuple

import gt_loader
from Diagnostics import run_diagnostics, DIAGNOSTICS_PP_FILENAME
from metrics import compute_coverage, compute_noise, generate_ngrams
from models import BlockResult, DocumentResult, Score
from ocr import pre_test
from parser import parse
from postprocessing import Postprocessing
from reporting import print_result, print_summary, save_json_report
from utils import collect_files_dirs_to_test, clean_text, find_document_file, tokenize
from substitutions import SubstitutionTable


def _is_punct_token(word: str) -> bool:
    return bool(word) and all(not c.isalnum() for c in word)


def _maybe_strip_punctuation_tokens(tokens: List[str], n: int) -> List[str]:
    if n <= 4:
        return tokens
    return [w for w in tokens if not _is_punct_token(w)]

# ══════════════════════════════════════════════
# Document evaluation
# ══════════════════════════════════════════════

def evaluate_document(
    file_dir:      Path,
    n:             int = 3,
    postprocessor: Optional[Postprocessing] = None,
    _parser_text:  Optional[str] = None,
    sub_table:     Optional[SubstitutionTable] = None,   # ← add this
) -> Tuple[DocumentResult, Set[str], Set[str], Set[str], str, str]:
    """
    Evaluate a single document folder.

    Steps:
      1. Load GT blocks from gt/
      2. Find and parse the document file (or use *_parser_text* if supplied)
      3. Optionally apply *postprocessor* to the parser output
      4. Compute coverage (per block) and noise (document level)
      5. Return a fully populated DocumentResult plus the raw parser text

    Args:
        postprocessor  — if provided, apply its ``apply()`` method to the
                         parser text before tokenisation (PP pass).
        _parser_text   — skip re-parsing and use this string directly;
                         lets the PP pass reuse the text cached from the
                         standard pass without calling the parser twice.
    """
    gt_dir = file_dir / "GT"
    if not gt_dir.exists():
        raise FileNotFoundError(f"Missing GT/ subfolder in {file_dir}")

    # ── Load GT ─────────────────────────────────────────────
    gt_blocks = gt_loader.load_gt(gt_dir)
    gt_blocks = [_maybe_strip_punctuation_tokens(block, n) for block in gt_blocks]
    if not gt_blocks:
        print(f"[warn] {file_dir.name}: no ==== body blocks found in GT",
              file=sys.stderr)
        
    all_gt_words_set    = {word for block in gt_blocks for word in block}

    # ──────────────────── INIT postprocessor vocab with all GT words ──────────────────
    if postprocessor is not None:
        postprocessor._vocab = all_gt_words_set
    

    # ── Parse document ──────────────────────────────────────
    test_file = find_document_file(file_dir)
    # Use the cached raw text when available (avoids parsing the file twice).
    raw_parser_text = _parser_text if _parser_text is not None else parse(str(test_file))
    # Apply postprocessor when running the PP evaluation pass.
    working_text = postprocessor.apply(raw_parser_text) if postprocessor is not None else raw_parser_text
    parser_words = tokenize(working_text)
    parser_words = _maybe_strip_punctuation_tokens(parser_words, n)


    # ── Build lookup sets ────────────────────────────────────
    parser_words_set    = set(parser_words)
    parser_ngrams_set   = set(generate_ngrams(parser_words, n))

    # Diagnostics build
    parser_bigrams_set = set(generate_ngrams(parser_words, 2))



    # ── Per-block coverage ───────────────────────────────────
    block_results: List[BlockResult] = []
    for i, block_words in enumerate(gt_blocks, start=1):
        coverage_block_score, missing = compute_coverage(
            block_words,
            parser_ngrams_set,
            parser_words_set=parser_words_set,
            n=n,
            sub_table=sub_table,    # ← add this

        )
        block_results.append(BlockResult(
            block_index          = i,
            coverage_block_score = coverage_block_score,
            missing_words        = missing,
        ))

    # ── Document-level noise ─────────────────────────────────
    noise_score, extra = compute_noise(all_gt_words_set, parser_words_set, sub_table=sub_table)

    # ── Aggregate coverage ───────────────────────────────────
    total_checked = sum(br.coverage_block_score.checked for br in block_results)
    total_failed  = sum(br.coverage_block_score.failed  for br in block_results)
    doc_coverage  = Score(checked=total_checked, failed=total_failed)

    res=DocumentResult(
        doc_name          = file_dir.name,
        doc_file          = str(test_file),
        coverage_score    = doc_coverage,
        noise_score       = noise_score,
        gt_word_count     = sum(len(b) for b in gt_blocks),
        parser_word_count = len(parser_words),
        block_results     = block_results,
        missing_triagams  = [w for br in block_results for w in br.missing_words],
        extra_words       = extra,
    )

    file_ext = Path(str(test_file)).suffix.lower()

    return res, parser_ngrams_set, parser_words_set, parser_bigrams_set, file_ext, raw_parser_text







# ══════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Evaluate RAG parser output against ground truth.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Metrics
-------
  Coverage  fraction of GT body trigrams found in parser output
  Noise     fraction of parser words not found anywhere in GT (lower = better)

Examples
--------
    python main.py "C:/Users/BenGarusi/Desktop/Parsing Test/files_to_test" --verbose --output results2.json

    python main.py "C:/Users/BenGarusi/Desktop/Parsing Test/files_to_test" --n 8 --verbose --output results.json

  
        """
    )
    p.add_argument("input_dir", type=Path,
                   help="Folder containing one subfolder per document.")
    p.add_argument("--output",  type=Path,
                   help="Save JSON report to this file.")

    p.add_argument("--verbose", action="store_true",
                   help="Print every missing and extra word for each document.")
    p.add_argument("--n",       type=int, default=3,
                   help="N-gram size for coverage evaluation (default: 3).")
    p.add_argument("--quiet",   action="store_true",
                   help="Suppress per-document output (summary only).")
    return p


def main() -> None:
    args = build_arg_parser().parse_args()

    input_dir: Path = args.input_dir
    if not input_dir.exists():
        raise SystemExit(f"[error] Folder not found: {input_dir}")
    if not input_dir.is_dir():
        raise SystemExit(f"[error] Not a folder: {input_dir}")

    pre_test(input_dir)

    files_dirs = collect_files_dirs_to_test(input_dir)
    if not files_dirs:
        raise SystemExit("No valid document folders found.")
    
    sub_table = SubstitutionTable.load(Path(__file__).parent / "substitutions.json")


    results:     List[DocumentResult] = []
    parser_data: List[Tuple[Set[str], Set[str], Set[str], str]] = []
    # Pairs of (file_dir, raw_parser_text) for every document that succeeded,
    # used to feed the postprocessing pass without re-invoking the parser.
    successful_runs: List[Tuple[Path, str]] = []

    # ══════════════════════════════════════════════
    # Pass 1 — Standard evaluation
    # ══════════════════════════════════════════════
    for file_dir in files_dirs:
        try:
            result, p_ngrams_set, p_words_set, p_bigrams_set, f_ext, raw_text = \
                evaluate_document(file_dir, n=args.n, sub_table=sub_table)  # ← add sub_table to the call
            results.append(result)
            parser_data.append((p_ngrams_set, p_words_set, p_bigrams_set, f_ext))
            successful_runs.append((file_dir, raw_text))

            if not args.quiet:
                print_result(result, verbose=args.verbose, n=args.n)
        except NotImplementedError as e:
            print(f"\n[!] {e}", file=sys.stderr)
            raise SystemExit(1)
        except Exception as e:
            print(f"[error] {file_dir.name}: {e}", file=sys.stderr)

    if results:
        print("=" * 30)
        print_summary(results)

    # ── Results JSON (optional, CLI argument) ────────────────
    if args.output and results:
        save_json_report(results, args.output, n=args.n)

    # ── Diagnostics JSON (always written, fixed filename) ────
    if results:
        run_diagnostics(results, parser_data, input_dir)

    # ══════════════════════════════════════════════
    # Pass 2 — Postprocessing evaluation
    # ══════════════════════════════════════════════
    

    pp = Postprocessing()
    results_pp:     List[DocumentResult] = []
    parser_data_pp: List[Tuple[Set[str], Set[str], Set[str], str]] = []

    pp_text_dir = Path(__file__).parent.parent / "parsing_files"
    pp_text_dir.mkdir(exist_ok=True)

    for file_dir, raw_text in successful_runs:
        try:
            result_pp, p_ngrams_pp, p_words_pp, p_bigrams_pp, f_ext, _ = \
                evaluate_document(file_dir, n=args.n, postprocessor=pp, _parser_text=raw_text, sub_table=sub_table)
            results_pp.append(result_pp)
            parser_data_pp.append((p_ngrams_pp, p_words_pp, p_bigrams_pp, f_ext))

            postprocessed_text = pp.apply(raw_text)
            out_file = pp_text_dir / f"{file_dir.name}_after_post.txt"
            out_file.write_text(postprocessed_text, encoding="utf-8")
        except Exception as e:
            print(f"[warn] Postprocessing failed for {file_dir.name}: {e}", file=sys.stderr)

    # ── Postprocessing results JSON ───────────────────────────
    if args.output and results_pp:
        pp_output = args.output.parent / ("postprocessing-" + args.output.stem + args.output.suffix)
        save_json_report(results_pp, pp_output, n=args.n)

    # ── Postprocessing diagnostics JSON ──────────────────────
    if results_pp:
        run_diagnostics(results_pp, parser_data_pp, input_dir,
                        output_filename=DIAGNOSTICS_PP_FILENAME)



if __name__ == "__main__":
    main()

"""
to run the server, use the command line:
cd "C:/Users/BenGarusi/Desktop/Parsing Test"
python frontend/server.py
and then open http://localhost:5000 in a web browser to access the interface.

"""