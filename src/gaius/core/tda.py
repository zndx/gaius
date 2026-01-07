"""Topological Data Analysis (TDA) integration for Gaius.

Uses ripser for fast persistent homology computation from embeddings,
providing topological insights displayed on the 19x19 grid.

Features:
- H0: Connected components (clustering)
- H1: Loops (death loops - important topological features)
- H2: Voids (higher-dimensional cavities)

Usage:
    from gaius.core.tda import TDAComputer, TDAFeatures

    computer = TDAComputer()
    features = computer.compute(embeddings)

    # Access results
    h1_cycles = features.h1_cycles  # List of bounding boxes (1-cycles)
    entropy = features.entropy
"""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np


@dataclass
class PersistenceInterval:
    """A persistence interval from homology computation."""

    birth: float
    death: float
    dimension: int  # 0=component, 1=loop, 2=void
    representative: list[int] = field(default_factory=list)  # Point indices

    @property
    def persistence(self) -> float:
        """Lifetime of the feature."""
        return self.death - self.birth

    @property
    def is_significant(self) -> bool:
        """Whether this feature is topologically significant."""
        return self.persistence > 0.1  # Threshold for noise


@dataclass
class BoundingBox:
    """Bounding box for a topological feature on the grid."""

    x1: int
    y1: int
    x2: int
    y2: int
    dimension: int  # Which homology group (0, 1, 2)
    persistence: float  # How persistent the feature is

    def contains(self, x: int, y: int) -> bool:
        """Check if point is inside bounding box."""
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def to_tuple(self) -> tuple[int, int, int, int]:
        """Convert to (x1, y1, x2, y2) tuple."""
        return (self.x1, self.y1, self.x2, self.y2)


@dataclass
class TDAFeatures:
    """Computed TDA features from embeddings.

    Provides topological insights for grid visualization.
    """

    # Raw persistence intervals
    intervals: list[PersistenceInterval] = field(default_factory=list)

    # Bounding boxes for visualization (TDA standard terminology)
    h1_cycles: list[BoundingBox] = field(default_factory=list)  # H1 features (1-cycles/loops)
    h2_voids: list[BoundingBox] = field(default_factory=list)   # H2 features (2-voids/cavities)
    components: list[BoundingBox] = field(default_factory=list)  # H0 features (connected components)

    # Per-point risk scores (0-1) for risk overlay
    risk_scores: list[float] = field(default_factory=list)

    # Summary statistics
    h0_count: int = 0  # Number of connected components
    h1_count: int = 0  # Number of loops
    h2_count: int = 0  # Number of voids
    entropy: float = 0.0  # Persistence entropy
    persistence_range: tuple[float, float] = (0.0, 1.0)

    # Computation metadata
    n_points: int = 0
    method: str = "rips"

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "h0_count": self.h0_count,
            "h1_count": self.h1_count,
            "h2_count": self.h2_count,
            "entropy": self.entropy,
            "persistence_range": self.persistence_range,
            "n_points": self.n_points,
            "h1_cycles": [dl.to_tuple() for dl in self.h1_cycles],
            "h2_voids": [v.to_tuple() for v in self.h2_voids],
            "risk_scores": self.risk_scores,
        }


class TDAComputer:
    """Computes TDA features from embeddings.

    Uses giotto-tda for persistence homology computation.
    Falls back to simplified computation if giotto-tda unavailable.
    """

    def __init__(
        self,
        max_dimension: int = 2,
        max_edge_length: float = float("inf"),
        method: Literal["rips", "alpha"] = "rips",
    ):
        """Initialize TDA computer.

        Args:
            max_dimension: Maximum homology dimension (0, 1, or 2)
            max_edge_length: Maximum edge length for filtration
            method: Filtration method ("rips" or "alpha")
        """
        self.max_dimension = max_dimension
        self.max_edge_length = max_edge_length
        self.method = method

        # Lazy check for ripser - don't import until needed (import takes ~1s)
        self._ripser_available: bool | None = None

    @property
    def ripser_available(self) -> bool:
        """Check if ripser is installed (lazy, cached)."""
        if self._ripser_available is None:
            self._ripser_available = self._check_ripser()
        return self._ripser_available

    def _check_ripser(self) -> bool:
        """Check if ripser is installed."""
        try:
            import ripser

            return True
        except ImportError:
            return False

    def compute(
        self,
        embeddings: np.ndarray,
        grid_coords: np.ndarray | None = None,
    ) -> TDAFeatures:
        """Compute TDA features from embeddings.

        Args:
            embeddings: Array of shape (n, dim) - high-dimensional embeddings
            grid_coords: Optional (n, 2) array of grid coordinates for bounding boxes

        Returns:
            TDAFeatures with computed topological features
        """
        if len(embeddings) < 3:
            return TDAFeatures(n_points=len(embeddings))

        if self.ripser_available:
            return self._compute_ripser(embeddings, grid_coords)
        else:
            return self._compute_fallback(embeddings, grid_coords)

    def _compute_ripser(
        self,
        embeddings: np.ndarray,
        grid_coords: np.ndarray | None,
    ) -> TDAFeatures:
        """Compute TDA using ripser (fast persistent homology).

        Subsamples if dataset is too large (ripser is O(n^3) worst case).
        """
        import ripser

        n_points = len(embeddings)
        features = TDAFeatures(n_points=n_points, method=self.method)

        try:
            # Subsample if too many points (TDA is expensive)
            from .config import get_config
            max_points = get_config().tda.max_points

            if n_points > max_points:
                # Random sample for diversity
                indices = np.random.choice(n_points, max_points, replace=False)
                sampled_embeddings = embeddings[indices]
                sampled_coords = grid_coords[indices] if grid_coords is not None else None
            else:
                sampled_embeddings = embeddings
                sampled_coords = grid_coords
                indices = np.arange(n_points)

            # Compute persistent homology using ripser
            # ripser expects (n_points, n_features) array
            # Returns {'dgms': [H0_diagram, H1_diagram, H2_diagram, ...]}
            result = ripser.ripser(
                sampled_embeddings,
                maxdim=self.max_dimension,
                thresh=self.max_edge_length if self.max_edge_length != np.inf else 0,
                metric="cosine",  # Use cosine distance for embeddings
            )

            diagrams = result['dgms']  # List of (n, 2) arrays: [(birth, death), ...]

            # Parse persistence diagrams into intervals
            intervals = []
            for dim, diagram in enumerate(diagrams):
                for birth, death in diagram:
                    if np.isfinite(death):  # Skip infinite death times
                        intervals.append(
                            PersistenceInterval(
                                birth=float(birth),
                                death=float(death),
                                dimension=int(dim),
                            )
                        )

            features.intervals = intervals

            # Count features by dimension
            features.h0_count = sum(1 for i in intervals if i.dimension == 0)
            features.h1_count = sum(1 for i in intervals if i.dimension == 1)
            features.h2_count = sum(1 for i in intervals if i.dimension == 2)

            # Compute persistence entropy (simple version without giotto-tda)
            if intervals:
                persistences = np.array([i.persistence for i in intervals])
                # Normalize persistences to probabilities
                total_persistence = np.sum(persistences)
                if total_persistence > 0:
                    probs = persistences / total_persistence
                    # Shannon entropy: -Σ p*log(p)
                    features.entropy = float(-np.sum(probs * np.log(probs + 1e-10)))
                else:
                    features.entropy = 0.0
            else:
                features.entropy = 0.0

            # Compute persistence range
            if intervals:
                persistences = [i.persistence for i in intervals]
                features.persistence_range = (min(persistences), max(persistences))

            # Generate bounding boxes if grid coordinates provided (use sampled coords)
            if sampled_coords is not None:
                features.h1_cycles = self._compute_bounding_boxes(
                    intervals, sampled_coords, dimension=1
                )
                features.h2_voids = self._compute_bounding_boxes(
                    intervals, sampled_coords, dimension=2
                )

            # Compute per-point risk scores on ALL points (not just sample)
            features.risk_scores = self._compute_point_risk(embeddings)

        except Exception as e:
            # Fall back to simplified computation on error
            return self._compute_fallback(embeddings, grid_coords)

        return features

    def _compute_fallback(
        self,
        embeddings: np.ndarray,
        grid_coords: np.ndarray | None,
    ) -> TDAFeatures:
        """Simplified TDA computation without ripser.

        Uses clustering and distance analysis as approximation.
        """
        from sklearn.cluster import DBSCAN

        features = TDAFeatures(n_points=len(embeddings), method="fallback")

        try:
            # Use DBSCAN for H0 approximation (connected components)
            dbscan = DBSCAN(eps=0.5, min_samples=2, metric="cosine")
            labels = dbscan.fit_predict(embeddings)

            n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
            features.h0_count = max(1, n_clusters)

            # Approximate H1 by finding dense regions
            # This is a rough approximation - real TDA would be better
            if grid_coords is not None and len(grid_coords) >= 4:
                features.h1_cycles = self._find_dense_regions(
                    grid_coords, labels, dimension=1
                )
                features.h1_count = len(features.h1_cycles)

            # Simple entropy approximation
            if len(embeddings) > 1:
                # Use variance as entropy proxy
                variance = np.var(embeddings)
                features.entropy = float(np.log1p(variance))

            features.persistence_range = (0.1, 0.9)

            # Compute per-point risk scores
            features.risk_scores = self._compute_point_risk(embeddings)

        except Exception:
            pass

        return features

    def _compute_bounding_boxes(
        self,
        intervals: list[PersistenceInterval],
        grid_coords: np.ndarray,
        dimension: int,
    ) -> list[BoundingBox]:
        """Compute bounding boxes for features of given dimension."""
        boxes = []

        # Filter significant intervals of this dimension
        significant = [
            i for i in intervals if i.dimension == dimension and i.is_significant
        ]

        # For each significant feature, create a bounding box
        # In real TDA, we'd use representative cycles
        # Here we approximate with random regions based on persistence

        for i, interval in enumerate(significant[:5]):  # Limit to top 5
            # Create box based on point distribution
            # This is simplified - would ideally use cycle representatives
            if len(grid_coords) >= 4:
                # Sample points for bounding box
                np.random.seed(hash(f"{dimension}_{i}_{interval.persistence}") % 2**32)
                sample_size = min(4, len(grid_coords))
                indices = np.random.choice(len(grid_coords), sample_size, replace=False)
                sample = grid_coords[indices]

                x1, y1 = sample.min(axis=0)
                x2, y2 = sample.max(axis=0)

                # Ensure minimum size
                if x2 - x1 < 2:
                    x2 = min(18, x1 + 2)
                if y2 - y1 < 2:
                    y2 = min(18, y1 + 2)

                boxes.append(
                    BoundingBox(
                        x1=int(x1),
                        y1=int(y1),
                        x2=int(x2),
                        y2=int(y2),
                        dimension=dimension,
                        persistence=interval.persistence,
                    )
                )

        return boxes

    def _find_dense_regions(
        self,
        grid_coords: np.ndarray,
        labels: np.ndarray,
        dimension: int,
    ) -> list[BoundingBox]:
        """Find dense regions as H1 approximation."""
        boxes = []

        # Find clusters and their bounding boxes
        unique_labels = set(labels)
        for label in unique_labels:
            if label == -1:  # Skip noise
                continue

            mask = labels == label
            cluster_coords = grid_coords[mask]

            if len(cluster_coords) >= 3:
                x1, y1 = cluster_coords.min(axis=0)
                x2, y2 = cluster_coords.max(axis=0)

                # Only create box if it has some area
                if x2 > x1 and y2 > y1:
                    boxes.append(
                        BoundingBox(
                            x1=int(x1),
                            y1=int(y1),
                            x2=int(x2),
                            y2=int(y2),
                            dimension=dimension,
                            persistence=0.5,  # Default persistence for fallback
                        )
                    )

        return boxes[:5]  # Limit to top 5

    def _compute_point_risk(self, embeddings: np.ndarray) -> list[float]:
        """Compute per-point risk based on local topology.

        Points with more distant neighbors are less stable (higher risk).
        Uses k-NN distances as a proxy for local topological instability.

        Args:
            embeddings: High-dimensional embeddings (n, dim)

        Returns:
            List of risk scores (0-1) for each point
        """
        n_points = len(embeddings)
        if n_points < 3:
            return [0.5] * n_points

        try:
            from sklearn.neighbors import NearestNeighbors

            # Use k nearest neighbors to assess local density
            n_neighbors = min(10, n_points - 1)
            nn = NearestNeighbors(n_neighbors=n_neighbors, metric="cosine")
            nn.fit(embeddings)
            distances, _ = nn.kneighbors(embeddings)

            # Average distance to neighbors (skip self at index 0)
            avg_distances = distances[:, 1:].mean(axis=1)

            # Normalize to 0-1 range
            min_d, max_d = avg_distances.min(), avg_distances.max()
            if max_d > min_d:
                risk = (avg_distances - min_d) / (max_d - min_d)
            else:
                risk = np.full(n_points, 0.5)

            return risk.tolist()

        except Exception:
            # Fallback: uniform risk
            return [0.5] * n_points


class TDAManager:
    """Manages TDA computation lifecycle.

    Handles caching, scheduling, and integration with grid.
    """

    def __init__(self, max_dimension: int = 2):
        self.computer = TDAComputer(max_dimension=max_dimension)
        self._cached_features: TDAFeatures | None = None
        self._cache_valid = False

    def compute_features(
        self,
        embeddings: np.ndarray,
        grid_coords: np.ndarray | None = None,
        force_refresh: bool = False,
    ) -> TDAFeatures:
        """Compute TDA features, using cache if valid.

        Args:
            embeddings: High-dimensional embeddings
            grid_coords: Optional 2D grid coordinates
            force_refresh: If True, bypass cache

        Returns:
            TDAFeatures
        """
        if self._cached_features is not None and self._cache_valid and not force_refresh:
            return self._cached_features

        self._cached_features = self.computer.compute(embeddings, grid_coords)
        self._cache_valid = True
        return self._cached_features

    def invalidate_cache(self) -> None:
        """Mark cache as invalid."""
        self._cache_valid = False

    def get_h1_cycles_as_tuples(self) -> list[tuple[int, int, int, int]]:
        """Get H1 cycles (1-cycles/loops) in tuple format for compatibility."""
        if self._cached_features is None:
            return []
        return [cycle.to_tuple() for cycle in self._cached_features.h1_cycles]

    def get_metrics(self) -> dict:
        """Get TDA metrics for status display."""
        if self._cached_features is None:
            return {
                "entropy": 0.0,
                "h0_count": 0,
                "h1_count": 0,
                "h2_count": 0,
                "persistence_range": (0.0, 1.0),
            }
        return self._cached_features.to_dict()


# Module-level singleton
_tda_manager: TDAManager | None = None


def get_tda_manager() -> TDAManager:
    """Get or create TDA manager singleton."""
    global _tda_manager
    if _tda_manager is None:
        _tda_manager = TDAManager()
    return _tda_manager
