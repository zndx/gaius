"""Gaius inbound → 512-token windows → MaxSim (Aegir method, Gaius sources)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from gaius.engine.services.sdg_aperture import SdgAperture
from gaius.flows.prospects.windows import TokenWindow, scan_windows

GURU_NOEXTRACT = (
    "Extracted source text is missing for this inbound document.\n"
    "  Guru: #WS.00000019.NOEXTRACT\n"
    "  The kb_path on content_items must exist under GAIUS_KB_ROOT"
)


def extracted_source_text(
    *,
    title: str,
    summary: str,
    kb_path: str = "",
    kb_root: Path | None = None,
) -> tuple[str, str]:
    """Complete extracted source the 512-token windows are cut from.

    Prefer the pipeline KB note at ``kb_path``. Else title + summary.
    Returns (text, origin) where origin is ``kb:<rel>`` or ``title+summary``.
    """
    rel = (kb_path or "").strip()
    if rel:
        from gaius.engine.services.agenda_notes import kb_root_from_env
        from gaius.engine.services.summary_lineup import SummaryLineupError, jail_kb

        root = kb_root or kb_root_from_env()
        try:
            path = jail_kb(root, rel)
        except SummaryLineupError as e:
            raise RuntimeError(f"{GURU_NOEXTRACT}\n  kb_path={rel!r}") from e
        if not path.is_file():
            raise RuntimeError(f"{GURU_NOEXTRACT}\n  kb_path={rel!r}")
        return path.read_text(encoding="utf-8"), f"kb:{rel}"
    parts = [str(title or "").strip(), str(summary or "").strip()]
    text = "\n\n".join(p for p in parts if p)
    if not text:
        raise RuntimeError(f"{GURU_NOEXTRACT}\n  no kb_path, title, or summary")
    return text, "title+summary"


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
        rows = await conn.fetch(
            """
            SELECT c.id::text AS source_id,
                   c.title,
                   COALESCE(c.summary, '') AS summary,
                   COALESCE(c.kb_path, '') AS kb_path
              FROM content_items c
             WHERE c.fetched_at >= $1
               AND NOT COALESCE(c.summary_excluded, false)
             ORDER BY c.fetched_at DESC
             LIMIT $2
            """,
            since,
            limit,
        )
    from gaius.engine.services.agenda_notes import kb_root_from_env

    root = kb_root_from_env()
    out = []
    for r in rows:
        text, _origin = extracted_source_text(
            title=str(r["title"] or ""),
            summary=str(r["summary"] or ""),
            kb_path=str(r["kb_path"] or ""),
            kb_root=root,
        )
        out.append({"source_id": r["source_id"], "text": text})
    return out
