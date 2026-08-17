"""Project the live knowledge base onto the 19×19 board.

UMAP/TDA snapshots live in ``current_state`` when ``/reindex`` has run.
Until then (Qdrant empty, no embeddings) the board still has to show
*what is already there*: markdown under ``build/dev`` plus
``content_items`` Iceberg links. That inventory uses
``projection_method=kb_topology`` — path structure, not fake Ricci.

Iceberg is the HX destination (``iceberg_id`` on ``content_items``).
The board reports migration coverage; it does not invent a warehouse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOARD_JSON_NAME = ".board.json"
PROJECTION_KB_TOPOLOGY = "kb_topology"
GRID = 19

_TIER_Y = {
    "archive": (0, 3),
    "current": (3, 13),
    "scratch": (13, 19),
}


def _fnv1a(text: str) -> int:
    h = 2166136261
    for ch in text.encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def place_path(rel: str, domains: tuple[str, ...] = ()) -> tuple[int, int]:
    """Deterministic cell for a KB-relative path (posix)."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return (9, 9)
    tier = parts[0] if parts[0] in _TIER_Y else "current"
    y0, y1 = _TIER_Y[tier]
    if tier == "current" and len(parts) > 1:
        domain = parts[1]
        if domains and domain in domains:
            x = domains.index(domain) % GRID
        else:
            x = _fnv1a(domain) % GRID
        rest = "/".join(parts[2:]) or domain
        y = y0 + (_fnv1a(rest) % (y1 - y0))
        return (x, y)
    if tier == "scratch" and len(parts) > 1:
        x = _fnv1a(parts[1]) % GRID
        rest = "/".join(parts[2:]) or parts[1]
        y = y0 + (_fnv1a(rest) % (y1 - y0))
        return (x, y)
    x = _fnv1a(rel) % GRID
    y = y0 + (_fnv1a(parts[-1]) % (y1 - y0))
    return (x, y)


@dataclass
class BoardDoc:
    path: str
    title: str
    x: int
    y: int
    iceberg_id: str = ""
    source: str = "file"  # file | content_item | both


@dataclass
class BoardSnapshot:
    kb_root: str
    projection_method: str
    n_documents: int
    n_iceberg: int
    n_file_only: int
    cells_occupied: int
    documents: list[BoardDoc]
    allocations: list[list[int]]
    iceberg_map: list[list[float]]
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_state_json(self) -> dict[str, Any]:
        return {
            "documents": [
                {
                    "x": d.x,
                    "y": d.y,
                    "path": d.path,
                    "title": d.title,
                    "cluster_id": -1,
                    "iceberg_id": d.iceberg_id,
                    "source": d.source,
                }
                for d in self.documents
            ],
            "clusters": [],
            "allocations": self.allocations,
            "iceberg_map": self.iceberg_map,
            "h0_count": 0,
            "h1_count": 0,
            "h2_count": 0,
            "h1_cycles": [],
            "h2_voids": [],
            "components": [],
            "risk_scores": [],
            "entropy": 0.0,
            "n_documents": self.n_documents,
            "n_iceberg": self.n_iceberg,
            "n_file_only": self.n_file_only,
            "cells_occupied": self.cells_occupied,
            "projection_method": self.projection_method,
            "embedding_model": "",
            "updated_at": self.updated_at,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "kb_root": self.kb_root,
            "projection_method": self.projection_method,
            "n_documents": self.n_documents,
            "n_iceberg": self.n_iceberg,
            "n_file_only": self.n_file_only,
            "cells_occupied": self.cells_occupied,
            "iceberg_coverage": (
                round(self.n_iceberg / self.n_documents, 4)
                if self.n_documents
                else 0.0
            ),
            "updated_at": self.updated_at,
        }


def _scan_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for tier in ("current", "scratch", "archive"):
        base = root / tier
        if not base.is_dir():
            continue
        found.extend(p for p in base.rglob("*.md") if p.is_file())
    return found


async def load_content_index() -> dict[str, str]:
    """kb_path → iceberg_id from content_items. Empty dict if DB down."""
    from gaius.storage.grid_state import (
        check_database_availability,
        get_database_url,
        _get_asyncpg,
    )

    if not await check_database_availability():
        return {}
    conn = await _get_asyncpg().connect(get_database_url())
    try:
        rows = await conn.fetch(
            """
            SELECT kb_path, iceberg_id
            FROM content_items
            WHERE kb_path IS NOT NULL AND kb_path <> ''
            """
        )
    finally:
        await conn.close()
    out: dict[str, str] = {}
    for row in rows:
        path = str(row["kb_path"]).lstrip("./")
        iced = row["iceberg_id"] or ""
        out[path] = str(iced) if iced else out.get(path, "")
    return out


def build_board_snapshot(
    kb_root: str | Path,
    *,
    catalog: dict[str, str] | None = None,
) -> BoardSnapshot:
    key = str(kb_root)
    root = Path(kb_root)
    if not root.is_absolute():
        root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(
            f"KB root missing: {root}\n"
            "  Guru: #KB.00000001.NOROOT\n"
            "  Try: confirm config kb.root (build/dev)"
        )

    current = root / "current"
    domains = tuple(
        sorted(p.name for p in current.iterdir() if p.is_dir())
    ) if current.is_dir() else ()

    iced_by_path = catalog or {}
    by_path: dict[str, BoardDoc] = {}

    for fp in _scan_files(root):
        rel = fp.relative_to(root).as_posix()
        x, y = place_path(rel, domains)
        by_path[rel] = BoardDoc(
            path=rel,
            title=fp.stem.replace("_", " "),
            x=x,
            y=y,
            iceberg_id=iced_by_path.get(rel, ""),
            source="file",
        )

    for rel, iceberg_id in iced_by_path.items():
        if rel in by_path:
            if iceberg_id:
                by_path[rel].iceberg_id = iceberg_id
            if by_path[rel].source == "file" and iceberg_id:
                by_path[rel].source = "both"
            continue
        x, y = place_path(rel, domains)
        by_path[rel] = BoardDoc(
            path=rel,
            title=Path(rel).stem.replace("_", " "),
            x=x,
            y=y,
            iceberg_id=iceberg_id,
            source="content_item",
        )

    docs = list(by_path.values())
    counts: list[list[int]] = [[0] * GRID for _ in range(GRID)]
    iced_counts: list[list[int]] = [[0] * GRID for _ in range(GRID)]
    for d in docs:
        counts[d.y][d.x] += 1
        if d.iceberg_id:
            iced_counts[d.y][d.x] += 1

    peak = max((c for row in counts for c in row), default=1) or 1
    allocations = [
        [
            0 if counts[y][x] == 0 else max(1, int(100 * counts[y][x] / peak))
            for x in range(GRID)
        ]
        for y in range(GRID)
    ]
    iceberg_map = [
        [
            (iced_counts[y][x] / counts[y][x]) if counts[y][x] else 0.0
            for x in range(GRID)
        ]
        for y in range(GRID)
    ]
    n_iceberg = sum(1 for d in docs if d.iceberg_id)
    return BoardSnapshot(
        kb_root=key,
        projection_method=PROJECTION_KB_TOPOLOGY,
        n_documents=len(docs),
        n_iceberg=n_iceberg,
        n_file_only=len(docs) - n_iceberg,
        cells_occupied=sum(1 for row in counts for c in row if c),
        documents=docs,
        allocations=allocations,
        iceberg_map=iceberg_map,
    )


async def publish_board_snapshot(snap: BoardSnapshot) -> int:
    """Write ``current_state`` + ``<kb>/.board.json``. Does not touch UMAP rows."""
    from gaius.storage.grid_state import (
        check_database_availability,
        get_database_url,
        _get_asyncpg,
    )

    payload = snap.to_state_json()
    board_path = Path(snap.kb_root) / BOARD_JSON_NAME
    board_path.write_text(
        json.dumps({**snap.summary(), "allocations": snap.allocations}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    if not await check_database_availability():
        raise RuntimeError(
            "Postgres unavailable; cannot publish board to current_state.\n"
            "  Guru: #DB.00000001.CONNFAIL\n"
            "  Try: /health fix postgres"
        )

    conn = await _get_asyncpg().connect(get_database_url())
    try:
        existing = await conn.fetchrow(
            "SELECT state_json FROM current_state WHERE kb_root = $1",
            snap.kb_root,
        )
        if existing and existing["state_json"]:
            prev = existing["state_json"]
            if isinstance(prev, str):
                prev = json.loads(prev)
            method = (prev or {}).get("projection_method") or ""
            n_docs = int((prev or {}).get("n_documents") or 0)
            if method == "umap" and n_docs > 0:
                raise RuntimeError(
                    "current_state is a UMAP projection; refuse to overwrite "
                    f"with {PROJECTION_KB_TOPOLOGY} ({n_docs} docs).\n"
                    "  Guru: #KB.00000002.UMAPLIVE\n"
                    "  Try: /reindex if the embedding index should refresh"
                )

        gen = await conn.fetchval(
            """
            INSERT INTO current_state (kb_root, snapshot_id, generation, state_json, updated_at)
            VALUES ($1, NULL, 1, $2::jsonb, NOW())
            ON CONFLICT (kb_root) DO UPDATE SET
                snapshot_id = NULL,
                generation = current_state.generation + 1,
                state_json = EXCLUDED.state_json,
                updated_at = NOW()
            RETURNING generation
            """,
            snap.kb_root,
            json.dumps(payload),
        )
        return int(gen or 1)
    finally:
        await conn.close()


def cached_is_umap(kb_root: str) -> bool:
    from gaius.storage.grid_state import load_current_state_fast_sync

    cached = load_current_state_fast_sync(kb_root)
    if cached is None or cached.n_documents <= 0:
        return False
    return cached.projection_method == "umap"
