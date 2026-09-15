"""HermiT-certified OWL TBox for Theta consolidation.

SKOS is terminology grounded to this ontology. CLT is a content graph.
Neither is the TBox. Do not mint owl:Class from thoughts or markdown.
"""

from __future__ import annotations

from pathlib import Path

GURU_MISSING = (
    "#THETA.00000004.ONTOLOGY_MISSING HermiT-certified sdg-ontology.owl is not in this checkout.\n"
    "  Try: git submodule update --init external/sdg-corpora"
)

_REPO = Path(__file__).resolve().parents[4]
CERTIFIED_OWL = _REPO / "external" / "sdg-corpora" / "ontology" / "sdg-ontology.owl"


def certified_ontology_path() -> Path:
    """Path to the HermiT-certified SDG OWL. Fail if the corpora pin is absent."""
    if not CERTIFIED_OWL.is_file():
        raise FileNotFoundError(GURU_MISSING)
    return CERTIFIED_OWL
