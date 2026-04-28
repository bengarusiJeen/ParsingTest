"""
postprocessing.py
-----------------
Postprocessing class: normalises parser output punctuation before scoring
so it can be compared against the Ground Truth on equal terms.

The rules are the mirror image of normalize_gt_punctuation() in utils.py:
the GT is already in the ideal format; this class brings the parser output
up to that same standard before measuring coverage and noise.
"""
from __future__ import annotations

import re

from docx import text


class Postprocessing:


    # Hebrew Unicode ranges used across several rules.
    _HEB = r'\u0590-\u05FF\uFB1D-\uFB4F'

    def apply(self, text: str) -> str:
        """Return *text* with all punctuation normalisation rules applied."""
        text = self._strip_asterisks(text)          # ← add this line

        text = self._fix_punctuation_spacing(text)
        text = self._fix_colon_spacing(text)
        text = self._fix_compound_dashes(text)
        text = self._fix_slashes(text)
        text = self._fix_mixed_language_fusions(text)
        return text

    # ── Rule implementations ───────────────────────────────────────────────────

    def _fix_punctuation_spacing(self, text: str) -> str:
        """Remove erroneous spaces around standard punctuation and brackets."""
        # Remove space(s) before . ? ! , ) ] }
        text = re.sub(r'[ \t]+([.?!,)\]}])', r'\1', text)
        # Remove space(s) after opening bracket ( [ {
        text = re.sub(r'([\[({])[ \t]+', r'\1', text)
        return text

    @staticmethod
    def _is_hebrew_dominant(text: str) -> bool:
        """Return True if more than half of alphabetic characters in *text* are Hebrew."""
        heb = len(re.findall(r'[\u0590-\u05FF\uFB1D-\uFB4F]', text))
        lat = len(re.findall(r'[A-Za-z]', text))
        total = heb + lat
        return total > 0 and heb / total > 0.5

    def _fix_colon_spacing(self, text: str) -> str:
        """Normalize colon placement in parser output.

        Processes the text line-by-line and applies two passes:

        Pass 1 — RTL flip repair (Hebrew-dominant lines only)
            PDF extractors sometimes place the colon at the *start* of a
            Hebrew line because in visual RTL order the colon appears at the
            left edge of the screen.  When the line content after the leading
            ':' is Hebrew-dominant, the colon is moved to the logical end:

                ': מטרת הרכיב'  →  'מטרת הרכיב:'
                ': מה הרכיב מקבל ומחזיר'  →  'מה הרכיב מקבל ומחזיר:'

            Lines whose remaining content is English/Latin-dominant are left
            untouched (a leading ':' there is likely intentional).

        Pass 2 — Space-before-colon repair (all lines)
            Remove one or more spaces/tabs that appear between a letter
            (Hebrew or Latin) and a following colon.  Two categories are
            explicitly protected from this rule:

            • URL schemes — ``://`` is guarded by a negative lookahead on
              the character that follows the colon, so ``https ://`` is left
              alone even if a stray space crept in before the colon.
            • Times — well-formed time literals (``10:30``) have no space
              before the colon and are never touched.  A space before a colon
              that is followed by a digit (``10 :30``) IS normalised because
              no legitimate time literal is written that way and it is almost
              certainly a spurious space.
        """
        lines = text.split('\n')
        result = []
        for line in lines:
            # ── Pass 1: RTL flip repair ──────────────────────────────────
            # Match: optional leading whitespace → ':' → whitespace → content
            m = re.match(r'^[ \t]*:[ \t]*(.+)$', line)
            if m:
                body = m.group(1)
                if self._is_hebrew_dominant(body):
                    # Colon belongs at the logical end of the Hebrew phrase.
                    line = body.rstrip() + ':'

            # ── Pass 2: Space before colon ───────────────────────────────
            # Lookbehind: last char before the spaces must be a letter.
            # Negative lookahead (?!/) protects URL schemes (://).
            line = re.sub(
                rf'(?<=[A-Za-z{self._HEB}])[ \t]+:(?!/)',
                ':',
                line,
            )
            result.append(line)
        return '\n'.join(result)

    def _fix_compound_dashes(self, text: str) -> str:
        """Collapse spaces around '-' for compound words (letter-letter only)."""
        return re.sub(
            r'(?<=[A-Za-z\u0590-\u05FF\uFB1D-\uFB4F])[ \t]*-[ \t]*'
            r'(?=[A-Za-z\u0590-\u05FF\uFB1D-\uFB4F])',
            '-',
            text,
            flags=re.MULTILINE,
        )

    def _fix_slashes(self, text: str) -> str:
        """Remove spaces flanking '/' between non-whitespace characters."""
        return re.sub(
            r'(?<=[^\s])[ \t]*/[ \t]*(?=[^\s])',
            '/',
            text,
            flags=re.MULTILINE,
        )

    def _fix_mixed_language_fusions(self, text: str) -> str:
        """Insert a space at Hebrew/Latin and Hebrew/digit fusion boundaries.

        Handles all four transition directions:
          - Hebrew → Latin   e.g. ``קיבלהTrue``  → ``קיבלה True``
          - Latin  → Hebrew  e.g. ``Messageבאמצעות`` → ``Message באמצעות``
          - Hebrew → digit   e.g. ``נספח3``       → ``נספח 3``
          - digit  → Hebrew  e.g. ``123בדיקה``    → ``123 בדיקה``
        """
        _HEBREW = r'\u0590-\u05FF'

        # Hebrew → Latin or digit
        text = re.sub(
            rf'([{_HEBREW}])([A-Za-z0-9])',
            r'\1 \2',
            text,
        )
        # Latin or digit → Hebrew
        text = re.sub(
            rf'([A-Za-z0-9])([{_HEBREW}])',
            r'\1 \2',
            text,
        )
        return text
    

    def _strip_asterisks(self, text: str) -> str:
        """Remove asterisks used as bold/emphasis markers in parser output."""
        return text.replace('**', '')

