"""CLT incidence → novel OWL class pairs.

A CLT feature links admitted items. Each item is MaxSim-grounded to the
full TBox (not the 33 aiming anchors). Pairs are classes on distinct
items that share a feature. Asserted or entailed ⊑ (either direction)
is excluded — BERTSubs scores only incomparable classes, both ways,
ranked by co-activation × MaxSim, not IRI lexicography.

CLT features are not owl:Class. This module never writes OWL.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GroundedItem:
    item_id: int
    classes: tuple[tuple[str, float], ...]
    activation: float


def novel_directed_pairs(
    feature_items: dict[tuple[int, int], list[GroundedItem]],
    entailed: frozenset[tuple[str, str]] | set[tuple[str, str]],
    *,
    ranked_limit: int,
) -> list[tuple[str, str]]:
    """Cross-item class pairs that the TBox does not already settle."""
    weights: dict[tuple[str, str], float] = defaultdict(float)
    for items in feature_items.values():
        unique: dict[int, GroundedItem] = {}
        for it in items:
            prev = unique.get(it.item_id)
            if prev is None or it.activation > prev.activation:
                unique[it.item_id] = it
        ids = list(unique.values())
        if len(ids) < 2:
            continue
        for i, left in enumerate(ids):
            for right in ids[i + 1 :]:
                w_items = (left.activation + right.activation)
                for ci, si in left.classes:
                    for cj, sj in right.classes:
                        if ci == cj:
                            continue
                        if (ci, cj) in entailed or (cj, ci) in entailed:
                            continue
                        w = w_items * si * sj
                        weights[(ci, cj)] += w
                        weights[(cj, ci)] += w
    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
    return [pair for pair, _ in ranked[:ranked_limit]]


def _ground_items(
    rows: list[Any],
    *,
    top_k: int,
) -> dict[tuple[int, int], list[GroundedItem]]:
    from gaius.agents.theta.tbox_maxsim import live_tbox_maxsim

    maxsim = live_tbox_maxsim()
    cache: dict[int, tuple[tuple[str, float], ...]] = {}
    grouped: dict[tuple[int, int], list[GroundedItem]] = defaultdict(list)
    for row in rows:
        iid = int(row["id"])
        if iid not in cache:
            cache[iid] = tuple(maxsim(str(row["text"] or ""), k=top_k))
        classes = cache[iid]
        if not classes:
            continue
        feat = (int(row["layer"]), int(row["feature_idx"]))
        grouped[feat].append(
            GroundedItem(
                item_id=iid,
                classes=classes,
                activation=float(row["activation"] or 0.0),
            )
        )
    return grouped


async def owl_pairs_from_conn(
    conn: Any,
    slice_id: str,
    *,
    ranked_limit: int = 64,
    top_k: int = 8,
) -> list[tuple[str, str]]:
    """Novel OWL pairs from CLT co-activation in this ISO week."""
    import asyncpg

    from gaius.agents.theta.tbox import entailed_subsumptions

    try:
        rows = await conn.fetch(
            """
            SELECT i.id, i.text, a.layer, a.feature_idx, a.activation
              FROM activation a
              JOIN admitted_item i ON i.id = a.item_id
             WHERE coalesce(i.text, '') <> ''
               AND to_char(i.admitted_at AT TIME ZONE 'UTC', 'IYYY')
                   || '-W' || to_char(i.admitted_at AT TIME ZONE 'UTC', 'IW')
                   = $1
            """,
            slice_id,
        )
    except asyncpg.UndefinedTableError:
        return []

    grouped = _ground_items(rows, top_k=top_k)
    return novel_directed_pairs(
        grouped, entailed_subsumptions(), ranked_limit=ranked_limit
    )


async def load_owl_pairs_for_slice(
    dsn: str,
    slice_id: str,
    *,
    ranked_limit: int = 64,
    top_k: int = 8,
) -> list[tuple[str, str]]:
    import asyncpg

    pool = await asyncpg.create_pool(dsn)
    try:
        async with pool.acquire() as conn:
            return await owl_pairs_from_conn(
                conn, slice_id, ranked_limit=ranked_limit, top_k=top_k
            )
    finally:
        await pool.close()
