"""
frontend/server.py
------------------
Flask development server for the Parser Diagnostics POC UI.

Usage
-----
    cd "C:/Users/BenGarusi/Desktop/Parsing Test"
    pip install flask
    python frontend/server.py

Then open http://localhost:5000 in your browser.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT            = Path(__file__).parent.parent          # project root
FRONTEND_DIR    = Path(__file__).parent                 # frontend/
MAIN_SCRIPT     = ROOT / "ParsingTest" / "main.py"
FILES_DIR       = ROOT / "files_to_test"
GENERAL_JSON    = ROOT / "general_report.json"
DIAG_JSON       = ROOT / "diagnostics_report.json"
GENERAL_PP_JSON = ROOT / "postprocessing-general_report.json"
DIAG_PP_JSON    = ROOT / "postprocessing-diagnostics_report.json"
GENERAL_PP_JSON_LEGACY = ROOT / "general_report-postprocessing.json"
DIAG_PP_JSON_LEGACY    = ROOT / "diagnostics_report-postprocessing.json"

SUPPORTED_EXTS = {'.pdf', '.docx', '.doc', '.pptx', '.xlsx'}

app = Flask(__name__, static_folder=str(FRONTEND_DIR))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict | None:
    """Read a JSON file; return None if missing or malformed."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_json_any(paths: list[Path]) -> dict | None:
    """Read first available JSON from a list of candidate paths."""
    for path in paths:
        data = _load_json(path)
        if data is not None:
            return data
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/api/files", methods=["GET"])
def list_files():
    """List available document folders in files_to_test."""
    if not FILES_DIR.exists():
        return jsonify({"files": []}), 200

    result = []
    for d in sorted(FILES_DIR.iterdir()):
        if not d.is_dir():
            continue
        ext = ""
        for f in d.iterdir():
            if f.suffix.lower() in SUPPORTED_EXTS:
                ext = f.suffix.lower().lstrip(".")
                break
        result.append({"name": d.name, "ext": ext})

    return jsonify({"files": result})


def _wipe_report_files():
    for _p in [GENERAL_JSON, DIAG_JSON, GENERAL_PP_JSON, DIAG_PP_JSON,
               GENERAL_PP_JSON_LEGACY, DIAG_PP_JSON_LEGACY]:
        try:
            _p.unlink(missing_ok=True)
        except OSError:
            pass


def _run_single_parser(parser_method: str, selected: list) -> dict:
    """Run the evaluation pipeline for one parser and return the result dict."""
    _wipe_report_files()

    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        str(FILES_DIR),
        "--verbose",
        "--output", str(GENERAL_JSON),
        "--parser", parser_method,
    ]
    if selected:
        cmd += ["--include", ",".join(selected)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Evaluation timed out after 180 s.",
                "stdout": "", "stderr": ""}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "stdout": "", "stderr": ""}

    general       = _load_json(GENERAL_JSON)
    diagnostic    = _load_json(DIAG_JSON)
    general_pp    = _load_json_any([GENERAL_PP_JSON, GENERAL_PP_JSON_LEGACY])
    diagnostic_pp = _load_json_any([DIAG_PP_JSON, DIAG_PP_JSON_LEGACY])

    return {
        "status":        "ok" if proc.returncode == 0 else "error",
        "returncode":    proc.returncode,
        "stdout":        proc.stdout,
        "stderr":        proc.stderr,
        "general":       general,
        "diagnostic":    diagnostic,
        "general_pp":    general_pp,
        "diagnostic_pp": diagnostic_pp,
    }


@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    """Run the full evaluation pipeline and return both JSON reports."""
    body     = request.get_json(silent=True) or {}
    selected = body.get("selected", [])

    # Accept either parsers (list, new) or parser (single string, legacy)
    parsers_list = body.get("parsers", None)
    if parsers_list is None:
        parsers_list = [body.get("parser", "base_text_parser")]

    if len(parsers_list) == 1:
        result = _run_single_parser(parsers_list[0], selected)
        return jsonify(result)

    # Multi-parser: run each sequentially, collect per-parser results
    parser_results = {}
    for parser_method in parsers_list:
        parser_results[parser_method] = _run_single_parser(parser_method, selected)

    return jsonify({"multi_parser": True, "parsers": parser_results})


@app.route("/api/results", methods=["GET"])
def results():
    """Return cached reports without re-running the evaluation."""
    general       = _load_json(GENERAL_JSON)
    diagnostic    = _load_json(DIAG_JSON)
    general_pp    = _load_json_any([GENERAL_PP_JSON, GENERAL_PP_JSON_LEGACY])
    diagnostic_pp = _load_json_any([DIAG_PP_JSON, DIAG_PP_JSON_LEGACY])

    if general is None and diagnostic is None:
        return jsonify({"status": "no_results"}), 404

    return jsonify({
        "status":        "ok",
        "general":       general,
        "diagnostic":    diagnostic,
        "general_pp":    general_pp,
        "diagnostic_pp": diagnostic_pp,
    })


# ── Stream comparison ─────────────────────────────────────────────────────────

PARSING_FILES_DIR = ROOT / "parsing_files"


def _parse_gt_blocks(raw: str) -> list[str]:
    """Extract text blocks from a GT Text.txt file (delimited by ==== lines)."""
    blocks: list[str] = []
    current: list[str] = []
    in_block = False
    for line in raw.splitlines():
        if line.strip() == "====":
            if in_block:
                text = "\n".join(current).strip()
                if text:
                    blocks.append(text)
                current, in_block = [], False
            else:
                in_block = True
        elif in_block:
            current.append(line)
    if in_block and current:
        text = "\n".join(current).strip()
        if text:
            blocks.append(text)
    return blocks


def _annotate(text: str, spec: list[tuple[str, str]]) -> list[tuple[int, int, str]]:
    """
    Find non-overlapping (start, end, cls) spans for each (word, cls) in spec.
    Earlier entries in spec take priority — first match wins for each position.
    """
    used: set[int] = set()
    spans: list[tuple[int, int, str]] = []
    for word, cls in spec:
        if not word or not text:
            continue
        wlen = len(word)
        pos = 0
        while True:
            idx = text.find(word, pos)
            if idx == -1:
                break
            end = idx + wlen
            if not used.intersection(range(idx, end)):
                spans.append((idx, end, cls))
                used.update(range(idx, end))
            pos = idx + 1
    return sorted(spans)


def _build_segments(text: str, spans: list[tuple[int, int, str]]) -> list[dict]:
    """Convert annotated spans into a [{text, cls}] segment list for the frontend."""
    segs: list[dict] = []
    pos = 0
    for start, end, cls in spans:
        if start > pos:
            segs.append({"text": text[pos:start], "cls": ""})
        segs.append({"text": text[start:end], "cls": cls})
        pos = end
    if pos < len(text):
        segs.append({"text": text[pos:], "cls": ""})
    return [s for s in segs if s["text"]]


def _find_doc(data: dict | None, doc_name: str) -> dict | None:
    """Find a document entry by doc_name in a report dict."""
    if not data:
        return None
    return next(
        (d for d in data.get("documents", []) if d.get("doc_name") == doc_name),
        None,
    )


@app.route("/api/stream_data", methods=["GET"])
def stream_data():
    """
    Return GT, raw-parser, and post-processed text as annotated segment lists
    for the Document Stream Comparison view.

    Query params:
      doc  — document name (matches folder name in files_to_test/ and
              doc_name in diagnostic reports)
    """
    doc_name = request.args.get("doc", "").strip()
    if not doc_name:
        return jsonify({"error": "Missing ?doc= parameter"}), 400

    # ── Text files ────────────────────────────────────────────────────────────
    gt_file  = FILES_DIR        / doc_name / "GT" / "Text.txt"
    raw_file = PARSING_FILES_DIR / f"{doc_name}.txt"
    pp_file  = PARSING_FILES_DIR / f"{doc_name}_after_post.txt"

    gt_text = raw_text = pp_text = None

    if gt_file.exists():
        blocks  = _parse_gt_blocks(gt_file.read_text(encoding="utf-8", errors="replace"))
        gt_text = "\n\n".join(blocks)

    if raw_file.exists():
        raw_text = raw_file.read_text(encoding="utf-8", errors="replace").strip()

    if pp_file.exists():
        pp_text = pp_file.read_text(encoding="utf-8", errors="replace").strip()

    # ── Diagnostic & general reports ──────────────────────────────────────────
    diag_doc    = _find_doc(_load_json(DIAG_JSON), doc_name)
    diag_pp_doc = _find_doc(_load_json_any([DIAG_PP_JSON, DIAG_PP_JSON_LEGACY]), doc_name)
    gen_doc     = _find_doc(_load_json(GENERAL_JSON), doc_name)
    gen_pp_doc  = _find_doc(_load_json_any([GENERAL_PP_JSON, GENERAL_PP_JSON_LEGACY]), doc_name)

    # ── Extract issue lists ───────────────────────────────────────────────────
    def _issues(doc: dict | None) -> dict:
        dp  = (doc or {}).get("detected_problems", {})
        fmt = dp.get("FORMATTING_ISSUES", {})
        return {
            "ocr":      dp.get("OCR_SPLIT",    {}).get("issues",  []),
            "merged":   dp.get("MERGED_WORDS", {}).get("issues",  []),
            "punct":    fmt.get("MISPLACED_PUNCTUATION", {}).get("issues", []),
            "reversal": fmt.get("WORD_ORDER_REVERSAL",   {}).get("issues", []),
            "unclass":  dp.get("UNCLASSIFIED", {}).get("ngrams",  []),
        }

    raw_iss = _issues(diag_doc)
    pp_iss  = _issues(diag_pp_doc)

    noise_raw = (gen_doc    or {}).get("noise", {}).get("noise_words", [])
    noise_pp  = (gen_pp_doc or {}).get("noise", {}).get("noise_words", [])

    # ── Determine what was fixed by postprocessing ────────────────────────────
    raw_ocr_originals = {i.get("original_word", "") for i in raw_iss["ocr"]}
    pp_ocr_originals  = {i.get("original_word", "") for i in pp_iss["ocr"]}
    ocr_fixed = raw_ocr_originals - pp_ocr_originals   # fixed by PP
    ocr_still = raw_ocr_originals & pp_ocr_originals   # still broken after PP

    raw_merged_set   = {i.get("merged_word", "") for i in raw_iss["merged"]}
    pp_merged_set    = {i.get("merged_word", "") for i in pp_iss["merged"]}
    merged_fixed_set = raw_merged_set - pp_merged_set

    # Original constituent words that were recovered when a merge was fixed
    fixed_orig_words: set[str] = set()
    for iss in raw_iss["merged"]:
        if iss.get("merged_word", "") in merged_fixed_set:
            fixed_orig_words.update(iss.get("original", []))

    # ── Build annotation specs ────────────────────────────────────────────────

    # RAW column: highlight every detected problem
    raw_spec: list[tuple[str, str]] = []
    for iss in raw_iss["ocr"]:
        for frag in iss.get("fragments_in_parser", []):
            raw_spec.append((frag, "hl-error"))
    for iss in raw_iss["merged"]:
        raw_spec.append((iss.get("merged_word", ""), "hl-format"))
    for iss in raw_iss["punct"] + raw_iss["reversal"]:
        pt = iss.get("parser_text", "")
        if pt:
            raw_spec.append((pt, "hl-format"))
    for w in noise_raw:
        raw_spec.append((w, "hl-noise"))

    # GT column: fixed issues → green, still-missing → muted red underline
    gt_spec: list[tuple[str, str]] = []
    for w in ocr_fixed:
        gt_spec.append((w, "hl-fixed"))
    for w in ocr_still:
        gt_spec.append((w, "hl-missing"))
    for w in fixed_orig_words:
        gt_spec.append((w, "hl-fixed"))
    for ng in pp_iss["unclass"]:
        gt_spec.append((ng, "hl-missing"))

    # PP column: fixed → green, still-broken → red/orange, remaining noise → strikethrough
    pp_spec: list[tuple[str, str]] = []
    for w in ocr_fixed:
        pp_spec.append((w, "hl-fixed"))
    for iss in pp_iss["ocr"]:
        for frag in iss.get("fragments_in_parser", []):
            pp_spec.append((frag, "hl-error"))
    for w in fixed_orig_words:
        pp_spec.append((w, "hl-fixed"))
    for iss in pp_iss["merged"]:
        pp_spec.append((iss.get("merged_word", ""), "hl-format"))
    for iss in pp_iss["punct"] + pp_iss["reversal"]:
        pt = iss.get("parser_text", "")
        if pt:
            pp_spec.append((pt, "hl-format"))
    for w in noise_pp:
        pp_spec.append((w, "hl-noise"))

    # ── Assemble response ─────────────────────────────────────────────────────
    def _segs(text: str | None, spec: list[tuple[str, str]]) -> list[dict]:
        if text is None:
            return []
        return _build_segments(text, _annotate(text, spec))

    return jsonify({
        "gt":      _segs(gt_text,  gt_spec),
        "raw":     _segs(raw_text, raw_spec),
        "pp":      _segs(pp_text,  pp_spec),
        "has_gt":  gt_text  is not None,
        "has_raw": raw_text is not None,
        "has_pp":  pp_text  is not None,
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("  ParserDiag — Evaluation Dashboard")
    print("  ──────────────────────────────────")
    print("  Open  →  http://localhost:5000")
    print()
    app.run(debug=True, port=5000, use_reloader=False)
