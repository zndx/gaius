"""CLT incidence → SKOS-grounded OWL class pairs.

A CLT feature is a discrete node over admitted content. Items that share a
feature are linked in the corpus graph. Their aperture SKOS codes resolve to
OWL IRIs on the HermiT TBox. Those IRIs are BERTSubs candidates.

CLT features are not owl:Class. This module never writes OWL.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any


def owl_pairs_from_feature_codes(
    feature_codes: dict[tuple[int, int], set[str]],
    resolve: Callable[[str], str | None],
    *,
    limit: int,
) -> list[tuple[str, str]]:
    """Pair distinct OWL IRIs that co-occur on the same CLT feature.

    ``resolve`` maps a SKOS / aperture code to an OWL class IRI, or None
    if the code is not grounded.
    """
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for codes in feature_codes.values():
        iris = sorted({iri for code in codes if (iri := resolve(code))})
        for i, subclass in enumerate(iris):
            for superclass in iris[i + 1 :]:
                key = (subclass, superclass)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append(key)
                if len(pairs) >= limit:
                    return pairs
    return pairs


def _resolve_code(code: str) -> str | None:
    from gaius.engine.services.sdg_aperture import SdgAperture

    anchor = SdgAperture.load().resolve(code)
    return anchor.iri if anchor else None


async def owl_pairs_from_conn(
    conn: Any,
    slice_id: str,
    *,
    limit: int = 20,
) -> list[tuple[str, str]]:
    """OWL class pairs from CLT co-activation in this ISO week."""
    import asyncpg

    try:
        rows = await conn.fetch(
            """
            SELECT a.layer, a.feature_idx, i.aperture_code
              FROM activation a
              JOIN admitted_item i ON i.id = a.item_id
             WHERE i.aperture_code <> ''
               AND to_char(i.admitted_at AT TIME ZONE 'UTC', 'IYYY')
                   || '-W' || to_char(i.admitted_at AT TIME ZONE 'UTC', 'IW')
                   = $1
            """,
            slice_id,
        )
    except asyncpg.UndefinedTableError:
        return []

    feature_codes: dict[tuple[int, int], set[str]] = defaultdict(set)
    for row in rows:
        code = str(row["aperture_code"] or "").strip()
        if code:
            feature_codes[(int(row["layer"]), int(row["feature_idx"]))].add(code)
    return owl_pairs_from_feature_codes(feature_codes, _resolve_code, limit=limit)


async def load_owl_pairs_for_slice(
    dsn: str,
    slice_id: str,
    *,
    limit: int = 20,
) -> list[tuple[str, str]]:
    import asyncpg

    pool = await asyncpg.create_pool(dsn)
    try:
        async with pool.acquire() as conn:
            return await owl_pairs_from_conn(conn, slice_id, limit=limit)
    finally:
        await pool.close()
