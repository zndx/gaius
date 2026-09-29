"""Week understanding is an investigation the loop can carry, not a pair counter."""

from __future__ import annotations

import pytest


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


def test_daily_loop_reads_the_carry_and_not_the_well() -> None:
    from gaius.engine.services.theta_understanding import consolidation_prompt_section

    carry = (
        "KNOWN: Restart survival is a settled frame.\n"
        "STOP: Do not ask what survives a restart without a selection rule.\n"
        "OPEN: Which states are recomputable is still unresolved."
    )
    section = consolidation_prompt_section(
        {
            "slice_id": "2026-W39",
            "summary": carry,
            "content": "WELL_ONLY the investigation itself " + ("x" * 800),
        }
    )
    assert section.startswith("\n\nWEEK CONSOLIDATION (2026-W39)")
    assert "selection rule" in section
    assert "WELL_ONLY" not in section
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


def test_latest_week_is_the_iso_slice_not_when_it_landed() -> None:
    """A later landing of an earlier week does not become the week in force."""
    from datetime import datetime, timezone

    from gaius.engine.services.theta_understanding import (
        choose_latest_consolidation,
        current_iso_slice,
    )

    landed_late = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    landed_early = datetime(2026, 9, 29, 1, 31, tzinfo=timezone.utc)
    rows = [
        {
            "title": "W38 backfill",
            "slice_id": "2026-W38",
            "created_at": landed_late,
            "content": "earlier week",
        },
        {
            "title": "W39 in force",
            "slice_id": "2026-W39",
            "created_at": landed_early,
            "content": "later week",
        },
        {
            "title": "not yet",
            "slice_id": "2026-W41",
            "created_at": datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc),
            "content": "future",
        },
        {"title": "no week", "slice_id": "", "created_at": landed_late, "content": "x"},
    ]
    chosen = choose_latest_consolidation(rows, "2026-W40")
    assert chosen is not None
    assert chosen["slice_id"] == "2026-W39"
    assert choose_latest_consolidation(rows, "2026-W38")["title"] == "W38 backfill"
    assert choose_latest_consolidation([rows[2]], "2026-W40") is None
    assert choose_latest_consolidation(rows, "") is None

    revised = choose_latest_consolidation(
        [
            {"title": "first", "slice_id": "2026-W39", "created_at": landed_early},
            {"title": "revised", "slice_id": "2026-W39", "created_at": landed_late},
        ],
        "2026-W40",
    )
    assert revised["title"] == "revised"

    # Year boundary is still string order because weeks are zero-padded.
    boundary = choose_latest_consolidation(
        [
            {"title": "old year", "slice_id": "2026-W53", "created_at": landed_late},
            {"title": "new year", "slice_id": "2027-W01", "created_at": landed_early},
        ],
        "2027-W01",
    )
    assert boundary["title"] == "new year"
    assert current_iso_slice(datetime(2026, 9, 29, tzinfo=timezone.utc)) == "2026-W40"
    assert current_iso_slice(datetime(2026, 9, 14, tzinfo=timezone.utc)) == "2026-W38"
