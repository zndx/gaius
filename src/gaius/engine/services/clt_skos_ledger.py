"""Postgres ledger for CLT/SAE SKOS evaluation (admitted items + activations)."""

from __future__ import annotations

from typing import Any

ENSURE_SQL = """
CREATE TABLE IF NOT EXISTS admitted_item (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    text TEXT NOT NULL,
    aperture_code TEXT NOT NULL DEFAULT '',
    margin DOUBLE PRECISION NOT NULL DEFAULT 0,
    admitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, char_start, char_end)
);
CREATE INDEX IF NOT EXISTS admitted_item_source ON admitted_item (source_id);
CREATE TABLE IF NOT EXISTS activation (
    id BIGSERIAL PRIMARY KEY,
    item_id BIGINT NOT NULL REFERENCES admitted_item (id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    layer INTEGER NOT NULL,
    feature_idx INTEGER NOT NULL,
    position INTEGER NOT NULL,
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    activation DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS activation_item ON activation (item_id);
CREATE INDEX IF NOT EXISTS activation_feat ON activation (model, layer, feature_idx);
"""


async def ensure_ledger(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(ENSURE_SQL)


async def upsert_admitted(
    pool: Any,
    *,
    source_id: str,
    char_start: int,
    char_end: int,
    text: str,
    aperture_code: str,
    margin: float,
) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO admitted_item
                (source_id, char_start, char_end, text, aperture_code, margin)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (source_id, char_start, char_end) DO UPDATE
              SET text = EXCLUDED.text,
                  aperture_code = EXCLUDED.aperture_code,
                  margin = EXCLUDED.margin
            RETURNING id
            """,
            source_id,
            char_start,
            char_end,
            text,
            aperture_code,
            margin,
        )
    return int(row["id"])


async def insert_activations(
    pool: Any,
    item_id: int,
    rows: list[tuple[str, int, int, int, int, int, float]],
) -> int:
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO activation
                (item_id, model, layer, feature_idx, position, span_start, span_end, activation)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            [
                (item_id, model, layer, feat, pos, a, b, act)
                for model, layer, feat, pos, a, b, act in rows
            ],
        )
    return len(rows)
