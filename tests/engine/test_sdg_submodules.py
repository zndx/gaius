"""Local sdg-corpora / sdg-strategy pins fail fast when missing."""

from __future__ import annotations

from pathlib import Path

import pytest

from gaius.engine.services.sdg_aperture import SdgAperture
from gaius.engine.services.sdg_catalog import SdgCatalog


def test_missing_corpora_fail_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="NOCORPORA"):
        SdgCatalog.load(tmp_path)


def test_missing_strategy_fail_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="NOSTRATEGY"):
        SdgAperture.load(tmp_path)


def test_live_catalog_has_skos_codes() -> None:
    try:
        catalog = SdgCatalog.load()
    except FileNotFoundError:
        pytest.skip("external/sdg-corpora not initialized")
    assert len(catalog) > 100
    assert catalog.require("SDG.ARTIFACT").label == "Artifact"


def test_live_aperture_matches_strategy_spec() -> None:
    try:
        aperture = SdgAperture.load()
    except FileNotFoundError:
        pytest.skip("external/sdg-strategy not initialized")
    assert aperture.strategy_id
    assert aperture.collection == "sdg_aperture"
    assert aperture.n == 33
    assert aperture.tau == 0.1
    lims = aperture.resolve("LIMS")
    assert lims is not None
    assert lims.iri.endswith("#LIMS")
