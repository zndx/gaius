"""ServerQuery kind=THOUGHTS — the newest persisted thoughts as content, honestly."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from gaius.engine.services import thoughts_hint as th


class _Conn:
    def __init__(self, rows, newest, total=None, cycles=3):
        self.rows, self.newest, self.total, self.cycles = rows, newest, total, cycles
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", args))
        return self.rows

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", args))
        if "count(*) FROM cognition_thoughts" in sql:
            return self.total if self.total is not None else len(self.rows)
        if "max(created_at)" in sql:
            return self.newest
        if "cognition_cycles" in sql:
            return self.cycles
        if "cron.job" in sql:
            return "43 0,4,8,12,16,20 * * *"
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        assert "FROM cognition_briefs" in sql, sql
        return None  # no brief yet in these tests


class _Acq:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acq(self.conn)


def _row(**kw):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "thought_type": "connection",
        "title": "State as the control plane",
        "content": "x" * 1500,
        "summary": "If state is the control plane, cells are debuggable.",
        "domains": ["biorxiv", "data-engineering"],
        "salience": 0.7,
        "thought_chain_id": "22222222-2222-2222-2222-222222222222",
        "generation": 1,
        "note_path": "scratch/2026-09-07/thoughts.md",
        "profile_name": "default",
        "generator_model": "qwen3.8-27b",
        "created_at": datetime(2026, 9, 7, 12, 48, tzinfo=timezone.utc),
    }
    base.update(kw)
    return base


def test_collect_bounds_text_and_reports_totals():
    now = datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)
    conn = _Conn([_row()], newest=datetime(2026, 9, 7, 12, 48, tzinfo=timezone.utc), total=9)
    out = asyncio.run(th.collect_thoughts(_Pool(conn), limit=50, since_ms=0, stream="Connection", now=now))
    assert out["project"] == "gaius"
    assert out["total_in_window"] == 9 and out["cycles_in_window"] == 3
    assert out["newest_ms"] == int(datetime(2026, 9, 7, 12, 48, tzinfo=timezone.utc).timestamp() * 1000)
    assert out["note"].startswith("no brief yet — next cognition cycle at")  # fresh thoughts, no brief yet
    t = out["thoughts"][0]
    assert t["kind"] == "connection" and t["title"].startswith("State as")
    assert len(t["excerpt"]) <= th.EXCERPT_CHARS and t["excerpt"].endswith("…")
    assert t["domains"] == ["biorxiv", "data-engineering"] and t["chain_id"].endswith("2222")
    # limit capped, filter lowercased, default 7-day window
    fetch_args = [a for k, a in conn.calls if k == "fetch"][0]
    assert fetch_args[1] == "connection" and fetch_args[2] == th.MAX_LIMIT
    assert fetch_args[0] == now - th.DEFAULT_WINDOW
    assert out["window_ms"] == int(th.DEFAULT_WINDOW.total_seconds() * 1000)


def test_idle_and_empty_are_said_plainly():
    now = datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)
    stale = _Conn([], newest=now - timedelta(hours=40), total=0)
    out = asyncio.run(th.collect_thoughts(_Pool(stale), now=now))
    assert out["thoughts"] == [] and "idle" in out["note"] and "40 h" in out["note"] and "no brief yet" in out["note"]
    empty = _Conn([], newest=None, total=0)
    out2 = asyncio.run(th.collect_thoughts(_Pool(empty), now=now))
    assert "store empty" in out2["note"]
    out3 = asyncio.run(th.collect_thoughts(None, now=now))
    assert out3["note"].startswith(th.GURU_NOPOOL) and out3["thoughts"] == []


def test_proto_roundtrip():
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    now = datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)
    conn = _Conn([_row()], newest=datetime(2026, 9, 7, 12, 48, tzinfo=timezone.utc))
    out = asyncio.run(th.collect_thoughts(_Pool(conn), now=now))
    hint = th.to_proto(out)
    assert isinstance(hint, zpb.ThoughtsHint)
    assert hint.thoughts[0].title == out["thoughts"][0]["title"]
    assert list(hint.thoughts[0].domains) == ["biorxiv", "data-engineering"]
    assert hint.total_in_window == 1 and hint.newest_ms == out["newest_ms"]
