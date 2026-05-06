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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("  ParserDiag — Evaluation Dashboard")
    print("  ──────────────────────────────────")
    print("  Open  →  http://localhost:5000")
    print()
    app.run(debug=True, port=5000, use_reloader=False)
