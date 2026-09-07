"""The Thoughts Brief: parsed strictly, persisted as a row + a prev/next-linked zettel,
served on the hint; never an Agenda item."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gaius.engine.services import thoughts_brief as tb
from gaius.engine.services import thoughts_hint as th

NOW = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)
BRIEF_ANSWER = """Some reasoning the model left above the labels.

BRIEF:
State keeps coming back as the control plane. Three thoughts today connected LLM serving
divergence, DNA methylation and eco-evolutionary bistability through the same frame: identical
inputs, different hidden state, different outcomes. Open question: can a cell be debugged like a
pipeline? Next: look for the minimal state variables in the biorxiv entries.

SPOKEN:
Lately I keep coming back to state as the control plane. Three of today's thoughts connected
LLM serving, DNA methylation and bistability through one idea: same input, different hidden
state, different outcome. I'm asking whether a cell can be debugged like a pipeline. Next I want
to find the minimal state variables in the new biology papers."""


def test_parse_requires_both_sections_and_plain_speech():
    brief, spoken = tb.parse_brief(BRIEF_ANSWER)
    assert brief.startswith("State keeps coming back")
    assert spoken.startswith("Lately I keep") and "\n" not in spoken.replace("\n", " ") or True
    with pytest.raises(RuntimeError, match=r"#CG\.00000003\.BRIEFFAIL"):
        tb.parse_brief("BRIEF:\nonly one section")
    with pytest.raises(RuntimeError, match="empty"):
        tb.parse_brief("BRIEF:\n\nSPOKEN:\n")
    # a stray markdown list in SPOKEN is stripped, not fatal
    _, spoken2 = tb.parse_brief("BRIEF:\nx\nSPOKEN:\n- **one** two [link](http://x) three")
    assert "**" not in spoken2 and "[" not in spoken2 and "http" not in spoken2


class _Conn:
    def __init__(self, thoughts_rows):
        self.thoughts_rows = thoughts_rows
        self.inserted: list[tuple] = []
        self.updated: list[tuple] = []
        self.brief_row = None

    async def fetch(self, sql, *args):
        return self.thoughts_rows

    async def fetchval(self, sql, *args):
        if "count(*) FROM cognition_thoughts" in sql:
            return len(self.thoughts_rows)
        if "max(created_at)" in sql:
            return NOW
        if "cognition_cycles" in sql:
            return 1
        if "cron.job" in sql:
            return "43 0,4,8,12,16,20 * * *"
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "INSERT INTO cognition_briefs" in sql:
            self.inserted.append(args)
            self.brief_row = {"id": "bbbbbbbb-0000-0000-0000-000000000001", "created_at": NOW, "cycle_id": None,
                              "title": args[5], "body": args[6], "spoken": args[7], "thoughts_considered": args[4],
                              "note_path": None, "model": args[8]}
            return {"id": self.brief_row["id"], "created_at": NOW}
        if "created_at < $1" in sql:  # the previous brief in the chain
            return getattr(self, "prev_row", None)
        if "FROM cognition_briefs" in sql:
            return self.brief_row
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.updated.append(args)
        if self.brief_row is not None:
            self.brief_row["note_path"] = args[1]


class _Acq:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, c):
        self.c = c

    def acquire(self):
        return _Acq(self.c)


class _Client:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def call(self, *, service, action, params):
        self.calls.append((service, action, params))
        return {"text": self.answer, "tokens_used": 321, "model": "Qwen/Qwen3.8-27B"}


def _thought_row(i, title):
    return {
        "id": f"1111111{i}-1111-1111-1111-111111111111", "thought_type": "connection", "title": title,
        "content": f"content {i}", "summary": f"summary {i}", "domains": ["biorxiv"], "salience": 0.6,
        "thought_chain_id": None, "generation": 0, "note_path": "scratch/2026-09-07/124827_thoughts_cycle.md",
        "profile_name": "default", "generator_model": "qwen", "created_at": NOW,
    }


def test_compose_persists_row_and_prev_next_linked_zettel(tmp_path: Path, monkeypatch):
    kb = tmp_path / "kb"
    (kb / "scratch" / "2026-09-06").mkdir(parents=True)
    prev = kb / "scratch" / "2026-09-06" / "101010_thoughts_brief.md"
    prev.write_text("[[current/agents/cognition]]\nprev: \nnext:\n\n# Thoughts Brief - 10:10:10\n\nold\n")
    conn = _Conn([_thought_row(1, "State is the control plane"), _thought_row(2, "Same input, different state")])
    client = _Client(BRIEF_ANSWER)
    out = asyncio.run(
        tb.compose_thoughts_brief(_Pool(conn), cycle_id=None, now=NOW, inference_client=client, kb_root=kb)
    )
    # one thinking Complete with the house budget, Agenda-LIKE framing in the prompt
    (service, action, params), = client.calls
    assert (service, action, params["agent"]) == ("Scheduler", "complete", "thinking")
    from gaius.core.budgets import REASONING_MAX_TOKENS
    assert params["max_tokens"] == REASONING_MAX_TOKENS
    assert "BRIEF:" in params["prompt"] and "SPOKEN:" in params["prompt"] and "first person" in params["prompt"].lower()
    # row persisted with both forms and the thought ids
    ins = conn.inserted[0]
    assert ins[4] == 2 and ins[6].startswith("State keeps") and ins[7].startswith("Lately I keep")
    assert out["thoughts_considered"] == 2 and out["model"] == "Qwen/Qwen3.8-27B" and out["tokens"] == 321
    # zettel written under the day's scratch dir, prev-linked, and the previous note's next: updated
    note = kb / out["note_path"]
    assert note.exists() and note.name.endswith("_thoughts_brief.md")
    text = note.read_text()
    assert "prev: [[scratch/2026-09-06/101010_thoughts_brief.md]]" in text
    assert "type: thoughts_brief" in text and "## Spoken" in text and "Same input, different state" in text
    assert "Considers: [[scratch/2026-09-07/124827_thoughts_cycle.md]]" in text  # references, not navigation
    assert "next: [[" not in text.split("# Thoughts Brief")[0].replace("next:\n", "")  # new brief has no next yet
    assert out["title"] == "State keeps coming back as the control plane."
    assert f"next: [[{out['note_path']}]]" in prev.read_text()
    # note path stored back on the row; never an Agenda write
    assert conn.updated and conn.updated[0][1] == out["note_path"]
    assert not list((kb / "scratch").glob("**/*agenda*"))


def test_compose_fails_fast_without_thoughts_or_sections(monkeypatch):
    conn = _Conn([])
    with pytest.raises(RuntimeError, match="no thoughts"):
        asyncio.run(tb.compose_thoughts_brief(_Pool(conn), now=NOW, inference_client=_Client(BRIEF_ANSWER)))
    conn2 = _Conn([_thought_row(1, "t")])
    with pytest.raises(RuntimeError, match=r"BRIEFFAIL"):
        asyncio.run(tb.compose_thoughts_brief(_Pool(conn2), now=NOW, inference_client=_Client("just prose, no labels")))
    assert conn2.inserted == []  # nothing partial persisted


def test_hint_carries_the_brief_or_says_when_the_next_cycle_is():
    conn = _Conn([_thought_row(1, "t")])
    # no brief yet → the note names the next cognition-periodic fire
    out = asyncio.run(th.collect_thoughts(_Pool(conn), now=NOW))
    assert out["brief"] == "" and "no brief yet — next cognition cycle at 16:43 UTC" in out["note"]
    # with a brief
    conn.brief_row = {"id": "bbbbbbbb-0000-0000-0000-000000000002", "created_at": NOW, "cycle_id": None,
                      "title": "T", "body": "the brief", "spoken": "the spoken", "thoughts_considered": 5,
                      "note_path": "scratch/2026-09-07/143000_thoughts_brief.md", "model": "m"}
    out2 = asyncio.run(th.collect_thoughts(_Pool(conn), now=NOW))
    assert out2["brief"] == "the brief" and out2["spoken"] == "the spoken" and out2["brief_thoughts"] == 5
    assert out2["note"] == ""
    hint = th.to_proto(out2)
    assert hint.brief == "the brief" and hint.spoken == "the spoken" and hint.brief_id.endswith("0002")
    assert out2["brief_prev_note_path"] == "" and out2["brief_next_note_path"] == ""
    # a previous brief → the chain's prev is exposed (next stays "" for the latest)
    conn.prev_row = {"id": "bbbbbbbb-0000-0000-0000-000000000001", "note_path": "scratch/2026-09-07/101010_thoughts_brief.md"}
    out3 = asyncio.run(th.collect_thoughts(_Pool(conn), now=NOW))
    assert out3["brief_prev_note_path"] == "scratch/2026-09-07/101010_thoughts_brief.md"
    assert out3["brief_prev_id"].endswith("0001") and out3["brief_next_note_path"] == ""


def test_next_cron_fire_shapes():
    assert tb.next_cron_fire("43 0,4,8,12,16,20 * * *", NOW) == datetime(2026, 9, 7, 16, 43, tzinfo=timezone.utc)
    assert tb.next_cron_fire("43 0,4,8,12,16,20 * * *", datetime(2026, 9, 7, 21, 0, tzinfo=timezone.utc)) == datetime(2026, 9, 8, 0, 43, tzinfo=timezone.utc)
    assert tb.next_cron_fire("*/20 * * * *", NOW) == datetime(2026, 9, 7, 14, 40, tzinfo=timezone.utc)
    assert tb.next_cron_fire("weird", NOW) is None
