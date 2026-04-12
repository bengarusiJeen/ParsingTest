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
# Check if a single character is Hebrew
def _is_hebrew(ch: str) -> bool:
    return "\u0590" <= ch <= "\u05FF" or "\uFB1D" <= ch <= "\uFB4F"

# Check if a single character is Latin (Not a number)
def _is_latin(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()

# Check if we need to insert a space between two adjacent characters based on their scripts
# Handles Hebrew<->Latin and Hebrew<->digit and the opposite 
def _needs_boundary_space(prev: str, cur: str) -> bool:
    """
    Return True if a space should be inserted between prev and cur.
    Handles Hebrew<->Latin and Hebrew<->digit boundaries.

        Hebrew + Latin  : "בTone"   -> "ב Tone"
        Latin  + Hebrew : "Toneכדי" -> "Tone כדי"
        Hebrew + digit  : "ל25"     -> "ל 25"
        digit  + Hebrew : "25ב"     -> "25 ב"
    """
    prev_heb = _is_hebrew(prev)
    prev_lat = _is_latin(prev)
    prev_dig = prev.isdigit()
    cur_heb  = _is_hebrew(cur)
    cur_lat  = _is_latin(cur)
    cur_dig  = cur.isdigit()

    return (
        (prev_heb and cur_lat) or
        (prev_lat and cur_heb) or
        (prev_heb and cur_dig) or
        (prev_dig and cur_heb)
    )


def insert_script_boundary_spaces(text: str) -> str:
    """
    Insert a space wherever adjacent characters cross a Hebrew/Latin/digit
    script boundary with no whitespace between them.

        "בTone"           ->  "ב Tone"
        "לClassifier"     ->  "ל Classifier"
        "קיבלהTrue"       ->  "קיבלה True"
        "ל25"             ->  "ל 25"
        "לאינטגרציהSAP"   ->  "לאינטגרציה SAP"
    """
    if not text:
        return text
    chars  = list(text)
    result = [chars[0]]
    for i in range(1, len(chars)):
        prev, cur = chars[i - 1], chars[i]
        if _needs_boundary_space(prev, cur):
            result.append(" ")
        result.append(cur)
    return "".join(result)



def clean_text(text: str) -> str:
    """
    Normalise text so both GT and parser produce identical tokens:
      1. Pad punctuation with spaces so each mark becomes its own token
         ("word," -> "word ,", "end." -> "end .").
      2. Insert spaces at Hebrew<->Latin and Hebrew<->digit script
         boundaries ("בTone"->"ב Tone", "ל25"->"ל 25").
      3. Collapse all whitespace runs to a single space and strip edges.

    Applied to BOTH parser output and GT text before tokenisation.
    Word-separator removal (hyphens, slashes, etc.) is GT-only and must be
    """
    # text = normalize_punctuation(text)
    text = insert_script_boundary_spaces(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()




def normalize_punctuation(text: str) -> str:
    """
    Ensure every punctuation character is surrounded by spaces so it becomes
    its own token, regardless of how the parser originally attached it to words.

    Examples:
        "שלום,עולם."        →  "שלום , עולם ."
        "קוראים לי בן,אני"  →  "קוראים לי בן , אני"
        "hello(world)"      →  "hello ( world )"

    Apply to BOTH parser output and GT text before comparison so that
    "word," and "word ," are treated identically.
    """
    # Pad every non-word, non-space character with spaces on both sides.
    # \w matches Unicode word characters (including Hebrew letters and digits),
    # so [^\w\s] reliably targets punctuation in multilingual text.
    text = re.sub(r"([^\w\s])", r" \1 ", text)
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
    return word
 
