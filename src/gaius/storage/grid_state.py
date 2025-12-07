"""Grid state persistence with Postgres.

Stores grid projections, TDA features, and history in Postgres for:
- Fast startup (no pickle file I/O)
- History tracking (see how grid evolved over time)
- Queryable state (find when documents were added)
- Sharing across instances

Schema:
    grid_snapshots: Snapshot metadata (timestamp, config, stats)
    grid_points: Individual document positions on grid
    tda_features: Topological features for each snapshot
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..core.projection import GridData, GridPoint
    from ..core.tda import TDAFeatures, BoundingBox

# Lazy import asyncpg
_asyncpg = None


def _get_asyncpg():
    """Lazy import asyncpg."""
    global _asyncpg
    if _asyncpg is None:
        import asyncpg
        _asyncpg = asyncpg
    return _asyncpg


def get_database_url() -> str:
    """Get database URL from environment."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://gaius:gaius@localhost:5432/gaius"
    )


# =============================================================================
# Schema Creation
# =============================================================================

SCHEMA_SQL = """
-- Grid snapshots: metadata for each projection
CREATE TABLE IF NOT EXISTS grid_snapshots (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    kb_root TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_type TEXT DEFAULT 'single',
    projection_method TEXT DEFAULT 'umap',
    n_documents INT DEFAULT 0,
    coverage FLOAT DEFAULT 0.0,
    -- TDA summary stats
    h0_count INT DEFAULT 0,
    h1_count INT DEFAULT 0,
    h2_count INT DEFAULT 0,
    entropy FLOAT DEFAULT 0.0,
    -- Status
    is_current BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'
);

-- Index for fast current snapshot lookup
CREATE INDEX IF NOT EXISTS idx_grid_snapshots_current
    ON grid_snapshots(kb_root, is_current) WHERE is_current = TRUE;

-- Grid points: document positions on the 19x19 grid
CREATE TABLE IF NOT EXISTS grid_points (
    id SERIAL PRIMARY KEY,
    snapshot_id INT REFERENCES grid_snapshots(id) ON DELETE CASCADE,
    x INT NOT NULL CHECK (x >= 0 AND x < 19),
    y INT NOT NULL CHECK (y >= 0 AND y < 19),
    doc_path TEXT NOT NULL,
    doc_title TEXT DEFAULT '',
    embedding_id TEXT DEFAULT '',
    cluster_id INT DEFAULT -1,
    -- Optional: store raw embedding for future use (pgvector)
    -- embedding VECTOR(768),
    UNIQUE(snapshot_id, doc_path)
);

-- Index for position lookups
CREATE INDEX IF NOT EXISTS idx_grid_points_position
    ON grid_points(snapshot_id, x, y);

-- TDA features: topological features for each snapshot
CREATE TABLE IF NOT EXISTS grid_tda_features (
    id SERIAL PRIMARY KEY,
    snapshot_id INT REFERENCES grid_snapshots(id) ON DELETE CASCADE UNIQUE,
    -- H1 cycles (loops) as JSONB array of bounding boxes
    h1_cycles JSONB DEFAULT '[]',
    -- H2 voids (cavities) as JSONB array
    h2_voids JSONB DEFAULT '[]',
    -- H0 components as JSONB array
    components JSONB DEFAULT '[]',
    -- Per-point risk scores
    risk_scores JSONB DEFAULT '[]',
    -- Raw persistence intervals
    intervals JSONB DEFAULT '[]'
);

-- Allocations: grid cell intensity values
CREATE TABLE IF NOT EXISTS grid_allocations (
    id SERIAL PRIMARY KEY,
    snapshot_id INT REFERENCES grid_snapshots(id) ON DELETE CASCADE UNIQUE,
    -- 19x19 allocation grid as JSONB 2D array
    values JSONB NOT NULL DEFAULT '[]'
);

-- Cluster centers: white stone positions
CREATE TABLE IF NOT EXISTS grid_clusters (
    id SERIAL PRIMARY KEY,
    snapshot_id INT REFERENCES grid_snapshots(id) ON DELETE CASCADE,
    x INT NOT NULL CHECK (x >= 0 AND x < 19),
    y INT NOT NULL CHECK (y >= 0 AND y < 19),
    UNIQUE(snapshot_id, x, y)
);

-- Raw embeddings: stored separately for efficient bulk operations
CREATE TABLE IF NOT EXISTS grid_embeddings (
    id SERIAL PRIMARY KEY,
    snapshot_id INT REFERENCES grid_snapshots(id) ON DELETE CASCADE,
    embedding_index INT NOT NULL,
    -- Store as JSONB array (768 floats) - could use pgvector later
    vector JSONB NOT NULL,
    grid_x INT,
    grid_y INT,
    UNIQUE(snapshot_id, embedding_index)
);
"""


async def ensure_schema() -> bool:
    """Create schema if it doesn't exist.

    Returns:
        True if schema was created/verified successfully
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(SCHEMA_SQL)
            return True
        finally:
            await conn.close()
    except Exception as e:
        print(f"Schema creation failed: {e}")
        return False


# =============================================================================
# Data Classes for Results
# =============================================================================

@dataclass
class GridSnapshotInfo:
    """Summary info for a grid snapshot."""
    id: int
    created_at: datetime
    kb_root: str
    embedding_model: str
    projection_method: str
    n_documents: int
    coverage: float
    h0_count: int
    h1_count: int
    h2_count: int
    entropy: float
    is_current: bool


# =============================================================================
# Repository Operations
# =============================================================================

async def save_grid_state(
    kb_root: str,
    grid_data: "GridData",
    tda_features: "TDAFeatures",
    embedding_model: str,
    projection_method: str,
    embedding_type: str = "single",
) -> int | None:
    """Save grid state to Postgres.

    Args:
        kb_root: KB root directory
        grid_data: Computed grid projection
        tda_features: Computed TDA features
        embedding_model: Model used for embeddings
        projection_method: Projection method (umap/pca)
        embedding_type: Embedding type ("single" or "multi")

    Returns:
        Snapshot ID if successful, None otherwise
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            # Start transaction
            async with conn.transaction():
                # Mark previous snapshots as not current
                await conn.execute(
                    """
                    UPDATE grid_snapshots
                    SET is_current = FALSE
                    WHERE kb_root = $1 AND is_current = TRUE
                    """,
                    kb_root
                )

                # Create new snapshot
                snapshot_id = await conn.fetchval(
                    """
                    INSERT INTO grid_snapshots (
                        kb_root, embedding_model, embedding_type,
                        projection_method, n_documents, coverage,
                        h0_count, h1_count, h2_count, entropy,
                        is_current, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, TRUE, $11)
                    RETURNING id
                    """,
                    kb_root,
                    embedding_model,
                    embedding_type,
                    projection_method,
                    grid_data.n_documents,
                    grid_data.coverage,
                    tda_features.h0_count,
                    tda_features.h1_count,
                    tda_features.h2_count,
                    tda_features.entropy,
                    json.dumps({
                        "method": grid_data.method,
                        "saved_at": datetime.now().isoformat(),
                    }),
                )

                # Save grid points
                if grid_data.points:
                    await conn.executemany(
                        """
                        INSERT INTO grid_points (
                            snapshot_id, x, y, doc_path, doc_title,
                            embedding_id, cluster_id
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        [
                            (
                                snapshot_id,
                                p.x,
                                p.y,
                                p.path,
                                p.title,
                                p.embedding_id,
                                p.cluster_id,
                            )
                            for p in grid_data.points
                        ],
                    )

                # Save cluster centers
                if grid_data.cluster_centers:
                    await conn.executemany(
                        """
                        INSERT INTO grid_clusters (snapshot_id, x, y)
                        VALUES ($1, $2, $3)
                        """,
                        [(snapshot_id, x, y) for x, y in grid_data.cluster_centers],
                    )

                # Save allocations
                await conn.execute(
                    """
                    INSERT INTO grid_allocations (snapshot_id, values)
                    VALUES ($1, $2)
                    """,
                    snapshot_id,
                    json.dumps(grid_data.allocations),
                )

                # Save TDA features
                await conn.execute(
                    """
                    INSERT INTO grid_tda_features (
                        snapshot_id, h1_cycles, h2_voids,
                        components, risk_scores, intervals
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    snapshot_id,
                    json.dumps([_bbox_to_dict(b) for b in tda_features.h1_cycles]),
                    json.dumps([_bbox_to_dict(b) for b in tda_features.h2_voids]),
                    json.dumps([_bbox_to_dict(b) for b in tda_features.components]),
                    json.dumps(tda_features.risk_scores),
                    json.dumps([_interval_to_dict(i) for i in tda_features.intervals]),
                )

                # Save raw embeddings if available (chunked for large arrays)
                if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) > 0:
                    # Batch insert embeddings
                    embedding_records = []
                    for idx, emb in enumerate(grid_data.raw_embeddings):
                        grid_pos = grid_data.embedding_to_grid.get(idx)
                        embedding_records.append((
                            snapshot_id,
                            idx,
                            json.dumps(emb.tolist()),
                            grid_pos[0] if grid_pos else None,
                            grid_pos[1] if grid_pos else None,
                        ))

                    # Insert in batches of 100
                    for i in range(0, len(embedding_records), 100):
                        batch = embedding_records[i:i+100]
                        await conn.executemany(
                            """
                            INSERT INTO grid_embeddings (
                                snapshot_id, embedding_index, vector, grid_x, grid_y
                            ) VALUES ($1, $2, $3, $4, $5)
                            """,
                            batch,
                        )

                return snapshot_id

        finally:
            await conn.close()

    except Exception as e:
        print(f"Save grid state failed: {e}")
        return None


async def load_current_grid_state(
    kb_root: str,
    embedding_model: str | None = None,
    projection_method: str | None = None,
) -> tuple["GridData | None", "TDAFeatures | None", dict | None]:
    """Load the current grid state from Postgres.

    Args:
        kb_root: KB root directory
        embedding_model: Optional model filter (must match if provided)
        projection_method: Optional projection filter

    Returns:
        Tuple of (grid_data, tda_features, metadata) or (None, None, None)
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            # Find current snapshot
            query = """
                SELECT id, created_at, kb_root, embedding_model, embedding_type,
                       projection_method, n_documents, coverage,
                       h0_count, h1_count, h2_count, entropy, metadata
                FROM grid_snapshots
                WHERE kb_root = $1 AND is_current = TRUE
            """
            params = [kb_root]

            if embedding_model:
                query = query.replace(
                    "AND is_current = TRUE",
                    "AND is_current = TRUE AND embedding_model = $2"
                )
                params.append(embedding_model)

            if projection_method:
                idx = len(params) + 1
                query = query.replace(
                    "AND is_current = TRUE",
                    f"AND is_current = TRUE AND projection_method = ${idx}"
                )
                params.append(projection_method)

            row = await conn.fetchrow(query, *params)

            if not row:
                return None, None, None

            snapshot_id = row["id"]

            # Load grid points
            point_rows = await conn.fetch(
                """
                SELECT x, y, doc_path, doc_title, embedding_id, cluster_id
                FROM grid_points
                WHERE snapshot_id = $1
                """,
                snapshot_id,
            )

            # Load cluster centers
            cluster_rows = await conn.fetch(
                """
                SELECT x, y FROM grid_clusters WHERE snapshot_id = $1
                """,
                snapshot_id,
            )

            # Load allocations
            alloc_row = await conn.fetchrow(
                """
                SELECT values FROM grid_allocations WHERE snapshot_id = $1
                """,
                snapshot_id,
            )

            # Load TDA features
            tda_row = await conn.fetchrow(
                """
                SELECT h1_cycles, h2_voids, components, risk_scores, intervals
                FROM grid_tda_features
                WHERE snapshot_id = $1
                """,
                snapshot_id,
            )

            # Load embeddings (for TDA recomputation if needed)
            emb_rows = await conn.fetch(
                """
                SELECT embedding_index, vector, grid_x, grid_y
                FROM grid_embeddings
                WHERE snapshot_id = $1
                ORDER BY embedding_index
                """,
                snapshot_id,
            )

            # Reconstruct GridData
            from ..core.projection import GridData, GridPoint

            points = [
                GridPoint(
                    x=r["x"],
                    y=r["y"],
                    path=r["doc_path"],
                    title=r["doc_title"],
                    embedding_id=r["embedding_id"],
                    cluster_id=r["cluster_id"],
                )
                for r in point_rows
            ]

            document_positions = {(p.x, p.y) for p in points}
            cluster_centers = {(r["x"], r["y"]) for r in cluster_rows}
            allocations = json.loads(alloc_row["values"]) if alloc_row else [[0]*19 for _ in range(19)]

            # Reconstruct embeddings
            raw_embeddings = None
            embedding_to_grid = {}
            grid_to_embedding = {}

            if emb_rows:
                raw_embeddings = np.array([
                    json.loads(r["vector"]) for r in emb_rows
                ])
                for r in emb_rows:
                    idx = r["embedding_index"]
                    if r["grid_x"] is not None and r["grid_y"] is not None:
                        pos = (r["grid_x"], r["grid_y"])
                        embedding_to_grid[idx] = pos
                        grid_to_embedding[pos] = idx

            grid_data = GridData(
                document_positions=document_positions,
                cluster_centers=cluster_centers,
                allocations=allocations,
                points=points,
                method=row["projection_method"],
                n_documents=row["n_documents"],
                coverage=row["coverage"],
                raw_embeddings=raw_embeddings,
                embedding_to_grid=embedding_to_grid,
                grid_to_embedding=grid_to_embedding,
            )

            # Reconstruct TDAFeatures
            from ..core.tda import TDAFeatures, BoundingBox, PersistenceInterval

            h1_cycles = [_dict_to_bbox(d) for d in json.loads(tda_row["h1_cycles"])] if tda_row else []
            h2_voids = [_dict_to_bbox(d) for d in json.loads(tda_row["h2_voids"])] if tda_row else []
            components = [_dict_to_bbox(d) for d in json.loads(tda_row["components"])] if tda_row else []
            risk_scores = json.loads(tda_row["risk_scores"]) if tda_row else []
            intervals = [_dict_to_interval(d) for d in json.loads(tda_row["intervals"])] if tda_row else []

            tda_features = TDAFeatures(
                intervals=intervals,
                h1_cycles=h1_cycles,
                h2_voids=h2_voids,
                components=components,
                risk_scores=risk_scores,
                h0_count=row["h0_count"],
                h1_count=row["h1_count"],
                h2_count=row["h2_count"],
                entropy=row["entropy"],
            )

            # Build metadata
            metadata = {
                "snapshot_id": snapshot_id,
                "created_at": row["created_at"].isoformat(),
                "embedding_model": row["embedding_model"],
                "embedding_type": row["embedding_type"],
                "projection_method": row["projection_method"],
                "version": 3,  # Postgres version
            }
            if row["metadata"]:
                metadata.update(json.loads(row["metadata"]))

            return grid_data, tda_features, metadata

        finally:
            await conn.close()

    except Exception as e:
        print(f"Load grid state failed: {e}")
        return None, None, None


async def list_snapshots(
    kb_root: str,
    limit: int = 20,
) -> list[GridSnapshotInfo]:
    """List recent grid snapshots.

    Args:
        kb_root: KB root directory
        limit: Maximum snapshots to return

    Returns:
        List of GridSnapshotInfo, most recent first
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                """
                SELECT id, created_at, kb_root, embedding_model,
                       projection_method, n_documents, coverage,
                       h0_count, h1_count, h2_count, entropy, is_current
                FROM grid_snapshots
                WHERE kb_root = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                kb_root,
                limit,
            )

            return [
                GridSnapshotInfo(
                    id=r["id"],
                    created_at=r["created_at"],
                    kb_root=r["kb_root"],
                    embedding_model=r["embedding_model"],
                    projection_method=r["projection_method"],
                    n_documents=r["n_documents"],
                    coverage=r["coverage"],
                    h0_count=r["h0_count"],
                    h1_count=r["h1_count"],
                    h2_count=r["h2_count"],
                    entropy=r["entropy"],
                    is_current=r["is_current"],
                )
                for r in rows
            ]
        finally:
            await conn.close()
    except Exception:
        return []


async def delete_old_snapshots(
    kb_root: str,
    keep_count: int = 10,
) -> int:
    """Delete old snapshots, keeping the most recent ones.

    Args:
        kb_root: KB root directory
        keep_count: Number of snapshots to keep

    Returns:
        Number of snapshots deleted
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            # Delete snapshots older than the Nth most recent
            result = await conn.execute(
                """
                DELETE FROM grid_snapshots
                WHERE kb_root = $1
                  AND id NOT IN (
                      SELECT id FROM grid_snapshots
                      WHERE kb_root = $1
                      ORDER BY created_at DESC
                      LIMIT $2
                  )
                """,
                kb_root,
                keep_count,
            )
            # Parse "DELETE N" result
            return int(result.split()[-1]) if result else 0
        finally:
            await conn.close()
    except Exception:
        return 0


async def check_state_exists(
    kb_root: str,
    embedding_model: str,
    projection_method: str,
) -> bool:
    """Check if valid state exists for the given config.

    Args:
        kb_root: KB root directory
        embedding_model: Model that must match
        projection_method: Projection method that must match

    Returns:
        True if matching current state exists
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            exists = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM grid_snapshots
                    WHERE kb_root = $1
                      AND embedding_model = $2
                      AND projection_method = $3
                      AND is_current = TRUE
                )
                """,
                kb_root,
                embedding_model,
                projection_method,
            )
            return exists
        finally:
            await conn.close()
    except Exception:
        return False


# =============================================================================
# Helper Functions
# =============================================================================

def _bbox_to_dict(bbox: "BoundingBox") -> dict:
    """Convert BoundingBox to JSON-serializable dict."""
    return {
        "x_min": bbox.x_min,
        "y_min": bbox.y_min,
        "x_max": bbox.x_max,
        "y_max": bbox.y_max,
        "persistence": bbox.persistence,
    }


def _dict_to_bbox(d: dict) -> "BoundingBox":
    """Convert dict back to BoundingBox."""
    from ..core.tda import BoundingBox
    return BoundingBox(
        x_min=d["x_min"],
        y_min=d["y_min"],
        x_max=d["x_max"],
        y_max=d["y_max"],
        persistence=d.get("persistence", 0.0),
    )


def _interval_to_dict(interval: "PersistenceInterval") -> dict:
    """Convert PersistenceInterval to JSON-serializable dict."""
    return {
        "dimension": interval.dimension,
        "birth": interval.birth,
        "death": interval.death,
        "persistence": interval.persistence,
    }


def _dict_to_interval(d: dict) -> "PersistenceInterval":
    """Convert dict back to PersistenceInterval."""
    from ..core.tda import PersistenceInterval
    return PersistenceInterval(
        dimension=d["dimension"],
        birth=d["birth"],
        death=d["death"],
        persistence=d.get("persistence", d["death"] - d["birth"]),
    )
