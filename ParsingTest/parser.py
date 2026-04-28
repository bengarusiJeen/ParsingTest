"""
parser.py
---------
Document parser plug-in — company parser-service (http://localhost:4004).

Expected signature:
    parse(file_path: str) -> str

Sends the file as raw bytes to the parser-service and returns the extracted
plain text from the response's "content" field.
"""
from __future__ import annotations

from pathlib import Path

import httpx

# PARSER_SERVICE_URL = "http://localhost:4004/api/v1/parser/parse"  # default (uses Azure DI for PDFs)
PARSER_SERVICE_URL = "http://localhost:4004/api/v1/parser/parse"  # base URL — parser_method added per file type below
_OUTPUT_DIR = Path(r"C:\Users\BenGarusi\Desktop\Parsing Test\parsing_files")


def _save_output(file_path: Path, text: str) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUTPUT_DIR / (file_path.stem + ".txt")
    out.write_text(text, encoding="utf-8")


def parse(file_path: str) -> str:
    """
    Extract plain text from a document file via the company parser-service.
    Returns the extracted text as a plain string.
    """
    path = Path(file_path)

    with open(path, "rb") as f:
        file_bytes = f.read()

    # HTTP headers must be ASCII — fall back to a safe name if filename contains non-ASCII (e.g. Hebrew)
    try:
        path.name.encode("ascii")
        safe_filename = path.name
    except UnicodeEncodeError:
        safe_filename = f"document{path.suffix}"

    # --- Parser method selection (swap the active line to switch parsers) ---
    # url = PARSER_SERVICE_URL + ("?parser_method=pdf_pymupdf" if path.suffix.lower() == ".pdf" else "")  # PyMuPDF (PDFs only) + auto-detect (others)
    url = PARSER_SERVICE_URL + "?parser_method=base_text_parser"  # Base Text Parser (all file types)

    response = httpx.post(
        url,
        content=file_bytes,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Original-Filename": safe_filename,
        },
        timeout=120,
    )
    response.raise_for_status()

    result = response.json().get("content", "")

    _save_output(path, result)
    return result