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

from flask import Flask, jsonify, send_from_directory

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


@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    """Run the full evaluation pipeline and return both JSON reports."""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(MAIN_SCRIPT),
                str(FILES_DIR),
                "--verbose",
                "--output", str(GENERAL_JSON),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Evaluation timed out after 180 s."}), 504
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    general       = _load_json(GENERAL_JSON)
    diagnostic    = _load_json(DIAG_JSON)
    general_pp    = _load_json_any([GENERAL_PP_JSON, GENERAL_PP_JSON_LEGACY])
    diagnostic_pp = _load_json_any([DIAG_PP_JSON, DIAG_PP_JSON_LEGACY])

    return jsonify({
        "status":        "ok" if proc.returncode == 0 else "error",
        "returncode":    proc.returncode,
        "stdout":        proc.stdout,
        "stderr":        proc.stderr,
        "general":       general,
        "diagnostic":    diagnostic,
        "general_pp":    general_pp,
        "diagnostic_pp": diagnostic_pp,
    })


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
