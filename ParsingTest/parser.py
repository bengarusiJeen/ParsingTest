"""
parser.py
---------
Document parser plug-in — routes to one of two parser services:

  • Default service (port 4004) — Azure DI / base text / Document Intelligence
      POST http://localhost:4004/api/v1/parser/parse?parser_method=<method>
      Response: { "content": "<plain text>" }

  • PyMuPDF service (port 8001) — selected when parser_method == "pdf_pymupdf"
      POST http://localhost:8001/parse?method=markdown
      Response: RAG document { "blocks": [{"text": ...}, ...] }

Expected signature:
    parse(file_path: str) -> str
"""
from __future__ import annotations

from pathlib import Path

import httpx

_DEFAULT_URL  = "http://localhost:4004/api/v1/parser/parse"
_PYMUPDF_URL  = "http://localhost:8001/parse"
_OUTPUT_DIR   = Path(r"C:\Users\BenGarusi\Desktop\Parsing Test\parsing_files")


def _save_output(file_path: Path, text: str) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUTPUT_DIR / (file_path.stem + ".txt")
    out.write_text(text, encoding="utf-8")


def _extract_text_from_rag(data: dict) -> str:
    """Flatten a RAG-format response (blocks list) into plain text."""
    blocks = data.get("blocks", [])
    return "\n".join(b.get("text", "") for b in blocks if b.get("text"))


def parse(file_path: str, parser_method: str = "base_text_parser") -> str:
    """
    Extract plain text from a document file via the appropriate parser service.
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

    if parser_method == "pdf_pymupdf":
        url = f"{_PYMUPDF_URL}?method=markdown"
    else:
        url = _DEFAULT_URL + (f"?parser_method={parser_method}" if parser_method else "")

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

    data = response.json()
    if parser_method == "pdf_pymupdf":
        result = _extract_text_from_rag(data)
    else:
        result = data.get("content", "")

    _save_output(path, result)
    return result