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
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

import numpy as np

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..core.projection import GridData, GridPoint
    from ..core.tda import TDAFeatures, BoundingBox, PersistenceInterval
    from ..core.geometry import GeometricFeatures

# Lazy import asyncpg
_asyncpg = None

# Database availability cache (check once, don't spam logs)
_db_available: bool | None = None
_db_check_error: str | None = None


def _get_asyncpg():
    """Lazy import asyncpg."""
    global _asyncpg
    if _asyncpg is None:
        import asyncpg
        _asyncpg = asyncpg
    return _asyncpg


def is_database_available() -> bool:
    """Check if database is available (cached result).

    Returns cached result after first check to avoid spamming connection attempts.
    Call reset_database_availability() to force re-check.
    """
    return _db_available is True


def get_database_unavailable_reason() -> str | None:
    """Get the reason database is unavailable, if any."""
    return _db_check_error


def reset_database_availability() -> None:
    """Reset cached database availability to force re-check."""
    global _db_available, _db_check_error
    _db_available = None
    _db_check_error = None


async def check_database_availability() -> bool:
    """Check if database is available and cache the result.

    This should be called once at startup. Subsequent calls return cached result.
    """
    global _db_available, _db_check_error

    if _db_available is not None:
        return _db_available

    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url, timeout=5)
        await conn.close()
        _db_available = True
        _db_check_error = None
        logger.info("Database connection verified")
        return True
    except Exception as e:
        _db_available = False
        _db_check_error = str(e)
        # Log once, not on every operation
        logger.warning(
            f"Database unavailable: {e}\n"
            "Guru Meditation: #DB.00000001.CONNFAIL\n"
            "Session persistence and fast state loading disabled.\n"
            "Start PostgreSQL: devenv up postgres"
        )
        return False


def check_database_availability_sync() -> bool:
    """Synchronous check for database availability (cached result).

    If not yet checked, performs a blocking check. Otherwise returns cached result.
    """
    global _db_available, _db_check_error

    if _db_available is not None:
        return _db_available

    import asyncio

    # Check if we're inside a running event loop
    try:
        asyncio.get_running_loop()
        # Running inside event loop - can't do sync check, assume unavailable until async check
        return False
    except RuntimeError:
        pass

    # Not in event loop, can run async check
    return asyncio.run(check_database_availability())


def get_database_url() -> str:
    """Get database URL from config.

    Delegates to gaius.core.config.get_database_url() for centralized
    database URL resolution.
    """
    from ..core.config import get_database_url as _core_get_database_url
    return _core_get_database_url()


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
        logger.warning(f"Schema creation failed: {e}")
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
    geometry_features: "GeometricFeatures | None" = None,
) -> int | None:
    """Save grid state to Postgres.

    Args:
        kb_root: KB root directory
        grid_data: Computed grid projection
        tda_features: Computed TDA features
        embedding_model: Model used for embeddings
        projection_method: Projection method (umap/pca)
        embedding_type: Embedding type ("single" or "multi")
        geometry_features: Optional GeometricFeatures (curvature, gradients, divergence)

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

                # Update current_state table (denormalized cache for instant startup)
                state_json = {
                    "documents": [
                        {
                            "x": p.x,
                            "y": p.y,
                            "path": p.path,
                            "title": p.title,
                            "cluster_id": p.cluster_id,
                        }
                        for p in (grid_data.points or [])
                    ],
                    "clusters": list(grid_data.cluster_centers or []),
                    "allocations": grid_data.allocations,
                    "h0_count": tda_features.h0_count,
                    "h1_count": tda_features.h1_count,
                    "h2_count": tda_features.h2_count,
                    "h1_cycles": [_bbox_to_dict(b) for b in tda_features.h1_cycles],
                    "h2_voids": [_bbox_to_dict(b) for b in tda_features.h2_voids],
                    "components": [_bbox_to_dict(b) for b in tda_features.components],
                    "risk_scores": tda_features.risk_scores,
                    "entropy": tda_features.entropy,
                    "n_documents": grid_data.n_documents,
                    "projection_method": projection_method,
                    "embedding_model": embedding_model,
                }

                # Add geometry features if provided
                if geometry_features is not None:
                    logger.info(f"Processing geometry features: {len(geometry_features.curvatures)} curvatures, "
                               f"{len(geometry_features.gradients)} gradients, "
                               f"embedding_to_grid has {len(grid_data.embedding_to_grid)} entries")
                    # Build curvature_map (19x19 flattened) and gradient_field
                    curvature_map = [[0.0] * 19 for _ in range(19)]
                    curvature_count = [[0] * 19 for _ in range(19)]
                    gradient_field = []
                    divergence_map = [[0.0] * 19 for _ in range(19)]
                    divergence_count = [[0] * 19 for _ in range(19)]

                    for idx, kappa in enumerate(geometry_features.curvatures):
                        if idx in grid_data.embedding_to_grid:
                            x, y = grid_data.embedding_to_grid[idx]
                            if 0 <= x < 19 and 0 <= y < 19:
                                curvature_map[y][x] += float(kappa)
                                curvature_count[y][x] += 1

                    for idx, (gx, gy) in enumerate(geometry_features.gradients):
                        if idx in grid_data.embedding_to_grid:
                            x, y = grid_data.embedding_to_grid[idx]
                            if 0 <= x < 19 and 0 <= y < 19:
                                gradient_field.append([x, y, float(gx), float(gy)])

                    for idx, div in enumerate(geometry_features.divergence):
                        if idx in grid_data.embedding_to_grid:
                            x, y = grid_data.embedding_to_grid[idx]
                            if 0 <= x < 19 and 0 <= y < 19:
                                divergence_map[y][x] += float(div)
                                divergence_count[y][x] += 1

                    # Average values per cell
                    for y in range(19):
                        for x in range(19):
                            if curvature_count[y][x] > 0:
                                curvature_map[y][x] /= curvature_count[y][x]
                            if divergence_count[y][x] > 0:
                                divergence_map[y][x] /= divergence_count[y][x]

                    # Flatten to 361-element lists
                    state_json["curvature_map"] = [
                        curvature_map[y][x] for y in range(19) for x in range(19)
                    ]
                    state_json["gradient_field"] = gradient_field
                    state_json["divergence_map"] = [
                        divergence_map[y][x] for y in range(19) for x in range(19)
                    ]
                    # Store raw curvatures for Iso view
                    state_json["curvatures_raw"] = [float(k) for k in geometry_features.curvatures]

                    logger.info(f"Geometry added to state_json: {len(gradient_field)} gradient vectors, "
                               f"curvature_map has non-zero count at {sum(1 for row in curvature_count for c in row if c > 0)}")

                # Atomic upsert with generation increment
                await conn.execute(
                    """
                    INSERT INTO current_state (kb_root, snapshot_id, generation, state_json, updated_at)
                    VALUES ($1, $2, 1, $3, NOW())
                    ON CONFLICT (kb_root) DO UPDATE SET
                        snapshot_id = EXCLUDED.snapshot_id,
                        generation = current_state.generation + 1,
                        state_json = EXCLUDED.state_json,
                        updated_at = NOW()
                    """,
                    kb_root,
                    snapshot_id,
                    json.dumps(state_json),
                )

                return snapshot_id

        finally:
            await conn.close()

    except Exception as e:
        logger.warning(f"Save grid state failed: {e}")
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
        logger.warning(f"Load grid state failed: {e}")
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


async def invalidate_state(kb_root: str) -> bool:
    """Invalidate (mark as not current) all snapshots for a KB root.

    Args:
        kb_root: KB root directory

    Returns:
        True if any snapshots were invalidated
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            result = await conn.execute(
                """
                UPDATE grid_snapshots
                SET is_current = FALSE
                WHERE kb_root = $1 AND is_current = TRUE
                """,
                kb_root,
            )
            # Parse "UPDATE N" result
            count = int(result.split()[-1]) if result else 0
            return count > 0
        finally:
            await conn.close()
    except Exception:
        return False


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
        "x_min": bbox.x1,
        "y_min": bbox.y1,
        "x_max": bbox.x2,
        "y_max": bbox.y2,
        "persistence": bbox.persistence,
    }


def _dict_to_bbox(d: dict) -> "BoundingBox":
    """Convert dict back to BoundingBox."""
    from ..core.tda import BoundingBox
    return BoundingBox(
        x1=d["x_min"],
        y1=d["y_min"],
        x2=d["x_max"],
        y2=d["y_max"],
        dimension=d.get("dimension", 1),
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
        # persistence is a computed property, not a constructor parameter
    )


# =============================================================================
# Thin Client Architecture: Fast State Access (Phase 1)
# =============================================================================

@dataclass
class CurrentState:
    """Cached grid state for instant TUI startup.

    This is denormalized JSON from the current_state table
    for <50ms load time.
    """
    kb_root: str
    snapshot_id: int | None
    generation: int
    updated_at: datetime | None

    # Grid data (denormalized for fast access)
    documents: list[dict] = field(default_factory=list)
    clusters: list[tuple[int, int]] = field(default_factory=list)
    allocations: list[list[int]] = field(default_factory=lambda: [[0]*19 for _ in range(19)])

    # TDA features
    h0_count: int = 0
    h1_count: int = 0
    h2_count: int = 0
    h1_cycles: list[dict] = field(default_factory=list)
    h2_voids: list[dict] = field(default_factory=list)
    components: list[dict] = field(default_factory=list)
    risk_scores: list[float] = field(default_factory=list)
    entropy: float = 0.0

    # Geometry features
    gradient_field: list = field(default_factory=list)  # List of [x, y, gx, gy]
    curvature_map: list[float] = field(default_factory=list)  # 361 values (19x19 flattened)
    divergence_map: list[float] = field(default_factory=list)  # 361 values (19x19 flattened)
    curvatures_raw: list[float] = field(default_factory=list)  # Per-point curvatures
    iso_features: dict = field(default_factory=dict)

    # Metadata
    n_documents: int = 0
    projection_method: str = "umap"
    embedding_model: str = ""


@dataclass
class UIPreferences:
    """Per-client UI preferences that survive restarts."""
    client_id: str
    cursor_x: int = 9
    cursor_y: int = 9
    view_mode: str = "go"
    overlay_mode: str = "none"
    iso_mode: str = "curvature"
    center_panel_mode: str = "graph"
    left_panel_visible: bool = True
    right_panel_visible: bool = True
    domain: str | None = None
    preferences_json: dict = field(default_factory=dict)


async def load_current_state_fast(kb_root: str) -> CurrentState | None:
    """Load current state from cache table for instant startup.

    This reads from the denormalized current_state table which
    stores a single JSON blob per kb_root for fast access.

    Args:
        kb_root: KB root directory

    Returns:
        CurrentState if found, None otherwise (silently if DB unavailable)
    """
    # Check if database is available (cached check, logs once)
    if not await check_database_availability():
        return None

    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow(
                """
                SELECT snapshot_id, generation, state_json, updated_at
                FROM current_state
                WHERE kb_root = $1
                """,
                kb_root,
            )

            if not row:
                return None

            state_json = row["state_json"] if row["state_json"] else {}
            if isinstance(state_json, str):
                state_json = json.loads(state_json)

            return CurrentState(
                kb_root=kb_root,
                snapshot_id=row["snapshot_id"],
                generation=row["generation"] or 0,
                updated_at=row["updated_at"],
                documents=state_json.get("documents", []),
                clusters=[tuple(c) for c in state_json.get("clusters", [])],
                allocations=state_json.get("allocations", [[0]*19 for _ in range(19)]),
                h0_count=state_json.get("h0_count", 0),
                h1_count=state_json.get("h1_count", 0),
                h2_count=state_json.get("h2_count", 0),
                h1_cycles=state_json.get("h1_cycles", []),
                h2_voids=state_json.get("h2_voids", []),
                components=state_json.get("components", []),
                risk_scores=state_json.get("risk_scores", []),
                entropy=state_json.get("entropy", 0.0),
                gradient_field=state_json.get("gradient_field", []),
                curvature_map=state_json.get("curvature_map", []),
                divergence_map=state_json.get("divergence_map", []),
                curvatures_raw=state_json.get("curvatures_raw", []),
                iso_features=state_json.get("iso_features", {}),
                n_documents=state_json.get("n_documents", 0),
                projection_method=state_json.get("projection_method", "umap"),
                embedding_model=state_json.get("embedding_model", ""),
            )
        finally:
            await conn.close()

    except Exception as e:
        # Unexpected error after availability check passed - log it
        logger.warning(f"Load current state failed unexpectedly: {e}")
        return None


def load_current_state_fast_sync(kb_root: str) -> CurrentState | None:
    """Synchronous wrapper for load_current_state_fast().

    This enables sync cache loading during TUI __init__ before the
    event loop starts, enabling <100ms startup from Postgres cache.

    Note: Do NOT call from within an existing event loop - use the
    async version load_current_state_fast() instead.

    Args:
        kb_root: KB root directory

    Returns:
        CurrentState if found, None otherwise
    """
    import asyncio

    # Check if we're inside a running event loop
    try:
        asyncio.get_running_loop()
        logger.warning("load_current_state_fast_sync called from async context - use async version")
        return None
    except RuntimeError:
        pass  # No running loop, safe to proceed

    try:
        return asyncio.run(load_current_state_fast(kb_root))
    except Exception as e:
        logger.warning(f"load_current_state_fast_sync failed: {e}")
        return None


async def get_current_generation(kb_root: str) -> int:
    """Get the current generation number for a kb_root.

    Used for sync protocol - clients only need update if generation changed.

    Args:
        kb_root: KB root directory

    Returns:
        Current generation (0 if not found)
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            gen = await conn.fetchval(
                "SELECT generation FROM current_state WHERE kb_root = $1",
                kb_root,
            )
            return gen or 0
        finally:
            await conn.close()
    except Exception:
        return 0


async def update_current_state(
    kb_root: str,
    snapshot_id: int,
    state_json: dict,
) -> int:
    """Atomically update current state with incremented generation.

    Uses the Postgres function update_current_state() for atomic
    generation increment.

    Args:
        kb_root: KB root directory
        snapshot_id: Grid snapshot ID
        state_json: Denormalized state as JSON dict

    Returns:
        New generation number
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            new_gen = await conn.fetchval(
                "SELECT update_current_state($1, $2, $3)",
                kb_root,
                snapshot_id,
                json.dumps(state_json),
            )
            return new_gen or 1
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"Update current state failed: {e}")
        return 0


async def upsert_current_state_if_newer(
    kb_root: str,
    snapshot_id: int,
    generation: int,
    state_json: dict,
) -> bool:
    """Idempotent state update - only applies if generation is higher.

    Safe for concurrent TUI/CLI/MCP calls - uses the Postgres function
    upsert_current_state_if_newer() for atomic comparison and update.

    Args:
        kb_root: KB root directory
        snapshot_id: Grid snapshot ID
        generation: Incoming generation
        state_json: Denormalized state as JSON dict

    Returns:
        True if state was updated, False if incoming was stale
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            updated = await conn.fetchval(
                "SELECT upsert_current_state_if_newer($1, $2, $3, $4)",
                kb_root,
                snapshot_id,
                generation,
                json.dumps(state_json),
            )
            return updated or False
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"Upsert current state failed: {e}")
        return False


async def load_ui_preferences(client_id: str) -> UIPreferences | None:
    """Load UI preferences for a client.

    Args:
        client_id: Client identifier (e.g., "tui", "cli", "mcp")

    Returns:
        UIPreferences if found, None otherwise
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow(
                """
                SELECT cursor_x, cursor_y, view_mode, overlay_mode,
                       iso_mode, center_panel_mode, left_panel_visible,
                       right_panel_visible, domain, preferences_json
                FROM ui_preferences
                WHERE client_id = $1
                """,
                client_id,
            )

            if not row:
                return None

            prefs_json = row["preferences_json"] if row["preferences_json"] else {}
            if isinstance(prefs_json, str):
                prefs_json = json.loads(prefs_json)

            return UIPreferences(
                client_id=client_id,
                cursor_x=row["cursor_x"] or 9,
                cursor_y=row["cursor_y"] or 9,
                view_mode=row["view_mode"] or "go",
                overlay_mode=row["overlay_mode"] or "none",
                iso_mode=row["iso_mode"] or "curvature",
                center_panel_mode=row["center_panel_mode"] or "graph",
                left_panel_visible=row["left_panel_visible"] if row["left_panel_visible"] is not None else True,
                right_panel_visible=row["right_panel_visible"] if row["right_panel_visible"] is not None else True,
                domain=row["domain"],
                preferences_json=prefs_json,
            )
        finally:
            await conn.close()

    except Exception as e:
        logger.warning(f"Load UI preferences failed: {e}")
        return None


async def save_ui_preferences(prefs: UIPreferences) -> bool:
    """Save UI preferences for a client.

    Uses upsert pattern - safe for concurrent calls.

    Args:
        prefs: UI preferences to save

    Returns:
        True if saved successfully
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(
                """
                INSERT INTO ui_preferences (
                    client_id, cursor_x, cursor_y, view_mode, overlay_mode,
                    iso_mode, center_panel_mode, left_panel_visible,
                    right_panel_visible, domain, preferences_json, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
                ON CONFLICT (client_id) DO UPDATE SET
                    cursor_x = EXCLUDED.cursor_x,
                    cursor_y = EXCLUDED.cursor_y,
                    view_mode = EXCLUDED.view_mode,
                    overlay_mode = EXCLUDED.overlay_mode,
                    iso_mode = EXCLUDED.iso_mode,
                    center_panel_mode = EXCLUDED.center_panel_mode,
                    left_panel_visible = EXCLUDED.left_panel_visible,
                    right_panel_visible = EXCLUDED.right_panel_visible,
                    domain = EXCLUDED.domain,
                    preferences_json = EXCLUDED.preferences_json,
                    updated_at = NOW()
                """,
                prefs.client_id,
                prefs.cursor_x,
                prefs.cursor_y,
                prefs.view_mode,
                prefs.overlay_mode,
                prefs.iso_mode,
                prefs.center_panel_mode,
                prefs.left_panel_visible,
                prefs.right_panel_visible,
                prefs.domain,
                json.dumps(prefs.preferences_json),
            )
            return True
        finally:
            await conn.close()

    except Exception as e:
        logger.warning(f"Save UI preferences failed: {e}")
        return False


async def prune_snapshots(
    kb_root: str,
    keep_count: int | None = None,
    older_than_days: int | None = None,
    dry_run: bool = False,
) -> tuple[int, list[int]]:
    """Prune old grid snapshots.

    At least one of keep_count or older_than_days must be specified.

    Args:
        kb_root: KB root directory
        keep_count: Keep only this many most recent snapshots
        older_than_days: Delete snapshots older than this many days
        dry_run: If True, return what would be deleted without deleting

    Returns:
        Tuple of (count deleted, list of deleted snapshot IDs)
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    if keep_count is None and older_than_days is None:
        return 0, []

    try:
        conn = await asyncpg.connect(url)
        try:
            # Build query to find snapshots to delete
            conditions = ["kb_root = $1"]
            params: list[Any] = [kb_root]

            if keep_count is not None:
                # Keep most recent N snapshots
                conditions.append(f"""
                    id NOT IN (
                        SELECT id FROM grid_snapshots
                        WHERE kb_root = $1
                        ORDER BY created_at DESC
                        LIMIT ${len(params) + 1}
                    )
                """)
                params.append(keep_count)

            if older_than_days is not None:
                conditions.append(f"created_at < NOW() - INTERVAL '{older_than_days} days'")

            # Find snapshots to delete
            find_query = f"""
                SELECT id FROM grid_snapshots
                WHERE {' AND '.join(conditions)}
            """
            rows = await conn.fetch(find_query, *params)
            snapshot_ids = [r["id"] for r in rows]

            if dry_run or not snapshot_ids:
                return len(snapshot_ids), snapshot_ids

            # Delete the snapshots (cascade deletes related data)
            await conn.execute(
                f"DELETE FROM grid_snapshots WHERE id = ANY($1)",
                snapshot_ids,
            )

            # Also clean up current_state entries pointing to deleted snapshots
            await conn.execute(
                """
                UPDATE current_state
                SET snapshot_id = NULL
                WHERE kb_root = $1 AND snapshot_id = ANY($2)
                """,
                kb_root,
                snapshot_ids,
            )

            return len(snapshot_ids), snapshot_ids

        finally:
            await conn.close()

    except Exception as e:
        logger.warning(f"Prune snapshots failed: {e}")
        return 0, []


async def log_state_change(
    kb_root: str,
    change_type: str,
    client_id: str | None = None,
    generation: int | None = None,
    change_data: dict | None = None,
) -> bool:
    """Log a state change for audit/debugging.

    Args:
        kb_root: KB root directory
        change_type: Type of change (init, reindex, cursor_move, etc.)
        client_id: Client that made the change
        generation: Generation after the change
        change_data: Additional change details

    Returns:
        True if logged successfully
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(
                """
                INSERT INTO state_changes (kb_root, client_id, change_type, generation, change_data)
                VALUES ($1, $2, $3, $4, $5)
                """,
                kb_root,
                client_id,
                change_type,
                generation,
                json.dumps(change_data) if change_data else None,
            )
            return True
        finally:
            await conn.close()

    except Exception as e:
        logger.warning(f"Log state change failed: {e}")
        return False


async def log_command(
    client_id: str,
    command: str,
    kb_root: str | None = None,
    args: dict | None = None,
    success: bool | None = None,
    offline: bool = False,
    result: dict | None = None,
    duration_ms: int | None = None,
) -> bool:
    """Log a command execution.

    Args:
        client_id: Client that executed the command
        command: Command string
        kb_root: KB root if applicable
        args: Command arguments
        success: Whether command succeeded
        offline: Whether command was attempted offline
        result: Command result
        duration_ms: Execution duration

    Returns:
        True if logged successfully
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(
                """
                INSERT INTO command_history (
                    client_id, kb_root, command, args_json,
                    success, offline, result_json, duration_ms
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                client_id,
                kb_root,
                command,
                json.dumps(args) if args else None,
                success,
                offline,
                json.dumps(result) if result else None,
                duration_ms,
            )
            return True
        finally:
            await conn.close()

    except Exception as e:
        logger.warning(f"Log command failed: {e}")
        return False


async def build_state_json(
    grid_data: "GridData",
    tda_features: "TDAFeatures",
    metadata: dict | None = None,
) -> dict:
    """Build denormalized state JSON for current_state table.

    Combines GridData and TDAFeatures into a single JSON blob
    optimized for fast TUI loading.

    Args:
        grid_data: Grid projection data
        tda_features: TDA features
        metadata: Optional additional metadata

    Returns:
        JSON-serializable dict
    """
    state = {
        # Documents
        "documents": [
            {
                "x": p.x,
                "y": p.y,
                "path": p.path,
                "title": p.title,
                "cluster_id": p.cluster_id,
            }
            for p in (grid_data.points or [])
        ],
        # Clusters
        "clusters": list(grid_data.cluster_centers or []),
        # Allocations
        "allocations": grid_data.allocations,
        # TDA
        "h0_count": tda_features.h0_count,
        "h1_count": tda_features.h1_count,
        "h2_count": tda_features.h2_count,
        "h1_cycles": [_bbox_to_dict(b) for b in tda_features.h1_cycles],
        "h2_voids": [_bbox_to_dict(b) for b in tda_features.h2_voids],
        "components": [_bbox_to_dict(b) for b in tda_features.components],
        "risk_scores": tda_features.risk_scores,
        "entropy": tda_features.entropy,
        # Metadata
        "n_documents": grid_data.n_documents,
        "projection_method": grid_data.method,
    }

    if metadata:
        state["embedding_model"] = metadata.get("embedding_model", "")

    return state


async def load_embeddings_for_snapshot(snapshot_id: int) -> tuple[np.ndarray | None, dict[int, tuple[int, int]], dict[tuple[int, int], int]]:
    """Load raw embeddings from Postgres for minigrid computation.

    This is called asynchronously after initial TUI startup to populate
    the GridManager cache with embedding data needed for minigrid views.

    Args:
        snapshot_id: Grid snapshot ID to load embeddings for

    Returns:
        Tuple of (raw_embeddings, embedding_to_grid, grid_to_embedding)
        Returns (None, {}, {}) if no embeddings found
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                """
                SELECT embedding_index, vector, grid_x, grid_y
                FROM grid_embeddings
                WHERE snapshot_id = $1
                ORDER BY embedding_index
                """,
                snapshot_id,
            )

            if not rows:
                return None, {}, {}

            # Reconstruct embeddings array
            raw_embeddings = np.array([
                json.loads(r["vector"]) for r in rows
            ])

            # Build mappings
            embedding_to_grid: dict[int, tuple[int, int]] = {}
            grid_to_embedding: dict[tuple[int, int], int] = {}

            for r in rows:
                idx = r["embedding_index"]
                if r["grid_x"] is not None and r["grid_y"] is not None:
                    pos = (r["grid_x"], r["grid_y"])
                    embedding_to_grid[idx] = pos
                    grid_to_embedding[pos] = idx

            logger.info(f"Loaded {len(raw_embeddings)} embeddings for snapshot {snapshot_id}")
            return raw_embeddings, embedding_to_grid, grid_to_embedding

        finally:
            await conn.close()

    except Exception as e:
        logger.warning(f"Load embeddings failed: {e}")
        return None, {}, {}


async def load_full_grid_data_for_minigrids(kb_root: str) -> "GridData | None":
    """Load full GridData from Postgres for minigrid computation.

    This combines the fast cached state with embeddings to create a
    complete GridData object suitable for minigrid rendering.

    Called asynchronously after TUI mount to enable minigrids.

    Args:
        kb_root: KB root directory

    Returns:
        GridData with embeddings or None if not available
    """
    from ..core.projection import GridData, GridPoint

    # First load the fast cached state
    cached = await load_current_state_fast(kb_root)
    if cached is None or cached.snapshot_id is None:
        return None

    # Load embeddings
    raw_embeddings, embedding_to_grid, grid_to_embedding = await load_embeddings_for_snapshot(
        cached.snapshot_id
    )

    # Build GridData from cached state + embeddings
    points = [
        GridPoint(
            x=d["x"],
            y=d["y"],
            path=d.get("path", ""),
            title=d.get("title", ""),
            embedding_id=d.get("embedding_id", ""),
            cluster_id=d.get("cluster_id", -1),
        )
        for d in cached.documents
    ]

    document_positions = {(d["x"], d["y"]) for d in cached.documents}
    cluster_centers = set(cached.clusters)

    grid_data = GridData(
        document_positions=document_positions,
        cluster_centers=cluster_centers,
        allocations=cached.allocations,
        points=points,
        method=cached.projection_method,
        n_documents=cached.n_documents,
        coverage=len(document_positions) / (19 * 19),
        raw_embeddings=raw_embeddings,
        embedding_to_grid=embedding_to_grid,
        grid_to_embedding=grid_to_embedding,
    )

    return grid_data
