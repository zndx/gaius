"""Cognition writes Brief / List / Session onto the /agenda zettel store."""

from __future__ import annotations

from pathlib import Path

import pytest

from gaius.engine.services.agenda_notes import AgendaError, list_items
from gaius.engine.services.cognition_synthesis import (
    SYNTH_PROMPT,
    insert_agenda,
)


class _Conn:
    def __init__(self) -> None:
        self.inserted: list[tuple] = []

    async def fetch(self, _sql: str, *_args: object) -> list:
        return []

    async def execute(self, _sql: str, *args: object) -> str:
        self.inserted.append(args)
        return "INSERT 0 1"


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


@pytest.mark.asyncio
async def test_insert_agenda_writes_letter_list_and_catchup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    monkeypatch.setenv("GAIUS_KB_ROOT", str(kb))
    conn = _Conn()
    n = await insert_agenda(
        _Pool(conn),
        "ep-1",
        "hx-1",
        {
            "briefs": [
                {
                    "title": "Warehouse honesty",
                    "body": (
                        "The analog of the closed hour is on Iceberg. "
                        "guru #EN.00000031.FDWINGEST"
                    ),
                }
            ],
            "reminders": [
                {
                    "title": "Expire closed hour",
                    "body": (
                        "- analog 496554\n"
                        "- DROP RANGE PARTITION VALUE = 496554"
                    ),
                }
            ],
            "sessions": [
                {
                    "title": "Aperture world events",
                    "body": "seL4 proofs vs makers; unique MaxSim DATAENG window",
                }
            ],
        },
    )
    assert n == 3
    items = list_items(kb, window_days=14)
    by_intent = {i.intent: i for i in items}
    assert by_intent["brief"].kind == "note"
    assert "Iceberg" in by_intent["brief"].body
    assert "EN.00000031" not in by_intent["brief"].body
    assert by_intent["reminder"].kind == "list"
    assert "- [ ]" in by_intent["reminder"].body
    assert "DROP RANGE" in by_intent["reminder"].body
    assert by_intent["session"].kind == "event"
    assert by_intent["session"].starts
    assert "Catch-up with a colleague" in by_intent["session"].body
    assert "Discussion headlines" in by_intent["session"].body
    assert "BEGIN SESSION" in by_intent["session"].body
    assert "unique MaxSim" in by_intent["session"].body


@pytest.mark.asyncio
async def test_insert_agenda_fails_fast_without_kb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAIUS_KB_ROOT", str(tmp_path / "missing"))
    with pytest.raises(AgendaError, match="AG.00000001"):
        await insert_agenda(
            _Pool(_Conn()),
            "ep-1",
            "hx-1",
            {"briefs": [], "reminders": [], "sessions": []},
        )


def test_synth_prompt_names_letter_list_catchup_genres() -> None:
    assert "letter or memo" in SYNTH_PROMPT
    assert "natural-register" in SYNTH_PROMPT
    assert "helpful suggestions" in SYNTH_PROMPT
    assert "catch up with a colleague" in SYNTH_PROMPT
    assert "discussion headlines" in SYNTH_PROMPT.lower()
    assert "Do NOT pack guru" in SYNTH_PROMPT
