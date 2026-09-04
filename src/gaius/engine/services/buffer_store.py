"""Durable FIFO store behind the ambient / prospects / publishing buffers.

(2026-09-04) The three RAM FIFOs were the reason three model workloads ran
inside the engine on private timers. Flows on pg_cron (``fmp_roll``,
``ambient_synthesis``) now write and compact the buffers in
``buffer_entries``; the engine's buffers are read-through caches of the live
rows. The byte contract is AmbientBuffer's own: compaction runs
AmbientBuffer's plan on a transient instance seeded from the live rows and
the difference is written back (new SUMMARY row inserted, replaced rows
stamped ``compacted_at`` / ``compacted_into`` — history, never deletion).

Fail-fast: a missing table or a failed write raises with a guru code. The
only tolerated absence is ``pool is None`` (unit tests), where DurableBuffer
behaves as the RAM buffer it subclasses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from gaius.engine.services.ambient_buffer import AmbientBuffer, BufferEntry, BufferRole

log = logging.getLogger("gaius.engine.buffer_store")

BUFFERS = ("ambient", "prospects", "publishing")
GURU_STORE = "#BUF.00000002.STORE"

_SELECT_LIVE = """
SELECT id, role, content, content_bytes, source_url, metadata, created_at
  FROM buffer_entries
 WHERE buffer = $1 AND compacted_at IS NULL
 ORDER BY created_at, id
"""

_INSERT = """
INSERT INTO buffer_entries
    (id, buffer, role, content, content_bytes, source_url, metadata, writer, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
ON CONFLICT (id) DO NOTHING
"""


def _check_buffer(buffer: str) -> str:
    if buffer not in BUFFERS:
        raise ValueError(f"{GURU_STORE} unknown buffer {buffer!r}; one of {BUFFERS}")
    return buffer


def _aware(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc) if ts.tzinfo is None else ts


def _row_to_entry(r: Any) -> BufferEntry:
    meta = r["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta or "{}")
    return BufferEntry(
        id=str(r["id"]),
        role=BufferRole(r["role"]),
        content=r["content"],
        content_bytes=int(r["content_bytes"]),
        created_at=r["created_at"],
        source_url=r["source_url"] or "",
        metadata=dict(meta or {}),
    )


def _entry_args(buffer: str, e: BufferEntry, writer: str) -> tuple:
    return (
        uuid.UUID(e.id),
        buffer,
        e.role.value,
        e.content,
        int(e.content_bytes),
        e.source_url or "",
        json.dumps(e.metadata or {}, default=str),
        writer,
        _aware(e.created_at),
    )


async def append_many(pool: Any, buffer: str, entries: list[BufferEntry], *, writer: str) -> int:
    """Insert entries as live rows. Returns the number handed to the store."""
    _check_buffer(buffer)
    if not entries:
        return 0
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_INSERT, [_entry_args(buffer, e, writer) for e in entries])
    except Exception as e:  # noqa: BLE001 — re-raised with remediation
        raise RuntimeError(
            f"{GURU_STORE} append to buffer_entries({buffer}) failed: {e}\n"
            "  Try: dbmate up (migration 20260904000001_durable_buffers)"
        ) from e
    return len(entries)


async def append(pool: Any, buffer: str, entry: BufferEntry, *, writer: str) -> str:
    await append_many(pool, buffer, [entry], writer=writer)
    return entry.id


async def live_entries(pool: Any, buffer: str) -> list[BufferEntry]:
    _check_buffer(buffer)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_LIVE, buffer)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"{GURU_STORE} read of buffer_entries({buffer}) failed: {e}\n"
            "  Try: dbmate up (migration 20260904000001_durable_buffers)"
        ) from e
    return [_row_to_entry(r) for r in rows]


async def live_stats(pool: Any, buffer: str) -> dict[str, int]:
    _check_buffer(buffer)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COALESCE(SUM(content_bytes),0) AS bytes, COUNT(*) AS n "
            "FROM buffer_entries WHERE buffer=$1 AND compacted_at IS NULL",
            buffer,
        )
    return {"bytes": int(row["bytes"]), "count": int(row["n"])}


async def live_fingerprints(pool: Any, buffer: str) -> set[str]:
    """md5(content) of live rows — dedupe key for re-fetched feed items."""
    _check_buffer(buffer)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT md5(content) AS fp FROM buffer_entries "
            "WHERE buffer=$1 AND compacted_at IS NULL",
            buffer,
        )
    return {r["fp"] for r in rows}


def diff_compaction(
    before: list[BufferEntry], after: list[BufferEntry]
) -> tuple[list[str], list[BufferEntry]]:
    """(ids dropped, entries created) between two FIFO states. Pure."""
    before_ids = {e.id for e in before}
    after_ids = {e.id for e in after}
    dropped = [e.id for e in before if e.id not in after_ids]
    created = [e for e in after if e.id not in before_ids]
    return dropped, created


async def compact(
    pool: Any,
    buffer: str,
    *,
    max_bytes: int,
    summarize: Callable[[str], Awaitable[str]],
    writer: str,
) -> dict[str, Any]:
    """Run AmbientBuffer's compaction plan over the live rows and persist the
    difference. Returns AmbientBuffer.compact_if_needed's dict plus counts."""
    _check_buffer(buffer)
    live = await live_entries(pool, buffer)
    work = AmbientBuffer(max_bytes=max_bytes)
    work.load(live)
    out = await work.compact_if_needed(summarize)
    if out.get("skipped"):
        return {**out, "buffer": buffer, "live_bytes": work.current_bytes, "live_entries": len(live)}
    after = await work.snapshot()
    dropped, created = diff_compaction(live, after)
    into = uuid.UUID(created[0].id) if len(created) == 1 else None
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if created:
                    await conn.executemany(
                        _INSERT, [_entry_args(buffer, e, writer) for e in created]
                    )
                if dropped:
                    await conn.execute(
                        "UPDATE buffer_entries SET compacted_at = NOW(), compacted_into = $1 "
                        "WHERE id = ANY($2::uuid[]) AND compacted_at IS NULL",
                        into,
                        [uuid.UUID(i) for i in dropped],
                    )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"{GURU_STORE} persisting compaction of {buffer} failed: {e}"
        ) from e
    log.info(
        "buffer %s compacted: dropped=%s created=%s bytes=%s (writer=%s)",
        buffer, len(dropped), len(created), work.current_bytes, writer,
    )
    return {
        **out,
        "buffer": buffer,
        "dropped_ids": len(dropped),
        "created": len(created),
        "live_bytes": work.current_bytes,
    }


class DurableBuffer(AmbientBuffer):
    """Engine-side read-through cache of one durable buffer.

    ``snapshot()`` refreshes from the table first (synthesis and export see
    what the flows wrote); the sync ``get_stats``/``current_bytes`` return the
    last refreshed state, kept current by ``start_refresh``. Appends made by
    the engine (rare after the migration) are persisted too.
    """

    def __init__(self, pool: Any, name: str, max_bytes: int, *, refresh_s: float = 60.0) -> None:
        super().__init__(max_bytes=max_bytes)
        self._pool = pool
        self.name = _check_buffer(name)
        self._refresh_s = float(refresh_s)
        self._last_refresh = 0.0
        self._refresh_task: asyncio.Task[None] | None = None

    @property
    def durable(self) -> bool:
        return self._pool is not None

    async def refresh(self, *, force: bool = False, max_age_s: float = 5.0) -> None:
        if self._pool is None:
            return
        if not force and (time.monotonic() - self._last_refresh) < max_age_s:
            return
        entries = await live_entries(self._pool, self.name)
        async with self._lock:
            self._entries = deque(entries)
            self._current_bytes = sum(e.content_bytes for e in entries)
        self._last_refresh = time.monotonic()

    async def snapshot(self) -> list[BufferEntry]:
        await self.refresh()
        return await super().snapshot()

    async def add_entry(self, entry: BufferEntry) -> str:
        eid = await super().add_entry(entry)
        if self._pool is not None:
            await append(self._pool, self.name, entry, writer="engine")
        return eid

    async def compact_if_needed(self, summarize) -> dict[str, object]:
        if self._pool is None:
            return await super().compact_if_needed(summarize)
        out = await compact(
            self._pool, self.name, max_bytes=self._max_bytes, summarize=summarize, writer="engine"
        )
        await self.refresh(force=True)
        return out

    def start_refresh(self) -> None:
        """Cache maintenance so the sync stats track the table (no model work)."""
        if self._pool is None or self._refresh_task is not None:
            return

        async def _loop() -> None:
            while True:
                try:
                    await self.refresh(force=True)
                except Exception as e:  # noqa: BLE001 — surfaced, loop survives
                    log.warning("%s refresh of %s buffer failed: %s", GURU_STORE, self.name, e)
                await asyncio.sleep(self._refresh_s)

        self._refresh_task = asyncio.create_task(_loop(), name=f"buffer-refresh-{self.name}")

    async def stop_refresh(self) -> None:
        t = self._refresh_task
        self._refresh_task = None
        if t is not None:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
