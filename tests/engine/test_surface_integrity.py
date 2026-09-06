"""The surface_integrity card's examples are specimens the evaluator must
resolve identically (sdg-strategy objective-pillar shape, 2026-09-06)."""

import json
from pathlib import Path

import pytest

from gaius.engine.services.surface_integrity import ASPECT, GATES, REMOVAL_REASONS, evaluate

CARD = Path(__file__).resolve().parents[2] / "config" / "supervision" / "objectives" / "surface-integrity.json"


def _card() -> dict:
    return json.loads(CARD.read_text(encoding="utf-8"))


def _examples():
    card = _card()
    return [pytest.param(card["params"], ex, id=ex["name"][:40]) for ex in card["examples"]]


@pytest.mark.parametrize("params,example", _examples())
def test_card_examples_resolve_identically(params: dict, example: dict) -> None:
    p = {**params, **example.get("params", {})}
    gates = {g["gate"]: g for g in evaluate(example["input"], p)}
    assert set(gates) == set(GATES), sorted(gates)
    expected = example["output"]["gates"]
    got = {k: v["verdict"] for k, v in gates.items()}
    assert got == expected, {k: (got[k], expected[k], gates[k]["evidence"][:120]) for k in GATES if got[k] != expected[k]}
    for g in gates.values():
        assert g["aspect"] == ASPECT[g["gate"]]
        assert g["verdict"] in ("pass", "fail", "error")  # never inconclusive
        assert g["evidence"]


def test_every_gate_has_an_aspect_and_the_card_lists_all_gates() -> None:
    assert set(ASPECT) == set(GATES)
    md = (CARD.with_suffix(".md")).read_text(encoding="utf-8")
    for g in GATES:
        assert f"`{g}`" in md, f"{g} not documented in the card"
    for cat in REMOVAL_REASONS:
        assert cat in md


def test_fail_evidence_names_a_stage() -> None:
    card = _card()
    ex = next(e for e in card["examples"] if e["name"].startswith("C"))
    gates = {g["gate"]: g for g in evaluate(ex["input"], {**card["params"], **ex["params"]})}
    assert "DAG stage" in gates["no_marketing_shapes"]["evidence"]
    assert "answerthis" in gates["no_marketing_shapes"]["evidence"].lower() or "v3" in gates["no_marketing_shapes"]["evidence"]
