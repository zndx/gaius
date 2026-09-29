"""Week understanding is a held draft, not a pair counter."""

from __future__ import annotations

import pytest


def _thoughts() -> list[dict]:
    return [
        {
            "title": "Durable state is the control plane",
            "summary": "What survives a restart is the control plane.",
            "thought_type": "pattern",
            "salience": 0.97,
            "n": 12,
        },
        {
            "title": "Memory is selection pressure",
            "summary": "Kept thoughts are the ones that get restated.",
            "thought_type": "connection",
            "salience": 0.4,
            "n": 2,
        },
    ]


def _bindings() -> list[tuple[str, int]]:
    return [("DataInput", 43), ("MachineLearningModel", 42), ("GenomicData", 19)]


def _held_body() -> str:
    carry = (
        "Next cycles should treat durable state as already settled and ask "
        "what the week's admitted work actually was."
    )
    stop = "Do not publish durable state is the control plane again."
    aperture = (
        "Admitted items grounded to DataInput and MachineLearningModel, "
        "which the loop never discussed."
    )
    summary = (
        "The week established that the cognition loop restated one control-plane "
        "thought while admissions grounded elsewhere."
    )
    return "\n".join(
        [
            "TITLE: The loop echoed; the corpus did not",
            f"SUMMARY: {summary}",
            f"CARRY_FORWARD: {carry}",
            f"STOP_REPEATING: {stop}",
            f"APERTURE: {aperture}",
        ]
    )


def test_histogram_keeps_named_classes_not_opaque_iris() -> None:
    from gaius.engine.services.theta_understanding import binding_histogram

    groundings = [
        {
            "classes": [
                ["https://example.org/BFO_0000034", 0.9],
                ["https://example.org/sdg#DataInput", 0.8],
            ]
        },
        {
            "classes": [
                ["https://www.commoncoreontologies.org/ont00001180", 0.9],
                ["https://example.org/sdg#DataInput", 0.7],
            ]
        },
    ]
    labels = [label for label, _n in binding_histogram(groundings)]
    assert labels == ["DataInput"]


def test_collapse_counts_restatement_and_skips_a_prior_consolidation() -> None:
    from gaius.engine.services.theta_understanding import collapse_thoughts

    rows = [
        {"title": "Durable state is the control plane", "summary": "a", "salience": 0.9, "thought_type": "pattern"},
        {"title": "Durable state is the control plane", "summary": "b", "salience": 0.95, "thought_type": "pattern"},
        {"title": "Already written", "summary": "week", "salience": 0.9, "thought_type": "consolidation"},
        {"title": "Memory is selection pressure", "content": "kept", "salience": 0.2, "thought_type": "curiosity"},
    ]
    collapsed = collapse_thoughts(rows)
    assert collapsed[0]["title"] == "Durable state is the control plane"
    assert collapsed[0]["n"] == 2
    assert all(row["title"] != "Already written" for row in collapsed)


def test_prompt_forbids_minting_a_subclass() -> None:
    from gaius.engine.services.theta_understanding import SYSTEM_PROMPT, consolidation_prompt

    prompt = consolidation_prompt("2026-W39", _thoughts(), _bindings())
    assert "Do not mint" in SYSTEM_PROMPT
    assert "subclass" in SYSTEM_PROMPT
    assert "DataInput (43)" in prompt
    assert "(12×) Durable state is the control plane" in prompt
    assert "APERTURE:" in prompt


def test_generic_essay_does_not_hold() -> None:
    from gaius.engine.services.theta_understanding import parse_consolidation, understanding_holds

    essay = "\n".join(
        [
            "TITLE: A productive week",
            "SUMMARY: " + ("Many things happened across the knowledge base. " * 8),
            "CARRY_FORWARD: " + ("Continue the good work in the next cycle and beyond. " * 4),
            "STOP_REPEATING: Do not repeat vague encouragement to the team.",
            "APERTURE: The corpus was broadly relevant to operations this week.",
        ]
    )
    draft = parse_consolidation(essay)
    assert draft is not None
    assert understanding_holds(draft, _thoughts(), _bindings()) is False


def test_cited_draft_holds_and_a_subclass_claim_does_not() -> None:
    from gaius.engine.services.theta_understanding import parse_consolidation, understanding_holds

    draft = parse_consolidation(_held_body())
    assert draft is not None
    assert understanding_holds(draft, _thoughts(), _bindings()) is True

    claimed = _held_body().replace(
        "which the loop never discussed.",
        "DataInput is a subclass of the control plane.",
    )
    assert understanding_holds(parse_consolidation(claimed), _thoughts(), _bindings()) is False

    denied = _held_body().replace(
        "which the loop never discussed.",
        "These labels do not assert subclass or subsumption.",
    )
    assert understanding_holds(parse_consolidation(denied), _thoughts(), _bindings()) is True


def test_prompt_section_carries_stop_repeating() -> None:
    from gaius.engine.services.theta_understanding import (
        consolidation_prompt_section,
        parse_consolidation,
    )

    draft = parse_consolidation(_held_body())
    assert draft is not None
    section = consolidation_prompt_section({"slice_id": "2026-W39", **draft})
    assert section.startswith("\n\nWEEK CONSOLIDATION (2026-W39)")
    assert "STOP_REPEATING" in section
    assert "Do not re-derive" in section


@pytest.mark.asyncio
async def test_a_day_that_does_not_close_the_week_is_not_rewritten() -> None:
    from gaius.engine.services.theta_understanding import attach_week_understanding

    out = await attach_week_understanding(
        "postgresql://unused",
        "2026-W39",
        "2026-09-21",
        {"success": True, "metadata": {"windows": ["2026-09-21"]}},
    )
    assert out["success"] is True
    assert "consolidation_thought_id" not in out


@pytest.mark.asyncio
async def test_nopairs_is_not_turned_into_an_understanding() -> None:
    from gaius.engine.services.theta_understanding import attach_week_understanding

    out = await attach_week_understanding(
        "postgresql://unused",
        "2026-W39",
        "",
        {
            "success": False,
            "error": "#THETA.00000011.NOPAIRS no novel pairs",
            "guru_code": "#THETA.00000011.NOPAIRS",
        },
    )
    assert out["success"] is False
    assert "NOPAIRS" in out["error"]
    assert "consolidation_thought_id" not in out
