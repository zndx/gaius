"""BDD-backed agenda densities — features/cognition/agenda.feature."""

from datetime import datetime, timezone

from gaius.engine.services.agenda_policy import (
    DEFAULT_DENSITY,
    clip_reminder_list,
    contains_packed_guru,
    next_session_slots,
    session_invite_description,
    slots_remaining,
    strip_packed_guru,
    take_kind,
)


def test_session_density_few_times_a_week() -> None:
    slots = slots_remaining({"session": 0, "brief": 0, "reminder": 0})
    assert slots["session"] == DEFAULT_DENSITY.sessions_per_week
    assert slots["session"] <= 3
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    dues = next_session_slots(now, [], per_week=3)
    assert len(dues) == 3
    days = sorted({d.date() for d in dues})
    assert len(days) == 3


def test_session_invite_has_terminal_paste_block() -> None:
    text = session_invite_description(
        title="Aperture world events",
        body="seL4 proofs vs makers; unique MaxSim DATAENG window.",
        episode_id="ep-1",
        hx_generation_id="hx-9",
        due_at=datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc),
    )
    assert "BEGIN SESSION" in text
    assert "END SESSION" in text
    assert "episode=ep-1" in text
    assert "Aperture" in text
    assert "unique MaxSim" in text


def test_reminder_is_short_list() -> None:
    body = clip_reminder_list(
        "- analog 496554\n- DROP RANGE PARTITION VALUE = 496554\n"
        "- discretionary: inspect starve\n- extra1\n- extra2\n- extra3",
        5,
    )
    lines = [ln for ln in body.splitlines() if ln.startswith("- ")]
    assert 1 <= len(lines) <= 5
    assert "DROP RANGE" in body


def test_search_guru_finds_unique_code_in_repo() -> None:
    from gaius.engine.services.cognition_synthesis import (
        parse_guru_searches,
        search_guru_in_repo,
    )

    reqs = parse_guru_searches("SEARCH_GURU #EN.00000031.FDWINGEST\n")
    assert reqs == ["EN.00000031.FDWINGEST"]
    hit = search_guru_in_repo("EN.00000031.FDWINGEST")
    assert "EN.00000031.FDWINGEST" in hit
    assert "no references" not in hit


def test_brief_slot_and_operational_specifics() -> None:
    slots = slots_remaining({"brief": 4})
    assert slots["brief"] == 1
    packed = (
        "Closed hour expired on Kudu after Iceberg analog. "
        "Thinking vLLM was down during recycle. "
        "guru #EN.00000031.FDWINGEST #AMB.00000014.NOHEALTHY"
    )
    assert contains_packed_guru(packed)
    cleaned = strip_packed_guru(packed)
    assert not contains_packed_guru(cleaned)
    assert "Iceberg analog" in cleaned
    assert "Thinking vLLM" in cleaned
    taken = take_kind(
        [{"title": "Warehouse", "body": cleaned}],
        kind="brief",
        slots=1,
    )
    assert "DROP RANGE" not in packed or "Iceberg" in taken[0]["body"]
    assert slots_remaining({"brief": 5})["brief"] == 0
