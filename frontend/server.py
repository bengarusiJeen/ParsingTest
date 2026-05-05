"""
frontend/server.py
------------------
Flask development server for the ParserEval POC UI.

Usage
-----
    cd "C:/Users/BenGarusi/Desktop/Parsing Test"
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
ROOT               = Path(__file__).parent.parent
FRONTEND_DIR       = Path(__file__).parent
MAIN_SCRIPT        = ROOT / "ParsingTest" / "main.py"
FILES_DIR          = ROOT / "files_to_test"
PARSING_FILES_DIR  = ROOT / "parsing_files"
GENERAL_JSON       = ROOT / "general_report.json"
DIAG_JSON          = ROOT / "diagnostics_report.json"
GENERAL_PP_JSON    = ROOT / "postprocessing-general_report.json"
DIAG_PP_JSON       = ROOT / "postprocessing-diagnostics_report.json"
GENERAL_PP_LEGACY  = ROOT / "general_report-postprocessing.json"
DIAG_PP_LEGACY     = ROOT / "diagnostics_report-postprocessing.json"

app = Flask(__name__, static_folder=str(FRONTEND_DIR))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_json_any(paths: list[Path]) -> dict | None:
    for path in paths:
        data = _load_json(path)
        if data is not None:
            return data
    return None


def _has_gt(doc_dir: Path) -> bool:
    gt_dir = doc_dir / "GT"
    if gt_dir.exists() and list(gt_dir.glob("*.txt")):
        return True
    return (doc_dir / "Text.txt").exists()


def _read_gt(doc_dir: Path) -> str | None:
    gt_dir = doc_dir / "GT"
    if gt_dir.exists():
        gt_files = list(gt_dir.glob("*.txt"))
        if gt_files:
            return gt_files[0].read_text(encoding="utf-8", errors="replace")
    txt = doc_dir / "Text.txt"
    if txt.exists():
        return txt.read_text(encoding="utf-8", errors="replace")
    return None


def _noise_rate(doc: dict) -> float:
    noise = doc.get("noise", {})
    count = noise.get("noise_words_count", 0)
    total = noise.get("unique_parser_words_checked", 1)
    return count / max(total, 1)


# ── Static pages ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "app.html")

@app.route("/legacy")
def legacy():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


# ── Meta / config endpoints ───────────────────────────────────────────────────

@app.route("/api/parsers")
def get_parsers():
    return jsonify({"parsers": [
        {"id": "document_intelligence", "name": "Document Intelligence",   "label": "DI",      "description": "Azure Document Intelligence", "available": True},
        {"id": "pdf_pymupdf",           "name": "PyMuPDF",                 "label": "PyMuPDF", "description": "Fast PDF extraction",          "available": True},
        {"id": "base_text_parser",      "name": "Base Text Extractor",     "label": "Base",    "description": "Generic text extraction",       "available": True},
        {"id": "mineru",                "name": "MinerU",                  "label": "MinerU",  "description": "Coming soon",                  "available": False},
        {"id": "marker",                "name": "Marker",                  "label": "Marker",  "description": "Coming soon",                  "available": False},
        {"id": "surya",                 "name": "Surya",                   "label": "Surya",   "description": "Coming soon",                  "available": False},
    ]})


@app.route("/api/documents")
def get_documents():
    docs = []
    if not FILES_DIR.exists():
        return jsonify({"documents": []})
    for doc_dir in sorted(FILES_DIR.iterdir()):
        if not doc_dir.is_dir():
            continue
        exts = {".pdf", ".docx", ".txt", ".pptx", ".xlsx"}
        doc_files = [f for f in doc_dir.iterdir() if f.suffix.lower() in exts]
        if not doc_files:
            continue
        doc_file = doc_files[0]
        docs.append({
            "name":     doc_dir.name,
            "filename": doc_file.name,
            "type":     doc_file.suffix.lower().lstrip("."),
            "has_gt":   _has_gt(doc_dir),
        })
    return jsonify({"documents": docs})


@app.route("/api/postprocessing")
def get_postprocessing():
    return jsonify({"methods": [
        {"id": "line_break_normalization",  "name": "Line break normalization"},
        {"id": "punctuation_normalization", "name": "Punctuation normalization"},
        {"id": "hebrew_english_spacing",    "name": "Hebrew/English spacing normalization"},
        {"id": "broken_word_repair",        "name": "Broken-word repair"},
        {"id": "diacritics_removal",        "name": "Diacritics / nikud removal"},
        {"id": "extra_whitespace_cleanup",  "name": "Extra whitespace cleanup"},
    ]})


# ── Dashboard aggregate ───────────────────────────────────────────────────────

@app.route("/api/dashboard-data")
def dashboard_data():
    general    = _load_json(GENERAL_JSON)
    general_pp = _load_json_any([GENERAL_PP_JSON, GENERAL_PP_LEGACY])
    diagnostic = _load_json(DIAG_JSON)

    if not general:
        return jsonify({"rows": [], "summary": {}, "parser_averages": []})

    pp_by_doc   = {d["doc_name"]: d for d in (general_pp or {}).get("documents", [])}
    diag_by_doc = {d["doc_name"]: d for d in (diagnostic  or {}).get("documents", [])}

    rows = []
    for doc in general.get("documents", []):
        doc_name    = doc["doc_name"]
        cov_before  = doc["coverage"]["coverage_rate"]
        noise_before = _noise_rate(doc)

        pp_doc    = pp_by_doc.get(doc_name, {})
        cov_after = pp_doc.get("coverage", {}).get("coverage_rate", cov_before)
        noise_after = _noise_rate(pp_doc) if pp_doc else noise_before

        diag_doc = diag_by_doc.get(doc_name, {})
        probs    = diag_doc.get("detected_problems", {})

        score = round((cov_after * 0.7 + (1 - noise_after) * 0.3) * 100, 1)

        rows.append({
            "parser":          "Base Text Extractor",
            "parser_id":       "base_text_parser",
            "doc_name":        doc_name,
            "cov_before":      round(cov_before  * 100, 1),
            "noise_before":    round(noise_before * 100, 1),
            "cov_after":       round(cov_after    * 100, 1),
            "noise_after":     round(noise_after  * 100, 1),
            "cov_improvement": round((cov_after - cov_before) * 100, 1),
            "noise_reduction": round((noise_before - noise_after) * 100, 1),
            "score":           score,
            "issues": {
                "missing":    probs.get("MISSING_BLOCK_PARSE", {}).get("count", 0),
                "ocr_split":  probs.get("OCR_SPLIT",           {}).get("count", 0),
                "merged":     probs.get("MERGED_WORDS",         {}).get("count", 0),
                "formatting": probs.get("FORMATTING_ISSUES",    {}).get("count", 0),
                "unclassified": probs.get("UNCLASSIFIED",       {}).get("count", 0),
            },
        })

    rows.sort(key=lambda x: x["score"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i

    if rows:
        best_cov_row    = max(rows, key=lambda r: r["cov_after"])
        lowest_noise_row= min(rows, key=lambda r: r["noise_after"])
        best_pp_row     = max(rows, key=lambda r: r["cov_improvement"])
    else:
        best_cov_row = lowest_noise_row = best_pp_row = {}

    summary = {
        "best_coverage":        best_cov_row.get("cov_after", 0),
        "best_coverage_parser": best_cov_row.get("parser", ""),
        "lowest_noise":         lowest_noise_row.get("noise_after", 0),
        "lowest_noise_parser":  lowest_noise_row.get("parser", ""),
        "best_pp_improvement":  best_pp_row.get("cov_improvement", 0),
        "best_pp_parser":       best_pp_row.get("parser", ""),
        "total_docs":           len(set(r["doc_name"] for r in rows)),
        "total_parsers":        len(set(r["parser_id"] for r in rows)),
    }

    parser_avg = {}
    for row in rows:
        pid = row["parser_id"]
        if pid not in parser_avg:
            parser_avg[pid] = {"parser": row["parser"], "cov_after": [], "noise_after": [], "cov_before": [], "noise_before": []}
        parser_avg[pid]["cov_after"].append(row["cov_after"])
        parser_avg[pid]["noise_after"].append(row["noise_after"])
        parser_avg[pid]["cov_before"].append(row["cov_before"])
        parser_avg[pid]["noise_before"].append(row["noise_before"])

    parser_averages = []
    for pid, data in parser_avg.items():
        def avg(lst): return round(sum(lst) / len(lst), 1) if lst else 0
        parser_averages.append({
            "parser_id":   pid,
            "parser":      data["parser"],
            "avg_cov_after":    avg(data["cov_after"]),
            "avg_noise_after":  avg(data["noise_after"]),
            "avg_cov_before":   avg(data["cov_before"]),
            "avg_noise_before": avg(data["noise_before"]),
        })

    return jsonify({"rows": rows, "summary": summary, "parser_averages": parser_averages})


# ── Diagnostics detail ────────────────────────────────────────────────────────

@app.route("/api/diagnostics/<path:doc_name>")
def diagnostics_detail(doc_name: str):
    general    = _load_json(GENERAL_JSON)
    general_pp = _load_json_any([GENERAL_PP_JSON, GENERAL_PP_LEGACY])
    diag       = _load_json(DIAG_JSON)
    diag_pp    = _load_json_any([DIAG_PP_JSON, DIAG_PP_LEGACY])

    def find_doc(report, name):
        if not report:
            return {}
        return next((d for d in report.get("documents", []) if d["doc_name"] == name), {})

    g_doc    = find_doc(general,    doc_name)
    gpp_doc  = find_doc(general_pp, doc_name)
    d_doc    = find_doc(diag,       doc_name)
    dpp_doc  = find_doc(diag_pp,    doc_name)

    if not g_doc:
        return jsonify({"error": f"No data for '{doc_name}'"}), 404

    cov_before   = g_doc.get("coverage", {}).get("coverage_rate", 0)
    noise_before = _noise_rate(g_doc)
    cov_after    = gpp_doc.get("coverage", {}).get("coverage_rate", cov_before) if gpp_doc else cov_before
    noise_after  = _noise_rate(gpp_doc) if gpp_doc else noise_before
    score        = round((cov_after * 0.7 + (1 - noise_after) * 0.3) * 100, 1)

    probs = d_doc.get("detected_problems", {})
    mb  = probs.get("MISSING_BLOCK_PARSE", {})
    ocr = probs.get("OCR_SPLIT",           {})
    mg  = probs.get("MERGED_WORDS",        {})
    fmt = probs.get("FORMATTING_ISSUES",   {})
    uc  = probs.get("UNCLASSIFIED",        {})

    return jsonify({
        "doc_name":    doc_name,
        "parser":      "Base Text Extractor",
        "cov_before":  round(cov_before  * 100, 1),
        "noise_before":round(noise_before * 100, 1),
        "cov_after":   round(cov_after    * 100, 1),
        "noise_after": round(noise_after  * 100, 1),
        "score":       score,
        "summary": {
            "missing":     mb.get("count", 0),
            "ocr_split":   ocr.get("count", 0),
            "merged":      mg.get("count", 0),
            "formatting":  fmt.get("count", 0),
            "unclassified":uc.get("count", 0),
            "total_missing_ngrams": d_doc.get("total_missing_ngrams", 0),
        },
        "problems": {
            "missing_block": mb,
            "ocr_split":     ocr,
            "merged_words":  mg,
            "formatting":    fmt,
            "unclassified":  uc,
        },
        "ocr_splits": ocr.get("issues", []),
    })


# ── Text content endpoints ────────────────────────────────────────────────────

@app.route("/api/parser-output/<path:doc_name>")
def get_parser_output(doc_name: str):
    path = PARSING_FILES_DIR / f"{doc_name}.txt"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify({"content": path.read_text(encoding="utf-8", errors="replace")})


@app.route("/api/parsed-output/<path:doc_name>")
def get_parsed_output(doc_name: str):
    path = PARSING_FILES_DIR / f"{doc_name}_after_post.txt"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify({"content": path.read_text(encoding="utf-8", errors="replace")})


@app.route("/api/ground-truth/<path:doc_name>")
def get_ground_truth(doc_name: str):
    content = _read_gt(FILES_DIR / doc_name)
    if content is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"content": content})


# ── Evaluation pipeline ───────────────────────────────────────────────────────

@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    try:
        proc = subprocess.run(
            [sys.executable, str(MAIN_SCRIPT), str(FILES_DIR), "--verbose",
             "--output", str(GENERAL_JSON)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Evaluation timed out after 300 s."}), 504
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "status":      "ok" if proc.returncode == 0 else "error",
        "returncode":  proc.returncode,
        "stdout":      proc.stdout,
        "stderr":      proc.stderr,
    })


@app.route("/api/results", methods=["GET"])
def results():
    general    = _load_json(GENERAL_JSON)
    diagnostic = _load_json(DIAG_JSON)
    general_pp = _load_json_any([GENERAL_PP_JSON, GENERAL_PP_LEGACY])
    diag_pp    = _load_json_any([DIAG_PP_JSON, DIAG_PP_LEGACY])
    if general is None:
        return jsonify({"status": "no_results"}), 404
    return jsonify({
        "status":      "ok",
        "general":     general,
        "diagnostic":  diagnostic,
        "general_pp":  general_pp,
        "diagnostic_pp": diag_pp,
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("  ParserEval POC")
    print("  ----------------------------------")
    print("  Open  ->  http://localhost:5000")
    print()
    app.run(debug=True, port=5000, use_reloader=False)
