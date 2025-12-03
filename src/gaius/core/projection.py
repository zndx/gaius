"""Projection pipeline for mapping embeddings to 19x19 grid.

Transforms high-dimensional embeddings from Qdrant into 2D coordinates
suitable for display on the Gaius grid. Supports UMAP and PCA projections.

Usage:
    from gaius.core.projection import GridProjector, GridData

    projector = GridProjector(method="umap")
    grid_data = await projector.project_kb()

    # Use in app
    state.allocations = grid_data.allocations
    state.black_stones = grid_data.document_positions
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

# Import vector search directly to avoid bm25s dependency chain
try:
    from ..inference.search.vector import VectorSearch, get_vector_search
except ImportError:
    # Fallback: define minimal stubs if dependencies missing
    VectorSearch = None
    get_vector_search = None


@dataclass
class GridPoint:
    """A point on the 19x19 grid."""

    x: int  # 0-18
    y: int  # 0-18
    path: str  # KB document path
    title: str
    embedding_id: str
    cluster_id: int = -1  # TDA cluster assignment


@dataclass
class GridData:
    """Complete grid state derived from embeddings.

    Replaces static GRID_DATA with real projected data.
    """

    # Document positions on grid (as set of (x, y) tuples)
    document_positions: set[tuple[int, int]] = field(default_factory=set)

    # Cluster positions (different color from documents)
    cluster_centers: set[tuple[int, int]] = field(default_factory=set)

    # Allocation intensity (19x19 array, 0-100)
    allocations: list[list[int]] = field(default_factory=list)

    # Full point data for detailed inspection
    points: list[GridPoint] = field(default_factory=list)

    # Projection metadata
    method: str = "umap"
    n_documents: int = 0
    coverage: float = 0.0  # Fraction of grid cells with documents

    # Raw embeddings for TDA computation (768-dim, not 2D projections)
    raw_embeddings: np.ndarray | None = None

    # Mapping from embedding index to grid position
    embedding_to_grid: dict[int, tuple[int, int]] = field(default_factory=dict)

    # Reverse mapping: grid position to embedding index (for mini-grids)
    grid_to_embedding: dict[tuple[int, int], int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.allocations:
            self.allocations = [[0] * 19 for _ in range(19)]


class GridProjector:
    """Projects high-dimensional embeddings onto 19x19 grid.

    Pipeline:
    1. Retrieve embeddings from Qdrant
    2. Apply dimensionality reduction (UMAP/PCA)
    3. Normalize to [0, 18] range
    4. Quantize to integer grid coordinates
    5. Compute density allocations
    """

    GRID_SIZE = 19

    def __init__(
        self,
        method: Literal["umap", "pca"] = "umap",
        kb_root: Path | str | None = None,
    ):
        """Initialize projector.

        Args:
            method: Projection method ("umap" or "pca")
            kb_root: KB root directory
        """
        self.method = method
        self.vector_search = get_vector_search(kb_root) if get_vector_search else None

        # Lazy-loaded projector
        self._projector = None
        self._fitted = False

    def _get_projector(self):
        """Get or create the dimensionality reduction model."""
        if self._projector is not None:
            return self._projector

        if self.method == "umap":
            try:
                from umap import UMAP

                self._projector = UMAP(
                    n_components=2,
                    n_neighbors=15,
                    min_dist=0.1,
                    metric="cosine",
                    random_state=42,
                )
            except ImportError:
                # Fall back to PCA if UMAP not available
                from sklearn.decomposition import PCA

                self._projector = PCA(n_components=2, random_state=42)
                self.method = "pca"
        else:
            from sklearn.decomposition import PCA

            self._projector = PCA(n_components=2, random_state=42)

        return self._projector

    def project_kb(self) -> GridData:
        """Project all KB embeddings to grid.

        Returns:
            GridData with positions, allocations, and raw embeddings for TDA
        """
        # Retrieve embeddings from Qdrant
        embeddings, metadata = self._retrieve_embeddings()

        if len(embeddings) == 0:
            return GridData(method=self.method)

        # Project to 2D
        coords_2d = self._project_to_2d(embeddings)

        # Normalize to grid coordinates
        grid_coords = self._normalize_to_grid(coords_2d)

        # Build grid data with raw embeddings preserved for TDA
        return self._build_grid_data(grid_coords, metadata, embeddings)

    def project_points(
        self,
        embeddings: np.ndarray,
        metadata: list[dict],
    ) -> GridData:
        """Project arbitrary embeddings to grid.

        Args:
            embeddings: Array of shape (n, dim)
            metadata: List of dicts with path, title, id

        Returns:
            GridData with positions and raw embeddings for TDA
        """
        if len(embeddings) == 0:
            return GridData(method=self.method)

        coords_2d = self._project_to_2d(embeddings)
        grid_coords = self._normalize_to_grid(coords_2d)
        return self._build_grid_data(grid_coords, metadata, embeddings)

    def _retrieve_embeddings(self) -> tuple[np.ndarray, list[dict]]:
        """Retrieve all embeddings from Qdrant.

        For multi-vector embeddings, fetches aggregated vectors ("agg" named vector).
        For single-vector embeddings, fetches default vector.
        """
        if self.vector_search is None:
            return np.array([]), []

        try:
            client = self.vector_search.client
            collection = self.vector_search.collection_name

            # Check collection exists and has points
            try:
                info = client.get_collection(collection)
                if info.points_count == 0:
                    return np.array([]), []
            except Exception:
                return np.array([]), []

            # Determine embedding type from config
            embedding_type = "single"  # Default
            try:
                from .config import get_config

                config = get_config()
                embedding_type = getattr(config.vector_store, "embedding_type", "single")
            except Exception:
                pass  # Use default

            # Scroll through all points
            all_embeddings = []
            all_metadata = []

            offset = None
            batch_size = 100

            # Configure which vectors to fetch
            if embedding_type == "multi":
                # Multi-vector: fetch "agg" named vector
                with_vectors = ["agg"]
            else:
                # Single-vector: fetch default vector
                with_vectors = True

            while True:
                results, offset = client.scroll(
                    collection_name=collection,
                    limit=batch_size,
                    offset=offset,
                    with_vectors=with_vectors,
                    with_payload=True,
                )

                if not results:
                    break

                for point in results:
                    # Extract vector based on type
                    if embedding_type == "multi":
                        # Named vectors: point.vector is a dict
                        vector = point.vector.get("agg") if point.vector else None
                    else:
                        # Single vector: point.vector is a list
                        vector = point.vector

                    if vector is not None:
                        all_embeddings.append(vector)
                        payload = point.payload or {}
                        all_metadata.append(
                            {
                                "path": payload.get("path", ""),
                                "title": payload.get("title", ""),
                                "chunk_id": payload.get("chunk_id", ""),
                            }
                        )

                if offset is None:
                    break

            if all_embeddings:
                return np.array(all_embeddings), all_metadata
            return np.array([]), []

        except Exception:
            return np.array([]), []

    def _project_to_2d(self, embeddings: np.ndarray) -> np.ndarray:
        """Project embeddings to 2D using UMAP or PCA."""
        if len(embeddings) < 2:
            # Not enough points for projection
            return np.array([[9, 9]] * len(embeddings))

        projector = self._get_projector()

        # Fit and transform
        if not self._fitted:
            coords_2d = projector.fit_transform(embeddings)
            self._fitted = True
        else:
            # If already fitted, just transform
            if hasattr(projector, "transform"):
                coords_2d = projector.transform(embeddings)
            else:
                coords_2d = projector.fit_transform(embeddings)

        return coords_2d

    def _normalize_to_grid(self, coords_2d: np.ndarray) -> np.ndarray:
        """Normalize 2D coordinates to [0, 18] grid range."""
        if len(coords_2d) == 0:
            return np.array([])

        # Get min/max for normalization
        x_min, x_max = coords_2d[:, 0].min(), coords_2d[:, 0].max()
        y_min, y_max = coords_2d[:, 1].min(), coords_2d[:, 1].max()

        # Avoid division by zero
        x_range = x_max - x_min if x_max > x_min else 1.0
        y_range = y_max - y_min if y_max > y_min else 1.0

        # Normalize to [0, 18]
        normalized = np.zeros_like(coords_2d)
        normalized[:, 0] = (coords_2d[:, 0] - x_min) / x_range * 18
        normalized[:, 1] = (coords_2d[:, 1] - y_min) / y_range * 18

        # Quantize to integers
        grid_coords = np.clip(np.round(normalized), 0, 18).astype(int)

        return grid_coords

    def _build_grid_data(
        self,
        grid_coords: np.ndarray,
        metadata: list[dict],
        embeddings: np.ndarray | None = None,
    ) -> GridData:
        """Build GridData from projected coordinates.

        Args:
            grid_coords: 2D grid coordinates (n, 2) in [0, 18] range
            metadata: List of dicts with path, title, chunk_id
            embeddings: Optional raw high-dim embeddings for TDA computation
        """
        grid_data = GridData(method=self.method, n_documents=len(metadata))

        # Store raw embeddings for TDA (768-dim, not 2D projections)
        grid_data.raw_embeddings = embeddings

        # Track density per cell
        density = np.zeros((19, 19), dtype=int)

        # Build points, positions, and embedding-to-grid mapping
        for i, (x, y) in enumerate(grid_coords):
            meta = metadata[i] if i < len(metadata) else {}

            point = GridPoint(
                x=int(x),
                y=int(y),
                path=meta.get("path", ""),
                title=meta.get("title", ""),
                embedding_id=meta.get("chunk_id", ""),
            )
            grid_data.points.append(point)
            grid_data.document_positions.add((int(x), int(y)))
            grid_data.embedding_to_grid[i] = (int(x), int(y))
            grid_data.grid_to_embedding[(int(x), int(y))] = i  # Reverse mapping
            density[y, x] += 1

        # Convert density to allocation (0-100 scale)
        if density.max() > 0:
            normalized_density = density / density.max() * 100
            grid_data.allocations = normalized_density.astype(int).tolist()

        # Calculate coverage
        non_empty_cells = np.sum(density > 0)
        grid_data.coverage = non_empty_cells / (19 * 19)

        return grid_data


class GridDataManager:
    """Manages grid data lifecycle and caching.

    Coordinates between VectorSearch, GridProjector, and app state.
    """

    def __init__(
        self,
        method: Literal["umap", "pca"] = "umap",
        kb_root: Path | str | None = None,
    ):
        self.projector = GridProjector(method=method, kb_root=kb_root)
        self.vector_search = get_vector_search(kb_root) if get_vector_search else None
        self._cached_data: GridData | None = None
        self._cache_valid = False

    def get_grid_data(self, force_refresh: bool = False) -> GridData:
        """Get current grid data, using cache if valid.

        Args:
            force_refresh: If True, bypass cache and recompute

        Returns:
            GridData with current projections
        """
        if self._cached_data is not None and self._cache_valid and not force_refresh:
            return self._cached_data

        self._cached_data = self.projector.project_kb()
        self._cache_valid = True
        return self._cached_data

    def invalidate_cache(self) -> None:
        """Mark cache as invalid (e.g., after KB changes)."""
        self._cache_valid = False

    def reindex_and_project(self) -> GridData:
        """Reindex KB and project to grid.

        Call when KB content has changed.
        """
        # Reindex KB to Qdrant
        if self.vector_search is not None:
            self.vector_search.index_kb()

        # Force projection refresh
        self._cache_valid = False
        return self.get_grid_data(force_refresh=True)

    def project_query(self, query: str) -> tuple[int, int] | None:
        """Project a query to grid coordinates.

        Useful for showing where a search query would land.

        Args:
            query: Search query text

        Returns:
            Grid coordinates (x, y) or None if projection fails
        """
        if self.vector_search is None:
            return None

        try:
            # Embed the query
            embedding = self.vector_search.model.encode(
                query, show_progress_bar=False
            )

            # If we have fitted projector, use it
            if self.projector._fitted and self.projector._projector is not None:
                coords_2d = self.projector._projector.transform([embedding])
                grid_coords = self.projector._normalize_to_grid(coords_2d)
                return (int(grid_coords[0, 0]), int(grid_coords[0, 1]))

            return None
        except Exception:
            return None


# Module-level singleton
_grid_manager: GridDataManager | None = None


def get_grid_manager(
    method: Literal["umap", "pca"] = "umap",
    kb_root: Path | str | None = None,
) -> GridDataManager:
    """Get or create grid data manager singleton."""
    global _grid_manager
    if _grid_manager is None:
        _grid_manager = GridDataManager(method=method, kb_root=kb_root)
    return _grid_manager
