from __future__ import annotations
 
import json
from pathlib import Path
 
 
class SubstitutionTable:
    """
    Compiles character equivalence groups into a single str.maketrans table.
 
    All characters in a group are mapped to the first character in that group
    (the canonical form).  Because str.translate() is a single C-level pass,
    the cost per lookup is O(len(string)) regardless of how many equivalence
    groups are defined — adding new groups to substitutions.json has zero
    performance impact.
 
    Instantiation
    -------------
    Always use the class methods rather than the constructor directly:
 
        SubstitutionTable.load(path)   — load from a JSON file
        SubstitutionTable.empty()      — no-op table (translate returns input unchanged)
    """
 
    def __init__(self, translation_table: dict) -> None:
        self._table = translation_table
 
    # ── Constructors ──────────────────────────────────────────────────────────
 
    @classmethod
    def load(cls, path: Path) -> "SubstitutionTable":
        """
        Load equivalence groups from a JSON file and compile the translation table.
 
        Expected JSON structure:
            {
              "equivalence_groups": [
                ["•", "-", "–", "—"],
                ["\u2019", "'"],
                ...
              ]
            }
 
        Groups with fewer than 2 members are silently skipped.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
 
        mapping: dict[str, str] = {}
        for group in data.get("equivalence_groups", []):
            if len(group) < 2:
                continue
            canonical = group[0]
            for char in group[1:]:
                # Only single characters are supported; multi-char strings are skipped.
                if len(char) == 1:
                    mapping[char] = canonical
 
        return cls(str.maketrans(mapping))
 
    @classmethod
    def empty(cls) -> "SubstitutionTable":
        """Return a no-op table — translate() returns the input string unchanged."""
        return cls(str.maketrans({}))
 
    # ── Public API ────────────────────────────────────────────────────────────
 
    def translate(self, text: str) -> str:
        """
        Return *text* with all equivalence substitutions applied.
 
        Call this on both sides of a comparison to normalise them to their
        canonical forms before checking equality.  Never store the result —
        it is for transient comparison only.
        """
        return text.translate(self._table)