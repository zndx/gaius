"""TDA compute service for the engine.

Wraps the core TDA module for IPC-based computation requests,
enabling distributed TDA computation and caching.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TDARequest:
    """Request for TDA computation.

    Attributes:
        request_id: Unique request identifier
        embeddings: High-dimensional embeddings (n, dim)
        grid_coords: Optional grid coordinates (n, 2)
        max_dimension: Maximum homology dimension
        force_refresh: Bypass cache
    """

    request_id: str
    embeddings: np.ndarray
    grid_coords: Optional[np.ndarray] = None
    max_dimension: int = 2
    force_refresh: bool = False


@dataclass
class TDAResult:
    """Result of TDA computation.

    Serializable result for IPC transport.
    """

    request_id: str
    success: bool = True
    error: Optional[str] = None

    # Feature counts
    h0_count: int = 0
    h1_count: int = 0
    h2_count: int = 0
    entropy: float = 0.0

    # Bounding boxes (serialized)
    h1_cycles: list[tuple[int, int, int, int]] = field(default_factory=list)
    h2_voids: list[tuple[int, int, int, int]] = field(default_factory=list)

    # Risk scores per point
    risk_scores: list[float] = field(default_factory=list)

    # Metadata
    n_points: int = 0
    computation_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "request_id": self.request_id,
            "success": self.success,
            "error": self.error,
            "h0_count": self.h0_count,
            "h1_count": self.h1_count,
            "h2_count": self.h2_count,
            "entropy": self.entropy,
            "h1_cycles": self.h1_cycles,
            "h2_voids": self.h2_voids,
            "risk_scores": self.risk_scores,
            "n_points": self.n_points,
            "computation_ms": self.computation_ms,
        }


class TDAService:
    """TDA computation service.

    Provides TDA computation for the engine with caching
    and request tracking.
    """

    def __init__(self, max_dimension: int = 2, cache_size: int = 10):
        """Initialize TDA service.

        Args:
            max_dimension: Maximum homology dimension
            cache_size: Number of results to cache
        """
        self.max_dimension = max_dimension
        self._cache_size = cache_size

        # Lazy import TDA computer
        self._computer = None

        # Result cache (keyed by data hash)
        self._cache: dict[str, TDAResult] = {}
        self._cache_order: list[str] = []

        # Stats
        self._total_requests = 0
        self._cache_hits = 0

        logger.info("TDAService initialized")

    def _get_computer(self):
        """Lazy load TDA computer."""
        if self._computer is None:
            try:
                from gaius.core.tda import TDAComputer

                self._computer = TDAComputer(max_dimension=self.max_dimension)
            except ImportError:
                logger.warning("TDA module not available")
                return None
        return self._computer

    def compute(self, request: TDARequest) -> TDAResult:
        """Compute TDA features.

        Args:
            request: TDA computation request

        Returns:
            TDAResult with computed features
        """
        self._total_requests += 1
        start_time = datetime.now()

        # Check cache (simple hash of embeddings shape and sample)
        cache_key = self._compute_cache_key(request.embeddings)
        if not request.force_refresh and cache_key in self._cache:
            self._cache_hits += 1
            result = self._cache[cache_key]
            result.request_id = request.request_id
            return result

        try:
            computer = self._get_computer()
            if computer is None:
                return TDAResult(
                    request_id=request.request_id,
                    success=False,
                    error="TDA module not available",
                )

            # Compute TDA
            features = computer.compute(
                request.embeddings,
                request.grid_coords,
            )

            # Build result
            result = TDAResult(
                request_id=request.request_id,
                success=True,
                h0_count=features.h0_count,
                h1_count=features.h1_count,
                h2_count=features.h2_count,
                entropy=features.entropy,
                h1_cycles=[dl.to_tuple() for dl in features.h1_cycles],
                h2_voids=[v.to_tuple() for v in features.h2_voids],
                risk_scores=features.risk_scores,
                n_points=features.n_points,
            )

            # Compute time
            elapsed = datetime.now() - start_time
            result.computation_ms = int(elapsed.total_seconds() * 1000)

            # Update cache
            self._update_cache(cache_key, result)

            return result

        except Exception as e:
            logger.error(f"TDA computation failed: {e}")
            return TDAResult(
                request_id=request.request_id,
                success=False,
                error=str(e),
            )

    def _compute_cache_key(self, embeddings: np.ndarray) -> str:
        """Compute cache key from embeddings."""
        # Use shape + sample of values for fast hashing
        shape_str = f"{embeddings.shape}"
        sample = embeddings.flat[::max(1, len(embeddings.flat) // 10)]
        sample_str = str(hash(sample.tobytes()))
        return f"{shape_str}_{sample_str}"

    def _update_cache(self, key: str, result: TDAResult) -> None:
        """Update cache with LRU eviction."""
        if key in self._cache:
            # Move to end
            self._cache_order.remove(key)
            self._cache_order.append(key)
        else:
            # Add new entry
            if len(self._cache) >= self._cache_size:
                # Evict oldest
                oldest = self._cache_order.pop(0)
                del self._cache[oldest]

            self._cache[key] = result
            self._cache_order.append(key)

    def get_status(self) -> dict[str, Any]:
        """Get service status."""
        return {
            "computer_available": self._computer is not None or self._get_computer() is not None,
            "max_dimension": self.max_dimension,
            "cache_size": self._cache_size,
            "cache_entries": len(self._cache),
            "total_requests": self._total_requests,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": (
                self._cache_hits / max(1, self._total_requests)
            ),
        }

    def clear_cache(self) -> None:
        """Clear the result cache."""
        self._cache.clear()
        self._cache_order.clear()
