"""
utils.py
--------
Filesystem helpers for discovering document folders and document files.
No metrics, no parsing, no output — pure path logic.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
from typing import List
import string


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".pptx", ".xlsx"}


def find_document_file(file_dir: Path) -> Path:
    """
    Find the document file sitting directly inside file_dir (not in GT/).
    Prefers the file whose stem matches the folder name when multiple exist.
    Raises FileNotFoundError if no supported file is found.
    """
    candidates = [
        f for f in file_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not candidates:
        raise FileNotFoundError(
            f"No supported document file found in {file_dir}\n"
            f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if len(candidates) > 1:
        name_match = [f for f in candidates if f.stem == file_dir.name]
        if name_match:
            return name_match[0]
        print(
            f"[warn] Multiple document files in '{file_dir.name}', "
            f"using '{candidates[0].name}'",
            file=sys.stderr,
        )

    return candidates[0]


def collect_files_dirs_to_test(input_dir: Path) -> List[Path]:
    """
    Return all subfolders of input_dir that contain:
      - a GT/ subfolder
      - at least one supported document file next to it

    Skipped folders are reported to stderr.
    """
    dirs: List[Path] = []

    for candidate in sorted(input_dir.iterdir()):
        if not candidate.is_dir():
            continue

        has_gt  = (candidate / "GT").exists()
        has_doc = any(
            f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
            for f in candidate.iterdir()
        )

        if has_gt and has_doc:
            dirs.append(candidate)
        else:
            missing = []
            if not has_gt:
                missing.append("GT/")
            if not has_doc:
                missing.append("document file")
            print(
                f"[warn] Skipping '{candidate.name}' — missing: {', '.join(missing)}",
                file=sys.stderr,
            )

    return dirs



# ══════════════════════════════════════════════
# Text utilities
# ══════════════════════════════════════════════

def clean_text(text: str) -> str:
    """Collapse all whitespace runs into a single space and strip edges."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()




def tokenize(text: str) -> List[str]:
    """
    Split text into words by whitespace, then strip ALL punctuation from
    each token. Empty tokens (e.g. a bare '...') are dropped.
 
    Applied to both GT and parser output, so comparisons are always
    punctuation-free on both sides.
 
    Example:
        "Hello, world. don't"  →  ["Hello", "world", "dont"]
    """
    return [
        normalized
        for word in text.split()
        if (normalized := normalize_word(word))   # drop empty strings
    ]
 
 

# ══════════════════════════════════════════════
# Text normalisation
# ══════════════════════════════════════════════
 
# Pre-built translation table that maps every punctuation character to None
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)
 
 
def normalize_word(word: str) -> str:
    """
    Remove ALL punctuation characters from a word.
 
    Examples:
        'world.'  → 'world'
        "don't"   → 'dont'
        '(hello)' → 'hello'
        '...'     → ''        ← empty string; callers should filter these out
    """
    return word.translate(_PUNCT_TABLE)
 
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".pptx", ".xlsx"}
 
 