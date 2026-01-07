"""State caching for fast TUI startup.

Uses Postgres for persistent, queryable grid state storage.
Requires DATABASE_URL to be set - cache is disabled if not configured.

The cache is invalidated when:
- Embedding model changes
- KB content changes significantly
- User runs /reindex or /init commands
"""

import logging
import os
from typing import TYPE_CHECKING

from .projection import GridData
from .tda import TDAFeatures

if TYPE_CHECKING:
    from .iso_features import IsoFeatures

logger = logging.getLogger(__name__)

# Cache schema version (increment when format changes)
CACHE_VERSION = 4  # v4: Postgres-only, removed pickle


def _use_cache() -> bool:
    """Check if caching is enabled.

    Requires DATABASE_URL to be set.
    """
    if not os.getenv("DATABASE_URL"):
        logger.debug("Cache disabled - DATABASE_URL not set")
        return False
    return True


async def save_cached_state_async(
    kb_root: str,
    grid_data: GridData,
    tda_features: TDAFeatures,
    embedding_model: str,
    projection_method: str,
    embedding_type: str = "single",
    iso_features: "IsoFeatures | None" = None,
) -> int | None:
    """Save computed state to Postgres cache (async).

    Args:
        kb_root: KB root directory
        grid_data: Computed grid projection
        tda_features: Computed TDA features
        embedding_model: Model used for embeddings
        projection_method: Projection method (umap/pca)
        embedding_type: Embedding type ("single" or "multi")
        iso_features: Pre-computed IsoFeatures (not yet stored in Postgres)

    Returns:
        Snapshot ID if saved successfully, None otherwise.
    """
    if not _use_cache():
        return None

    try:
        from ..storage.grid_state import save_grid_state, ensure_schema

        await ensure_schema()
        snapshot_id = await save_grid_state(
            kb_root=kb_root,
            grid_data=grid_data,
            tda_features=tda_features,
            embedding_model=embedding_model,
            projection_method=projection_method,
            embedding_type=embedding_type,
        )
        logger.debug(f"Saved grid state to Postgres: {snapshot_id}")
        return snapshot_id
    except Exception as e:
        logger.warning(f"Failed to save cache to Postgres: {e}")
        return None


async def load_cached_state_async(
    kb_root: str,
) -> tuple[GridData | None, TDAFeatures | None, dict | None, "IsoFeatures | None"]:
    """Load cached state from Postgres (async).

    Returns:
        Tuple of (grid_data, tda_features, metadata, iso_features).
        Returns (None, None, None, None) if cache unavailable.
    """
    if not _use_cache():
        return None, None, None, None

    try:
        from ..storage.grid_state import load_current_grid_state

        grid_data, tda_features, metadata = await load_current_grid_state(kb_root)
        if grid_data is not None and tda_features is not None and metadata is not None:
            logger.debug(f"Loaded grid state from Postgres: {metadata.get('snapshot_id', 'unknown')}")
            # IsoFeatures not yet stored in Postgres
            return grid_data, tda_features, metadata, None
        return None, None, None, None
    except Exception as e:
        logger.warning(f"Failed to load cache from Postgres: {e}")
        return None, None, None, None


async def check_cache_validity_async(
    kb_root: str,
    current_embedding_model: str,
    current_projection_method: str,
    current_embedding_type: str = "single",
) -> bool:
    """Check if cache is valid for current config (async).

    Args:
        kb_root: KB root directory
        current_embedding_model: Current embedding model from config
        current_projection_method: Current projection method from config
        current_embedding_type: Current embedding type ("single" or "multi")

    Returns:
        True if cache matches current config
    """
    if not _use_cache():
        return False

    try:
        from ..storage.grid_state import check_state_exists

        exists = await check_state_exists(
            kb_root,
            current_embedding_model,
            current_projection_method,
        )
        return exists
    except Exception as e:
        logger.debug(f"Cache validity check failed: {e}")
        return False


async def invalidate_cache_async(kb_root: str) -> None:
    """Invalidate cached state for a KB root (async).

    This marks the current snapshot as not current, so it won't be loaded
    on next startup.
    """
    if not _use_cache():
        return

    try:
        from ..storage.grid_state import invalidate_state

        await invalidate_state(kb_root)
        logger.debug(f"Invalidated cache for {kb_root}")
    except Exception as e:
        logger.warning(f"Failed to invalidate cache: {e}")


# Synchronous wrappers for backwards compatibility
# These only work when NOT inside an existing event loop

def save_cached_state(
    kb_root: str,
    grid_data: GridData,
    tda_features: TDAFeatures,
    embedding_model: str,
    projection_method: str,
    embedding_type: str = "single",
    iso_features: "IsoFeatures | None" = None,
) -> int | None:
    """Save computed state (sync wrapper).

    Note: This creates a new event loop. Do not call from within an async context.
    Use save_cached_state_async() instead.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
        logger.warning("save_cached_state called from async context - use save_cached_state_async()")
        return None
    except RuntimeError:
        pass  # No running loop, safe to proceed

    try:
        return asyncio.run(save_cached_state_async(
            kb_root, grid_data, tda_features,
            embedding_model, projection_method, embedding_type, iso_features
        ))
    except Exception as e:
        logger.warning(f"save_cached_state failed: {e}")
        return None


def load_cached_state(
    kb_root: str,
) -> tuple[GridData | None, TDAFeatures | None, dict | None, "IsoFeatures | None"]:
    """Load cached state (sync wrapper).

    Note: This creates a new event loop. Do not call from within an async context.
    Use load_cached_state_async() instead.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
        logger.warning("load_cached_state called from async context - use load_cached_state_async()")
        return None, None, None, None
    except RuntimeError:
        pass  # No running loop, safe to proceed

    try:
        return asyncio.run(load_cached_state_async(kb_root))
    except Exception as e:
        logger.warning(f"load_cached_state failed: {e}")
        return None, None, None, None


def check_cache_validity(
    kb_root: str,
    current_embedding_model: str,
    current_projection_method: str,
    current_embedding_type: str = "single",
) -> bool:
    """Check if cache is valid (sync wrapper).

    Note: This creates a new event loop. Do not call from within an async context.
    Use check_cache_validity_async() instead.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
        logger.warning("check_cache_validity called from async context - use check_cache_validity_async()")
        return False
    except RuntimeError:
        pass  # No running loop, safe to proceed

    try:
        return asyncio.run(check_cache_validity_async(
            kb_root, current_embedding_model, current_projection_method, current_embedding_type
        ))
    except Exception as e:
        logger.warning(f"check_cache_validity failed: {e}")
        return False


def invalidate_cache(kb_root: str) -> None:
    """Invalidate cached state (sync wrapper).

    Note: This creates a new event loop. Do not call from within an async context.
    Use invalidate_cache_async() instead.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
        logger.warning("invalidate_cache called from async context - use invalidate_cache_async()")
        return
    except RuntimeError:
        pass  # No running loop, safe to proceed

    try:
        asyncio.run(invalidate_cache_async(kb_root))
    except Exception as e:
        logger.warning(f"invalidate_cache failed: {e}")
