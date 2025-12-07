"""State caching for fast TUI startup.

Supports two backends:
1. **Postgres** (preferred): Full history, queryable, shared across instances
2. **Pickle** (fallback): Local files, no external dependencies

The cache is invalidated when:
- Embedding model changes
- KB content changes significantly
- User runs /reindex or /init commands

Configuration:
    Set DATABASE_URL to enable Postgres backend.
    Falls back to pickle if Postgres unavailable.
"""

import asyncio
import json
import os
import pickle
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .projection import GridData
from .tda import TDAFeatures

if TYPE_CHECKING:
    from .iso_features import IsoFeatures

# Cache schema version (increment when format changes)
# v2: Added iso.pkl for IsoFeatures
# v3: Added Postgres backend
CACHE_VERSION = 3


def _use_postgres() -> bool:
    """Check if Postgres backend should be used."""
    # Use Postgres if DATABASE_URL is set and not explicitly disabled
    if os.getenv("GAIUS_CACHE_BACKEND", "auto") == "pickle":
        return False
    return bool(os.getenv("DATABASE_URL"))


def get_cache_dir(kb_root: Path | str) -> Path:
    """Get cache directory for a KB root."""
    kb_path = Path(kb_root)
    cache_dir = kb_path / ".cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def get_cache_metadata_path(kb_root: Path | str) -> Path:
    """Get path to cache metadata file."""
    return get_cache_dir(kb_root) / "state.json"


def get_cache_grid_path(kb_root: Path | str) -> Path:
    """Get path to cached grid data (pickle for numpy arrays)."""
    return get_cache_dir(kb_root) / "grid.pkl"


def get_cache_tda_path(kb_root: Path | str) -> Path:
    """Get path to cached TDA features."""
    return get_cache_dir(kb_root) / "tda.pkl"


def get_cache_iso_path(kb_root: Path | str) -> Path:
    """Get path to cached IsoFeatures."""
    return get_cache_dir(kb_root) / "iso.pkl"


def save_cached_state(
    kb_root: Path | str,
    grid_data: GridData,
    tda_features: TDAFeatures,
    embedding_model: str,
    projection_method: str,
    embedding_type: str = "single",
    iso_features: "IsoFeatures | None" = None,
) -> None:
    """Save computed state to cache.

    Uses Postgres if DATABASE_URL is set, otherwise falls back to pickle files.

    Args:
        kb_root: KB root directory
        grid_data: Computed grid projection
        tda_features: Computed TDA features
        embedding_model: Model used for embeddings
        projection_method: Projection method (umap/pca)
        embedding_type: Embedding type ("single" or "multi")
        iso_features: Pre-computed IsoFeatures from TDA on multi-vectors
    """
    kb_root_str = str(kb_root)

    # Try Postgres first
    if _use_postgres():
        try:
            from ..storage.grid_state import save_grid_state, ensure_schema

            # Run async save
            loop = asyncio.new_event_loop()
            try:
                # Ensure schema exists
                loop.run_until_complete(ensure_schema())
                # Save to Postgres
                snapshot_id = loop.run_until_complete(
                    save_grid_state(
                        kb_root=kb_root_str,
                        grid_data=grid_data,
                        tda_features=tda_features,
                        embedding_model=embedding_model,
                        projection_method=projection_method,
                        embedding_type=embedding_type,
                    )
                )
                if snapshot_id:
                    # Success - also save minimal pickle for offline fallback
                    _save_pickle_fallback(kb_root, grid_data, tda_features,
                                         embedding_model, projection_method,
                                         embedding_type, iso_features)
                    return
            finally:
                loop.close()
        except Exception as e:
            print(f"Postgres save failed, falling back to pickle: {e}")

    # Fallback to pickle
    _save_pickle_cache(kb_root, grid_data, tda_features,
                       embedding_model, projection_method,
                       embedding_type, iso_features)


def _save_pickle_cache(
    kb_root: Path | str,
    grid_data: GridData,
    tda_features: TDAFeatures,
    embedding_model: str,
    projection_method: str,
    embedding_type: str = "single",
    iso_features: "IsoFeatures | None" = None,
) -> None:
    """Save state to pickle files (original implementation)."""
    cache_dir = get_cache_dir(kb_root)

    # Save metadata (JSON for readability)
    metadata = {
        "version": CACHE_VERSION,
        "timestamp": datetime.now().isoformat(),
        "embedding_model": embedding_model,
        "embedding_type": embedding_type,
        "projection_method": projection_method,
        "n_documents": grid_data.n_documents,
        "coverage": grid_data.coverage,
        "tda_h0": tda_features.h0_count,
        "tda_h1": tda_features.h1_count,
        "tda_h2": tda_features.h2_count,
        "tda_entropy": tda_features.entropy,
        "has_iso_features": iso_features is not None,
        "backend": "pickle",
    }

    with open(get_cache_metadata_path(kb_root), "w") as f:
        json.dump(metadata, f, indent=2)

    # Save grid data (pickle for numpy arrays)
    with open(get_cache_grid_path(kb_root), "wb") as f:
        pickle.dump(grid_data, f)

    # Save TDA features
    with open(get_cache_tda_path(kb_root), "wb") as f:
        pickle.dump(tda_features, f)

    # Save IsoFeatures if available
    if iso_features is not None:
        with open(get_cache_iso_path(kb_root), "wb") as f:
            pickle.dump(iso_features, f)


def _save_pickle_fallback(
    kb_root: Path | str,
    grid_data: GridData,
    tda_features: TDAFeatures,
    embedding_model: str,
    projection_method: str,
    embedding_type: str = "single",
    iso_features: "IsoFeatures | None" = None,
) -> None:
    """Save minimal pickle cache as offline fallback after Postgres save."""
    # Just save metadata indicating Postgres is primary
    cache_dir = get_cache_dir(kb_root)
    metadata = {
        "version": CACHE_VERSION,
        "timestamp": datetime.now().isoformat(),
        "embedding_model": embedding_model,
        "embedding_type": embedding_type,
        "projection_method": projection_method,
        "n_documents": grid_data.n_documents,
        "coverage": grid_data.coverage,
        "tda_h0": tda_features.h0_count,
        "tda_h1": tda_features.h1_count,
        "tda_h2": tda_features.h2_count,
        "tda_entropy": tda_features.entropy,
        "has_iso_features": iso_features is not None,
        "backend": "postgres",  # Mark that Postgres is primary
    }

    with open(get_cache_metadata_path(kb_root), "w") as f:
        json.dump(metadata, f, indent=2)

    # Also save full pickle as fallback for offline use
    _save_pickle_cache(kb_root, grid_data, tda_features,
                       embedding_model, projection_method,
                       embedding_type, iso_features)


def load_cached_state(
    kb_root: Path | str,
) -> tuple[GridData | None, TDAFeatures | None, dict | None, "IsoFeatures | None"]:
    """Load cached state if available.

    Tries Postgres first if DATABASE_URL is set, then falls back to pickle.

    Returns:
        Tuple of (grid_data, tda_features, metadata, iso_features).
        Returns (None, None, None, None) if cache invalid.
    """
    kb_root_str = str(kb_root)

    # Try Postgres first
    if _use_postgres():
        try:
            from ..storage.grid_state import load_current_grid_state

            loop = asyncio.new_event_loop()
            try:
                grid_data, tda_features, metadata = loop.run_until_complete(
                    load_current_grid_state(kb_root_str)
                )
                if grid_data is not None and tda_features is not None:
                    # Postgres doesn't store IsoFeatures yet, try loading from pickle
                    iso_features = _load_iso_features(kb_root)
                    return grid_data, tda_features, metadata, iso_features
            finally:
                loop.close()
        except Exception as e:
            print(f"Postgres load failed, falling back to pickle: {e}")

    # Fallback to pickle
    return _load_pickle_cache(kb_root)


def _load_iso_features(kb_root: Path | str) -> "IsoFeatures | None":
    """Load IsoFeatures from pickle if available."""
    iso_path = get_cache_iso_path(kb_root)
    if iso_path.exists():
        try:
            with open(iso_path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    return None


def _load_pickle_cache(
    kb_root: Path | str,
) -> tuple[GridData | None, TDAFeatures | None, dict | None, "IsoFeatures | None"]:
    """Load state from pickle files (original implementation)."""
    try:
        metadata_path = get_cache_metadata_path(kb_root)
        grid_path = get_cache_grid_path(kb_root)
        tda_path = get_cache_tda_path(kb_root)
        iso_path = get_cache_iso_path(kb_root)

        # Check required files exist
        if not (metadata_path.exists() and grid_path.exists() and tda_path.exists()):
            return None, None, None, None

        # Load metadata
        with open(metadata_path) as f:
            metadata = json.load(f)

        # Check version (accept both v2 pickle and v3 postgres-backed pickle)
        version = metadata.get("version", 0)
        if version < 2:  # Too old
            return None, None, None, None

        # Load pickled data
        with open(grid_path, "rb") as f:
            grid_data = pickle.load(f)

        with open(tda_path, "rb") as f:
            tda_features = pickle.load(f)

        # Load IsoFeatures if available
        iso_features = None
        if iso_path.exists():
            try:
                with open(iso_path, "rb") as f:
                    iso_features = pickle.load(f)
            except Exception:
                pass  # IsoFeatures optional, continue without

        return grid_data, tda_features, metadata, iso_features

    except Exception:
        # Any error loading cache -> invalidate
        return None, None, None, None


def invalidate_cache(kb_root: Path | str) -> None:
    """Delete cached state files."""
    try:
        cache_dir = get_cache_dir(kb_root)
        for path in cache_dir.glob("*"):
            if path.is_file():
                path.unlink()
    except Exception:
        pass  # Best effort


def check_cache_validity(
    kb_root: Path | str,
    current_embedding_model: str,
    current_projection_method: str,
    current_embedding_type: str = "single",
) -> bool:
    """Check if cache is valid for current config.

    Checks Postgres first if available, then falls back to pickle metadata.

    Args:
        kb_root: KB root directory
        current_embedding_model: Current embedding model from config
        current_projection_method: Current projection method from config
        current_embedding_type: Current embedding type ("single" or "multi")

    Returns:
        True if cache matches current config
    """
    kb_root_str = str(kb_root)

    # Check Postgres first
    if _use_postgres():
        try:
            from ..storage.grid_state import check_state_exists

            loop = asyncio.new_event_loop()
            try:
                exists = loop.run_until_complete(
                    check_state_exists(
                        kb_root_str,
                        current_embedding_model,
                        current_projection_method,
                    )
                )
                if exists:
                    return True
            finally:
                loop.close()
        except Exception:
            pass  # Fall through to pickle check

    # Fallback: check pickle metadata
    try:
        metadata_path = get_cache_metadata_path(kb_root)
        if not metadata_path.exists():
            return False

        with open(metadata_path) as f:
            metadata = json.load(f)

        # Check version (accept v2 and v3)
        version = metadata.get("version", 0)
        if version < 2:
            return False

        # Check config matches
        if metadata.get("embedding_model") != current_embedding_model:
            return False

        if metadata.get("projection_method") != current_projection_method:
            return False

        # Check embedding type (critical for single vs multi)
        if metadata.get("embedding_type", "single") != current_embedding_type:
            return False

        return True

    except Exception:
        return False
