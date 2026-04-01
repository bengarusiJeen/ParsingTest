from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class Score:
    checked: int   # total items evaluated
    failed:  int   # total items that failed (missing / extra)

    @property
    def rate(self) -> float:
        """1.0 = perfect (nothing missing/extra)"""
        return round(1.0 - self.failed / self.checked, 4) if self.checked else 1.0

    @property
    def fraction(self) -> str:
        """Display as 'failed/checked'  e.g. '15/100'"""
        return f"{self.failed}/{self.checked}"


@dataclass
class BlockResult:
    block_index:          int
    coverage_block_score: Score
    missing_words:        List[str] = field(default_factory=list)


@dataclass
class DocumentResult:
    doc_name:  str
    doc_file:  str          # absolute path to the document file that was parsed

    # ── Scores (0.0 – 1.0) ───────────────────
    coverage_score: Score   # fraction of GT body trigrams found in parser output
    noise_score:    Score   # fraction of parser words NOT in GT

    # ── Word counts ──────────────────────────
    gt_word_count:     int  # body words only (==== blocks)
    parser_word_count: int

    # ── Detailed results ─────────────────────
    block_results:   List[BlockResult] = field(default_factory=list)
    missing_triagams: List[str]        = field(default_factory=list)
    extra_words:      List[str]        = field(default_factory=list)

    # ── Convenience properties ───────────────
    @property
    def coverage_pct(self) -> float:
        """1 - (total missing / total evaluated) across all blocks"""
        return self.coverage_score.rate

    @property
    def noise_pct(self) -> float:
        """extra words / total parser words"""
        return (
            round(self.noise_score.failed / self.noise_score.checked, 4)
            if self.noise_score.checked
            else 0.0
        )