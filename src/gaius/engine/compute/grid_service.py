"""Grid projection compute service for the engine.

Wraps the core projection module for IPC-based grid computation,
enabling distributed UMAP/PCA projections.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GridPoint:
    """A point on the 19x19 grid."""

    x: int
    y: int
    path: str = ""
    title: str = ""
    embedding_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "x": self.x,
            "y": self.y,
            "path": self.path,
            "title": self.title,
            "embedding_id": self.embedding_id,
        }


@dataclass
class ProjectionRequest:
    """Request for grid projection.

    Attributes:
        request_id: Unique request identifier
        embeddings: High-dimensional embeddings (n, dim)
        metadata: List of metadata dicts for each embedding
        method: Projection method (umap or pca)
        force_refresh: Bypass fitted projector
    """

    request_id: str
    embeddings: np.ndarray
    metadata: list[dict[str, Any]] = field(default_factory=list)
    method: Literal["umap", "pca"] = "umap"
    force_refresh: bool = False


@dataclass
class ProjectionResult:
    """Result of grid projection.

    Serializable result for IPC transport.
    """

    request_id: str
    success: bool = True
    error: Optional[str] = None

    # Projected points
    points: list[dict[str, Any]] = field(default_factory=list)
    document_positions: list[tuple[int, int]] = field(default_factory=list)

    # Grid allocations (19x19 density)
    allocations: list[list[int]] = field(default_factory=list)

    # Mappings
    embedding_to_grid: dict[int, tuple[int, int]] = field(default_factory=dict)

    # Stats
    n_documents: int = 0
    coverage: float = 0.0
    method: str = "umap"
    computation_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "request_id": self.request_id,
            "success": self.success,
            "error": self.error,
            "points": self.points,
            "document_positions": self.document_positions,
            "allocations": self.allocations,
            "n_documents": self.n_documents,
            "coverage": self.coverage,
            "method": self.method,
            "computation_ms": self.computation_ms,
        }


class GridService:
    """Grid projection computation service.

    Provides UMAP/PCA projection for the engine with
    fitted projector caching.
    """

    def __init__(self, method: Literal["umap", "pca"] = "umap"):
        """Initialize grid service.

        Args:
            method: Default projection method
        """
        self.method = method

        # Lazy load projector
        self._projector = None
        self._fitted = False

        # Stats
        self._total_requests = 0
        self._total_points_projected = 0

        logger.info(f"GridService initialized with method={method}")

    def _get_projector(self):
        """Lazy load grid projector."""
        if self._projector is None:
            try:
                from gaius.core.projection import GridProjector

                self._projector = GridProjector(method=self.method)
            except ImportError:
                logger.warning("Projection module not available")
                return None
        return self._projector

    def project(self, request: ProjectionRequest) -> ProjectionResult:
        """Project embeddings to 19x19 grid.

        Args:
            request: Projection request

        Returns:
            ProjectionResult with grid coordinates
        """
        self._total_requests += 1
        start_time = datetime.now()

        try:
            projector = self._get_projector()
            if projector is None:
                return ProjectionResult(
                    request_id=request.request_id,
                    success=False,
                    error="Projection module not available",
                )

            # Update method if different
            if request.method != self.method:
                projector.method = request.method

            # Project embeddings
            embeddings = request.embeddings
            metadata = request.metadata or [{} for _ in range(len(embeddings))]

            if len(embeddings) == 0:
                return ProjectionResult(
                    request_id=request.request_id,
                    success=True,
                    n_documents=0,
                    method=request.method,
                )

            # Use internal projection methods (2D projection + grid normalization)
            coords_2d = projector._project_to_2d(embeddings)
            grid_coords = projector._normalize_to_grid(coords_2d)

            # Build result
            points = []
            document_positions = set()
            embedding_to_grid = {}
            density = np.zeros((19, 19), dtype=int)

            for i, (x, y) in enumerate(grid_coords):
                meta = metadata[i] if i < len(metadata) else {}
                point = GridPoint(
                    x=int(x),
                    y=int(y),
                    path=meta.get("path", ""),
                    title=meta.get("title", ""),
                    embedding_id=meta.get("chunk_id", ""),
                )
                points.append(point.to_dict())
                document_positions.add((int(x), int(y)))
                embedding_to_grid[i] = (int(x), int(y))
                density[int(y), int(x)] += 1

            # Normalize density to allocations (0-100)
            if density.max() > 0:
                allocations = (density / density.max() * 100).astype(int).tolist()
            else:
                allocations = density.tolist()

            # Compute coverage
            non_empty = np.sum(density > 0)
            coverage = non_empty / (19 * 19)

            result = ProjectionResult(
                request_id=request.request_id,
                success=True,
                points=points,
                document_positions=list(document_positions),
                allocations=allocations,
                embedding_to_grid=embedding_to_grid,
                n_documents=len(embeddings),
                coverage=coverage,
                method=request.method,
            )

            # Compute time
            elapsed = datetime.now() - start_time
            result.computation_ms = int(elapsed.total_seconds() * 1000)

            self._total_points_projected += len(embeddings)
            self._fitted = True

            return result

        except Exception as e:
            logger.error(f"Grid projection failed: {e}")
            return ProjectionResult(
                request_id=request.request_id,
                success=False,
                error=str(e),
            )

    def project_query(self, query_embedding: np.ndarray) -> Optional[tuple[int, int]]:
        """Project a single query embedding to grid.

        Only works after fit.

        Args:
            query_embedding: Single embedding vector

        Returns:
            Grid coordinates (x, y) or None
        """
        projector = self._get_projector()
        if projector is None or not self._fitted:
            return None

        try:
            coords_2d = projector._project_to_2d(query_embedding.reshape(1, -1))
            grid_coords = projector._normalize_to_grid(coords_2d)
            return (int(grid_coords[0, 0]), int(grid_coords[0, 1]))
        except Exception:
            return None

    def get_status(self) -> dict[str, Any]:
        """Get service status."""
        return {
            "projector_available": self._projector is not None,
            "fitted": self._fitted,
            "method": self.method,
            "total_requests": self._total_requests,
            "total_points_projected": self._total_points_projected,
        }

    def reset(self) -> None:
        """Reset projector (unfits)."""
        self._projector = None
        self._fitted = False
