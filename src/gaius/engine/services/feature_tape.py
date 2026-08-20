"""Persist CLT activations for Discover. Postgres only — no markdown."""

from __future__ import annotations

from datetime import datetime
from typing import Any

ENSURE_SQL = """
CREATE TABLE IF NOT EXISTS feature_tape (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    stream TEXT NOT NULL,
    source_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    layer INTEGER NOT NULL,
    feature_idx INTEGER NOT NULL,
    activation DOUBLE PRECISION NOT NULL,
    worker TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS feature_tape_event_feat
    ON feature_tape (event_id, layer, feature_idx);
CREATE INDEX IF NOT EXISTS feature_tape_ts ON feature_tape (ts DESC);
CREATE INDEX IF NOT EXISTS feature_tape_feat ON feature_tape (layer, feature_idx);
"""


async def ensure_tape(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(ENSURE_SQL)


async def event_already_probed(pool: Any, event_id: str) -> bool:
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT 1 FROM feature_tape WHERE event_id = $1 LIMIT 1",
            event_id,
        )
    return n is not None


async def insert_activations(
    pool: Any,
    *,
    event_id: str,
    stream: str,
    source_id: str,
    ts: datetime,
    rows: list[tuple[int, int, float]],
    worker: str,
) -> int:
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO feature_tape
                (event_id, stream, source_id, ts, layer, feature_idx, activation, worker)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (event_id, layer, feature_idx) DO UPDATE
              SET activation = EXCLUDED.activation
            """,
            [
                (event_id, stream, source_id, ts, layer, idx, act, worker)
                for layer, idx, act in rows
            ],
        )
    return len(rows)


async def pick_unprobed_inflow(pool: Any, *, since, limit: int) -> list[Any]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT c.id, c.title, COALESCE(c.summary, '') AS body,
                   COALESCE(c.kb_path, '') AS kb_path,
                   c.fetched_at, COALESCE(s.name, '') AS source
              FROM content_items c
              LEFT JOIN feed_sources s ON s.id = c.source_id
             WHERE c.fetched_at >= $1
               AND NOT COALESCE(c.summary_excluded, false)
               AND NOT EXISTS (
                   SELECT 1 FROM feature_tape t
                    WHERE t.event_id = 'inflow:' || c.id::text
               )
             ORDER BY c.fetched_at DESC
             LIMIT $2
            """,
            since,
            limit,
        )


async def tape_stats(pool: Any, *, since) -> dict[str, Any]:
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT count(*) FROM feature_tape WHERE ts >= $1", since
        )
        events = await conn.fetchval(
            "SELECT count(DISTINCT event_id) FROM feature_tape WHERE ts >= $1",
            since,
        )
        feats = await conn.fetchval(
            "SELECT count(DISTINCT (layer, feature_idx)) FROM feature_tape WHERE ts >= $1",
            since,
        )
    return {
        "rows": int(total or 0),
        "events": int(events or 0),
        "distinct_features": int(feats or 0),
    }
