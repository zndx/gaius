"""Cognition buffer is a merge scratchpad; SDG schema drives compaction."""

from __future__ import annotations

from pathlib import Path

import pytest

from gaius.engine.services.cognition_buffer import (
    DEFAULT_SCRATCH_TOKEN_BUDGET,
    NEXT_QUESTION_RESERVE_TOKENS,
    THINKING_CONTEXT_TOKENS,
    AttentionSchema,
    CognitionBuffer,
    DecisionSituation,
)
from gaius.engine.services.sdg_aperture import (
    DEFAULT_SDG_STRATEGY,
    ApertureAnchor,
    SdgAperture,
)
from gaius.engine.services.sdg_catalog import (
    DEFAULT_SDG_CORPORA,
    SdgCatalog,
    SdgConcept,
)

_ICE = SdgConcept(
    code="SDG.ICE",
    label="Information Content Entity",
    notation="3.0",
    parent_code="SDG.GDC",
    description="about something",
)


def _schema() -> AttentionSchema:
    catalog = SdgCatalog(
        {"SDG.ICE": _ICE},
        root=Path("/tmp/sdg-corpora-fixture"),
    )
    aperture = SdgAperture(
        strategy_id="teststrategy",
        collection="sdg_aperture",
        regime="threshold",
        tau=0.1,
        window_chars=4000,
        colbert_token_limit=512,
        anchors=(
            ApertureAnchor(
                iri="https://signals.zndx.org/sdg#LIMS",
                label="Laboratory Information Management",
                vector_sha="deadbeef",
                local_name="LIMS",
            ),
        ),
        root=Path("/tmp/sdg-strategy-fixture"),
    )
    return AttentionSchema(catalog, aperture)


def test_budget_rejects_eating_the_next_question_reserve() -> None:
    with pytest.raises(ValueError, match="one next question"):
        CognitionBuffer(_schema(), token_budget=THINKING_CONTEXT_TOKENS)
    with pytest.raises(ValueError, match="one next question"):
        CognitionBuffer(
            _schema(),
            token_budget=DEFAULT_SCRATCH_TOKEN_BUDGET + 1,
        )
    buf = CognitionBuffer(_schema())
    assert buf.token_budget + buf.reserve_tokens == THINKING_CONTEXT_TOKENS
    assert buf.reserve_tokens == NEXT_QUESTION_RESERVE_TOKENS


def test_succinct_is_keep_score_not_the_full_scratchpad() -> None:
    buf = CognitionBuffer(_schema(), token_budget=4000)
    buf.merge("ambient", "hn", "rustc nightly thread " * 20, role="hn", ts=1.0)
    buf.merge(
        "prospects",
        "slb",
        "SLB 10-K liquidity covenant " * 20,
        role="fmp",
        ts=2.0,
        code="SDG.ICE",
        margin=0.40,
        admitted=True,
    )
    rows = buf.succinct(max_items=4, excerpt=80)
    assert rows
    assert rows[0]["flag"] == "ADMIT"
    assert rows[0]["stream"] == "prospects"
    assert "SLB" in rows[0]["excerpt"]
    assert len(rows[0]["excerpt"]) <= 80
    assembled = buf.assemble()
    assert "rustc nightly" in assembled
    assert assembled != rows[0]["excerpt"]


def test_merge_keeps_full_content() -> None:
    buf = CognitionBuffer(_schema(), token_budget=4000)
    body = "liquidity covenant " * 40
    buf.merge("prospects", "e1", body, role="fmp")
    got = buf.get("e1")
    assert got is not None
    assert got.content == body
    text = buf.assemble()
    assert text.startswith("# Cognition scratchpad")
    assert body in text
    assert "## Situation" in text
    assert "## Scratchpad" in text
    assert "## Attention" in text
    assert "where: —" in text
    assert "purpose=one-next-question" in text
    assert "reserve=" in text


def test_compact_prefers_schema_over_fifo() -> None:
    """Old admitted+coded beats new untyped when only one fits."""
    buf = CognitionBuffer(_schema(), token_budget=80)
    buf.merge("prospects", "old", "x" * 160, ts=1.0)
    buf.record_attention(
        "old",
        code="SDG.ICE",
        margin=0.40,
        admitted=True,
    )
    buf.merge("ambient", "new", "y" * 160, ts=9.0)
    assert buf.get("old") is not None
    assert buf.get("new") is None


def test_unknown_code_fail_fast() -> None:
    buf = CognitionBuffer(_schema(), token_budget=400)
    buf.merge("prospects", "e1", "note")
    with pytest.raises(ValueError, match="UNKCODE"):
        buf.record_attention("e1", code="NOT.A.CODE", admitted=True)


def test_aperture_token_resolves() -> None:
    buf = CognitionBuffer(_schema(), token_budget=400)
    buf.merge("prospects", "e1", "specimen accession")
    rec = buf.record_attention(
        "e1",
        code="LIMS",
        margin=0.22,
        admitted=True,
    )
    assert rec.sdg_code == "https://signals.zndx.org/sdg#LIMS"


def test_annotate_before_merge_fails() -> None:
    buf = CognitionBuffer(_schema(), token_budget=400)
    with pytest.raises(KeyError, match="NOENTRY"):
        buf.record_attention("missing", code="SDG.ICE")


def test_situation_biases_compact_toward_the_open_decision() -> None:
    """Equal admits: keep the one that could inform the situated move."""
    buf = CognitionBuffer(_schema(), token_budget=80)
    buf.situate(
        DecisionSituation(
            where="SLB filing",
            doing="prospects review",
            decide="keep or drop SLB",
        )
    )
    buf.merge(
        "prospects",
        "slb",
        "SLB 10-K liquidity " + "x" * 120,
        ts=1.0,
        code="SDG.ICE",
        margin=0.30,
        admitted=True,
    )
    buf.merge(
        "ambient",
        "hn",
        "rustc nightly thread " + "y" * 120,
        ts=2.0,
        code="SDG.ICE",
        margin=0.30,
        admitted=True,
    )
    assert buf.get("slb") is not None
    assert buf.get("hn") is None
    text = buf.assemble()
    assert "where: SLB filing" in text
    assert "decide: keep or drop SLB" in text


def test_review_survives_budget() -> None:
    buf = CognitionBuffer(_schema(), token_budget=80)
    buf.merge("prospects", "flag", "r" * 160, ts=1.0)
    buf.record_attention(
        "flag",
        review=True,
        review_reason="root hit, no genus",
    )
    buf.merge("ambient", "noise", "n" * 160, ts=2.0)
    assert [e.source_id for e in buf.review_worklist()] == ["flag"]


def test_live_sdg_submodules_load() -> None:
    if not (DEFAULT_SDG_CORPORA / "vocabulary" / "annotations.csv").is_file():
        pytest.skip("external/sdg-corpora not initialized")
    if not (DEFAULT_SDG_STRATEGY / "CURRENT").is_file():
        pytest.skip("external/sdg-strategy not initialized")
    schema = AttentionSchema.load()
    assert "SDG.ARTIFACT" in schema.catalog
    assert schema.aperture.regime == "threshold"
    assert schema.aperture.tau == 0.1
    assert schema.aperture.colbert_token_limit == 512
    assert schema.aperture.n == 33
    assert schema.aperture.resolve("LIMS") is not None
    schema.resolve("SDG.ARTIFACT")
    schema.resolve("LIMS")


def test_parse_agenda_payload_from_tagged_completion() -> None:
    from gaius.engine.services.cognition_synthesis import parse_agenda_payload, synthesis_body

    text = """SYNTHESIS:
HN is covering GPU power; two cards landed on the site.

AGENDA:
{"briefs":[{"title":"GPU power narrative","body":"Keep analog honest"}],"reminders":[{"title":"DROP 496550","body":"after Iceberg verify","due_at":null}],"sessions":[{"title":"Agenda agent","body":"wire provenance"}]}
"""
    data = parse_agenda_payload(text)
    assert data["briefs"][0]["title"] == "GPU power narrative"
    assert "HN is covering" in synthesis_body(text)
