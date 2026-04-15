"""
gt_loader.py
------------
Everything related to loading and tokenizing Ground Truth (GT) files.

GT file format
--------------
Each block of evaluated content is wrapped between ==== markers:

    ====
    hello world
    foo bar
    ====

load_gt() returns a list of blocks, where each block is a list of tokens.
"""
from __future__ import annotations


from pathlib import Path
from typing import List

from utils import clean_text, normalize_gt_punctuation, tokenize

# ══════════════════════════════════════════════
# GT loader
# ══════════════════════════════════════════════

def load_gt(gt_dir: Path) -> List[List[str]]:
    """
    Parse a GT directory and return a list of blocks.
    Each block is a list of words (tokenised lines between ==== markers).

    File resolution order inside gt_dir:
      1. Text.txt  (preferred)
      2. Any *.txt file whose name does NOT start with "desc"

    Returns:
        [ ["hello", "world", "foo", "bar"], ["another", "block"], ... ]
    """
    preferred = gt_dir / "Text.txt"
    if preferred.exists():
        txt_files = [preferred]
    else:
        txt_files = sorted(
            f for f in gt_dir.glob("*.txt") if not f.name.startswith("desc")
        )

    if not txt_files:
        raise FileNotFoundError(f"No GT .txt file found in {gt_dir}")

    blocks:        List[List[str]] = []
    current_block: List[str]       = []
    in_block                       = False

    for line in txt_files[0].read_text(encoding="utf-8").splitlines():
        if line.strip() == "====":
            if in_block:
                # closing marker — save the block if it has content
                if current_block:
                    normalized_block = normalize_gt_punctuation("\n".join(current_block))
                    blocks.append(tokenize(clean_text(normalized_block)))
                current_block = []
            in_block = not in_block
            continue

        if in_block:
            current_block.append(line)

    # guard: file ends without a closing ====
    if in_block and current_block:
        normalized_block = normalize_gt_punctuation("\n".join(current_block))
        blocks.append(tokenize(clean_text(normalized_block)))

    return blocks