"""Gaius inbound → 512-token windows → MaxSim (Aegir method, Gaius sources)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from gaius.engine.services.sdg_aperture import SdgAperture
from gaius.flows.prospects.windows import TokenWindow, scan_windows

GURU_NOMAXSIM = (
    "Aperture MaxSim collection is required for CLT SKOS ingest.\n"
    "  Guru: #SDG.00000005.NOMAXSIM\n"
    "  Load sdg_aperture in Qdrant or pass a maxsim callback."
)


def build_qdrant_maxsim(aperture: SdgAperture) -> Callable[[str], tuple[str, float]]:
    """Live MaxSim against the aiming collection. Materializes C if missing."""
    from gaius.engine.services.clt_skos_aperture import live_maxsim

    _ = aperture
    return live_maxsim()


def require_aperture_collection(aperture: SdgAperture) -> None:
    """Fail-fast if the live MaxSim index is missing. Do not admit-all."""
    import os

    from qdrant_client import QdrantClient

    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6339"))
    client = QdrantClient(host=host, port=port)
    if not client.collection_exists(aperture.collection):
        raise RuntimeError(
            f"{GURU_NOMAXSIM}\n  collection={aperture.collection!r} "
            f"not on {host}:{port}"
        )


@dataclass
class AdmitResult:
    source_id: str
    windows: list[TokenWindow]
    kept: int


def admit_text(
    text: str,
    *,
    aperture: SdgAperture,
    maxsim: Callable[[str], tuple[str, float]] | None,
    require_maxsim: bool,
    encode_offsets: Callable[[str], list[tuple[int, int]]] | None = None,
) -> list[TokenWindow]:
    if require_maxsim and maxsim is None:
        raise RuntimeError(GURU_NOMAXSIM)
    scan = scan_windows(
        text,
        size=aperture.colbert_token_limit,
        maxsim=maxsim,
        tau=aperture.tau,
        encode_offsets=encode_offsets,
    )
    return [w for w in scan.windows if w.admitted]


async def load_source_items(
    pool: Any,
    *,
    since: datetime | None,
    limit: int,
) -> list[Any]:
    since = since or (datetime.now(timezone.utc) - timedelta(days=7))
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT c.id::text AS source_id,
                   c.title || E'\\n\\n' || COALESCE(c.summary, '') AS text
              FROM content_items c
             WHERE c.fetched_at >= $1
               AND NOT COALESCE(c.summary_excluded, false)
             ORDER BY c.fetched_at DESC
             LIMIT $2
            """,
            since,
            limit,
        )
