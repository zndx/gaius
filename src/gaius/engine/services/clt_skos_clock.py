"""Incremental corpus clock: overlap watermark, quarantine, task run_id.

Admit advances the watermark per successfully processed document.
``admitted_item (source_id, char_start, char_end)`` is the idempotency
key. Late ``fetched_at`` arrivals are picked up by overlap; poison docs
go to ``admitted_quarantine`` and re-enter when extract backfills.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from gaius.engine.services.clt_skos_admit import extracted_source_text

GURU_QUARANTINE = "#WS.00000019.NOEXTRACT"
OVERLAP_SECONDS = 3600
EXEMPLAR_STALE_JACCARD = 0.7
EXEMPLAR_TOP = 8

ENSURE_CLOCK_SQL = """
ALTER TABLE admitted_item ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS admit_progress (
    source_id TEXT PRIMARY KEY,
    fetched_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS admitted_quarantine (
    source_id TEXT PRIMARY KEY,
    fetched_at TIMESTAMPTZ,
    guru TEXT NOT NULL,
    reason TEXT NOT NULL,
    kb_path TEXT NOT NULL DEFAULT '',
    iceberg_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS skos_pref_label (
    notation TEXT PRIMARY KEY,
    pref_label TEXT NOT NULL,
    clt_uri TEXT NOT NULL,
    labeler_model TEXT NOT NULL DEFAULT '',
    labeler_version TEXT NOT NULL DEFAULT '',
    exemplar_hash TEXT NOT NULL,
    item_ids BIGINT[] NOT NULL DEFAULT '{}',
    stale BOOLEAN NOT NULL DEFAULT FALSE,
    run_id TEXT NOT NULL DEFAULT '',
    labeled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stale_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS clt_skos_clock (
    key TEXT PRIMARY KEY,
    watermark_fetched_at TIMESTAMPTZ,
    overlap_seconds INTEGER NOT NULL DEFAULT 3600,
    last_run_id TEXT NOT NULL DEFAULT '',
    last_run_at TIMESTAMPTZ,
    run_count INTEGER NOT NULL DEFAULT 0
);
INSERT INTO clt_skos_clock (key) VALUES ('admit'), ('label')
ON CONFLICT (key) DO NOTHING;
"""


@dataclass
class ExtractMiss(Exception):
    guru: str
    reason: str
    kb_path: str = ""
    iceberg_id: str = ""

    def __str__(self) -> str:
        return f"{self.guru} {self.reason}"


def next_watermark(
    current: datetime | None, fetched_at: datetime | None
) -> datetime | None:
    """Watermark only moves forward, per successfully processed doc."""
    if fetched_at is None:
        return current
    if current is None or fetched_at > current:
        return fetched_at
    return current


def jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def exemplar_hash(rows: list[tuple[int, int, int]]) -> str:
    blob = json.dumps(sorted(rows), separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def is_stale(
    stored_ids: list[int],
    current_ids: list[int],
    *,
    threshold: float = EXEMPLAR_STALE_JACCARD,
) -> bool:
    return jaccard(set(stored_ids), set(current_ids)) < threshold


async def ensure_clock(pool: Any) -> None:
    from gaius.engine.services.clt_skos_ledger import ensure_ledger

    await ensure_ledger(pool)
    async with pool.acquire() as conn:
        await conn.execute(ENSURE_CLOCK_SQL)


async def write_task_run_id(pool: Any, task_id: int, run_id: str) -> None:
    if not task_id or not run_id:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE scheduled_tasks
               SET result = COALESCE(result, '{}'::jsonb)
                            || jsonb_build_object('run_id', $2::text)
             WHERE id = $1
            """,
            int(task_id),
            run_id,
        )


async def mark_clock_started(pool: Any, key: str, run_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO clt_skos_clock (key, last_run_id, last_run_at, run_count)
            VALUES ($1, $2, NOW(), 1)
            ON CONFLICT (key) DO UPDATE
              SET last_run_at = NOW(),
                  run_count = clt_skos_clock.run_count + 1,
                  last_run_id = COALESCE(NULLIF($2, ''), clt_skos_clock.last_run_id)
            """,
            key,
            run_id,
        )


async def load_watermark(pool: Any) -> tuple[datetime | None, int]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT watermark_fetched_at, overlap_seconds
              FROM clt_skos_clock WHERE key = 'admit'
            """
        )
    if not row:
        return None, OVERLAP_SECONDS
    return row["watermark_fetched_at"], int(row["overlap_seconds"] or OVERLAP_SECONDS)


async def save_watermark(
    pool: Any, watermark: datetime | None, run_id: str
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE clt_skos_clock
               SET watermark_fetched_at = $1,
                   last_run_id = $2
             WHERE key = 'admit'
            """,
            watermark,
            run_id,
        )


async def select_due_docs(pool: Any, *, batch: int) -> list[Any]:
    watermark, overlap = await load_watermark(pool)
    floor = None
    if watermark is not None:
        floor = watermark - timedelta(seconds=overlap)
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT c.id::text AS source_id,
                   c.fetched_at,
                   c.title,
                   COALESCE(c.summary, '') AS summary,
                   COALESCE(c.kb_path, '') AS kb_path,
                   COALESCE(c.iceberg_id, '') AS iceberg_id
              FROM content_items c
             WHERE NOT COALESCE(c.summary_excluded, false)
               AND ($1::timestamptz IS NULL OR c.fetched_at >= $1)
               AND (
                    NOT EXISTS (
                        SELECT 1 FROM admit_progress p
                         WHERE p.source_id = c.id::text
                           AND p.status IN ('admitted', 'empty')
                    )
                    OR EXISTS (
                        SELECT 1 FROM admitted_quarantine q
                         WHERE q.source_id = c.id::text
                           AND q.resolved_at IS NULL
                           AND (
                                (COALESCE(c.kb_path, '') <> ''
                                 AND c.kb_path IS DISTINCT FROM NULLIF(q.kb_path, ''))
                             OR (COALESCE(c.iceberg_id, '') <> ''
                                 AND c.iceberg_id IS DISTINCT FROM NULLIF(q.iceberg_id, ''))
                           )
                    )
               )
             ORDER BY c.fetched_at ASC, c.id ASC
             LIMIT $2
            """,
            floor,
            batch,
        )


def require_extracted(doc: Any, *, kb_root: Any) -> tuple[str, str]:
    """Parent text for MaxSim. Missing extract → ExtractMiss, not tick death."""
    kb_path = str(doc["kb_path"] or "")
    iceberg_id = str(doc["iceberg_id"] or "")
    if kb_path:
        try:
            return extracted_source_text(
                title=str(doc["title"] or ""),
                summary=str(doc["summary"] or ""),
                kb_path=kb_path,
                kb_root=kb_root,
            )
        except RuntimeError as e:
            raise ExtractMiss(
                GURU_QUARANTINE,
                f"no kb_path file: {e}",
                kb_path=kb_path,
                iceberg_id=iceberg_id,
            ) from e
    if iceberg_id:
        text = _iceberg_body(iceberg_id)
        if text:
            return text, f"iceberg:{iceberg_id}"
        raise ExtractMiss(
            GURU_QUARANTINE,
            "no Iceberg body",
            kb_path=kb_path,
            iceberg_id=iceberg_id,
        )
    raise ExtractMiss(
        GURU_QUARANTINE,
        "no kb_path, no Iceberg body",
        kb_path=kb_path,
        iceberg_id=iceberg_id,
    )


def _iceberg_body(iceberg_id: str) -> str:
    try:
        from gaius.hx.reader import ContentReader

        item = ContentReader().get_by_id(iceberg_id)
    except Exception:
        return ""
    if item is None:
        return ""
    return str(getattr(item, "raw_content", None) or "")


async def quarantine_doc(
    pool: Any,
    doc: Any,
    miss: ExtractMiss,
    run_id: str,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO admitted_quarantine
                (source_id, fetched_at, guru, reason, kb_path, iceberg_id, run_id,
                 quarantined_at, resolved_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NULL)
            ON CONFLICT (source_id) DO UPDATE
              SET fetched_at = EXCLUDED.fetched_at,
                  guru = EXCLUDED.guru,
                  reason = EXCLUDED.reason,
                  kb_path = EXCLUDED.kb_path,
                  iceberg_id = EXCLUDED.iceberg_id,
                  run_id = EXCLUDED.run_id,
                  quarantined_at = NOW(),
                  resolved_at = NULL
            """,
            str(doc["source_id"]),
            doc["fetched_at"],
            miss.guru,
            miss.reason[:800],
            miss.kb_path,
            miss.iceberg_id,
            run_id,
        )


async def resolve_quarantine(pool: Any, source_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE admitted_quarantine
               SET resolved_at = NOW()
             WHERE source_id = $1 AND resolved_at IS NULL
            """,
            source_id,
        )


async def mark_progress(
    pool: Any,
    *,
    source_id: str,
    fetched_at: datetime | None,
    status: str,
    run_id: str,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO admit_progress (source_id, fetched_at, status, run_id, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (source_id) DO UPDATE
              SET fetched_at = EXCLUDED.fetched_at,
                  status = EXCLUDED.status,
                  run_id = EXCLUDED.run_id,
                  updated_at = NOW()
            """,
            source_id,
            fetched_at,
            status,
            run_id,
        )


async def current_exemplars(
    pool: Any, layer: int, feat: int, *, top: int = EXEMPLAR_TOP
) -> list[tuple[int, int, int]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT item_id, span_start, span_end
              FROM activation
             WHERE model = 'clt' AND layer = $1 AND feature_idx = $2
               AND span_end > span_start
             ORDER BY activation DESC
             LIMIT $3
            """,
            layer,
            feat,
            top,
        )
    return [(int(r["item_id"]), int(r["span_start"]), int(r["span_end"])) for r in rows]


async def mark_stale_labels(pool: Any) -> int:
    n = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT notation, item_ids
              FROM skos_pref_label
             WHERE NOT stale
            """
        )
    for r in rows:
        notation = str(r["notation"])
        try:
            layer_s, feat_s = notation.split(":", 1)
            layer, feat = int(layer_s), int(feat_s)
        except ValueError:
            continue
        stored = [int(x) for x in (r["item_ids"] or [])]
        current = await current_exemplars(pool, layer, feat)
        current_ids = [t[0] for t in current]
        if not is_stale(stored, current_ids):
            continue
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE skos_pref_label
                   SET stale = TRUE, stale_at = NOW()
                 WHERE notation = $1 AND NOT stale
                """,
                notation,
            )
        n += 1
    return n


async def run_admit_tick(
    pool: Any,
    *,
    run_id: str,
    task_id: int = 0,
    batch: int = 16,
    gpu_index: int = 4,
    extract_top_k: int = 16,
    skip_extract: bool = False,
) -> dict[str, Any]:
    from gaius.engine.services.agenda_notes import kb_root_from_env
    from gaius.engine.services.clt_skos_admit import admit_text, build_qdrant_maxsim
    from gaius.engine.services.clt_skos_aperture import v2_offsets
    from gaius.engine.services.clt_skos_extract import extract_positional
    from gaius.engine.services.clt_skos_ground import spans_for_features
    from gaius.engine.services.clt_skos_ledger import insert_activations, upsert_admitted
    from gaius.engine.services.sdg_aperture import SdgAperture

    await ensure_clock(pool)
    await write_task_run_id(pool, task_id, run_id)
    await mark_clock_started(pool, "admit", run_id)
    kb_root = kb_root_from_env()
    aperture = SdgAperture.load()
    maxsim = build_qdrant_maxsim(aperture)
    docs = await select_due_docs(pool, batch=batch)
    watermark, _ = await load_watermark(pool)
    stats = {
        "docs": len(docs),
        "admitted": 0,
        "empty": 0,
        "quarantined": 0,
        "extracted": 0,
        "run_id": run_id,
    }
    for doc in docs:
        sid = str(doc["source_id"])
        try:
            text, _origin = require_extracted(doc, kb_root=kb_root)
        except ExtractMiss as miss:
            await quarantine_doc(pool, doc, miss, run_id)
            stats["quarantined"] += 1
            continue
        windows = admit_text(
            text,
            aperture=aperture,
            maxsim=maxsim,
            require_maxsim=True,
            encode_offsets=v2_offsets,
        )
        item_ids: list[int] = []
        for w in windows:
            iid = await upsert_admitted(
                pool,
                source_id=sid,
                char_start=w.start,
                char_end=w.end,
                text=w.text,
                aperture_code=w.code,
                margin=w.margin,
                run_id=run_id,
            )
            item_ids.append(iid)
            stats["admitted"] += 1
        if not skip_extract:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, text FROM admitted_item WHERE id = ANY($1::bigint[])",
                    item_ids,
                )
            for row in rows:
                got = extract_positional(
                    row["text"],
                    gpu_index=gpu_index,
                    top_k=extract_top_k,
                )
                grounded = spans_for_features(got["features"], got["offsets"])
                stats["extracted"] += await insert_activations(
                    pool, int(row["id"]), grounded
                )
        status = "admitted" if item_ids else "empty"
        if not item_ids:
            stats["empty"] += 1
        await mark_progress(
            pool,
            source_id=sid,
            fetched_at=doc["fetched_at"],
            status=status,
            run_id=run_id,
        )
        await resolve_quarantine(pool, sid)
        watermark = next_watermark(watermark, doc["fetched_at"])
        await save_watermark(pool, watermark, run_id)
    return stats


async def upsert_pref_label(
    pool: Any,
    *,
    notation: str,
    pref_label: str,
    clt_uri: str,
    labeler_model: str,
    labeler_version: str,
    exemplar_hash_s: str,
    item_ids: list[int],
    run_id: str,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO skos_pref_label
                (notation, pref_label, clt_uri, labeler_model, labeler_version,
                 exemplar_hash, item_ids, stale, run_id, labeled_at, stale_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE, $8, NOW(), NULL)
            ON CONFLICT (notation) DO UPDATE
              SET pref_label = EXCLUDED.pref_label,
                  clt_uri = EXCLUDED.clt_uri,
                  labeler_model = EXCLUDED.labeler_model,
                  labeler_version = EXCLUDED.labeler_version,
                  exemplar_hash = EXCLUDED.exemplar_hash,
                  item_ids = EXCLUDED.item_ids,
                  stale = FALSE,
                  run_id = EXCLUDED.run_id,
                  labeled_at = NOW(),
                  stale_at = NULL
            """,
            notation,
            pref_label,
            clt_uri,
            labeler_model,
            labeler_version,
            exemplar_hash_s,
            item_ids,
            run_id,
        )
