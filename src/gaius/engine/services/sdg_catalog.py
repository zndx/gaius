"""Signals Data Governance catalog from the local ``sdg-corpora`` pin.

Aegir publishes the SHARE-tier vocabulary here. Gaius consumes it; it
does not own or regenerate the ontology. Missing checkout is fail-fast
— there is no in-tree substitute.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SDG_CORPORA = _REPO_ROOT / "external" / "sdg-corpora"
_ANNOTATIONS = Path("vocabulary") / "annotations.csv"


@dataclass(frozen=True)
class SdgConcept:
    code: str
    label: str
    notation: str
    parent_code: str
    description: str


class SdgCatalog:
    """SKOS annotation vocabulary (``vocabulary/annotations.csv``)."""

    def __init__(self, concepts: dict[str, SdgConcept], *, root: Path) -> None:
        if not concepts:
            raise ValueError(
                "SDG catalog is empty.\n"
                "  Guru: #SDG.00000001.NOCORPORA\n"
                "  Try: git submodule update --init external/sdg-corpora"
            )
        self.concepts = concepts
        self.root = root

    @classmethod
    def load(cls, root: Path | None = None) -> SdgCatalog:
        checkout = Path(root) if root is not None else DEFAULT_SDG_CORPORA
        path = checkout / _ANNOTATIONS
        if not path.is_file():
            raise FileNotFoundError(
                f"SDG vocabulary not found: {path}\n"
                "  Guru: #SDG.00000001.NOCORPORA\n"
                "  Try: git submodule update --init external/sdg-corpora"
            )
        concepts: dict[str, SdgConcept] = {}
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                code = (row.get("code") or "").strip()
                if not code:
                    continue
                concepts[code] = SdgConcept(
                    code=code,
                    label=(row.get("label") or "").strip(),
                    notation=(row.get("notation") or "").strip(),
                    parent_code=(row.get("parent_code") or "").strip(),
                    description=(row.get("description") or "").strip(),
                )
        return cls(concepts, root=checkout)

    def get(self, code: str) -> SdgConcept | None:
        return self.concepts.get(code)

    def require(self, code: str) -> SdgConcept:
        hit = self.get(code)
        if hit is None:
            raise ValueError(
                f"Unknown SDG code {code!r} (not in sdg-corpora vocabulary).\n"
                "  Guru: #SDG.00000002.UNKCODE\n"
                "  Try: check external/sdg-corpora/vocabulary/annotations.csv"
            )
        return hit

    def __contains__(self, code: str) -> bool:
        return code in self.concepts

    def __len__(self) -> int:
        return len(self.concepts)
