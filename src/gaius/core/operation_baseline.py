"""EWMA-based operation baselines for anomaly detection.

Provides O(1) memory baseline tracking using Exponential Weighted Moving Average
(EWMA) for detecting anomalous operation durations. This enables adaptive timeout
detection without fixed hard timeouts.

Key concepts:
- EWMA: Exponentially weights recent observations more heavily than older ones
- Anomaly detection: Flags operations where Z-score exceeds threshold
- Cold start handling: Uses larger threshold multiplier until sufficient samples

Usage:
    from gaius.core.operation_baseline import get_baseline_registry

    registry = get_baseline_registry()
    baseline = registry.get_or_create("gpu_allocation", endpoint="reasoning")

    # Check if duration is anomalous
    if baseline.is_anomaly(current_duration):
        logger.warning(f"Anomaly detected: Z={baseline.z_score(current_duration):.2f}")

    # Update baseline after operation completes
    baseline.update(elapsed_seconds)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)

# Global singleton
_registry: BaselineRegistry | None = None
_registry_lock = threading.Lock()


@dataclass
class OperationBaseline:
    """EWMA-based baseline for anomaly detection.

    Attributes:
        operation_type: Operation identifier (e.g., "gpu_allocation")
        endpoint: Optional endpoint context (e.g., "reasoning")
        alpha: EWMA responsiveness (0-1). Higher = more weight on recent.
        mean: Current EWMA mean
        variance: Current EWMA variance
        count: Total samples observed
        sigma_threshold: Z-score threshold for anomaly detection
        min_samples: Minimum samples before detection enabled
        cold_start_multiplier: Threshold multiplier during cold start
        cold_start_samples: Samples considered "cold start"
    """

    operation_type: str
    endpoint: str = ""
    alpha: float = 0.2
    mean: float = 0.0
    variance: float = 0.0
    count: int = 0
    sigma_threshold: float = 2.0
    min_samples: int = 5
    cold_start_multiplier: float = 3.0
    cold_start_samples: int = 10
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def update(self, value: float) -> None:
        """Update EWMA mean and variance with new sample.

        Uses the EWMA formula:
            new_mean = alpha * value + (1 - alpha) * old_mean
            new_var = (1 - alpha) * (old_var + alpha * (value - old_mean)^2)

        This is a streaming update that maintains O(1) memory.
        """
        self.count += 1
        self.last_updated = datetime.utcnow()

        if self.count == 1:
            # First observation - initialize
            self.mean = value
            self.variance = 0.0
        else:
            # EWMA update
            delta = value - self.mean
            self.mean = self.alpha * value + (1 - self.alpha) * self.mean
            # Variance update per EWMA formula
            self.variance = (1 - self.alpha) * (self.variance + self.alpha * delta * delta)

        logger.debug(
            f"Baseline updated: operation={self.operation_type} endpoint={self.endpoint} "
            f"value={value:.3f}s mean={self.mean:.3f}s std={self.stddev:.3f}s count={self.count}"
        )

    @property
    def stddev(self) -> float:
        """Standard deviation of the baseline."""
        return math.sqrt(self.variance) if self.variance > 0 else 0.0

    def z_score(self, current_duration: float) -> float:
        """Calculate Z-score for a duration.

        Returns how many standard deviations the value is from the mean.
        Positive values indicate longer than average duration.
        """
        if self.stddev < 0.001:
            # Avoid division by near-zero
            return 0.0
        return (current_duration - self.mean) / self.stddev

    def get_effective_threshold(self) -> float:
        """Get the effective Z-score threshold accounting for cold start.

        During cold start (< cold_start_samples), uses a higher threshold
        to avoid false positives from insufficient data.
        """
        if self.count < self.cold_start_samples:
            return self.sigma_threshold * self.cold_start_multiplier
        return self.sigma_threshold

    def is_anomaly(self, current_duration: float) -> bool:
        """Check if current duration is anomalous (Z > threshold).

        Returns False if insufficient samples for reliable detection.
        """
        if self.count < self.min_samples:
            return False

        z = self.z_score(current_duration)
        threshold = self.get_effective_threshold()
        return z > threshold

    def get_adaptive_timeout(self, multiplier: float = 5.0, default: float = 120.0) -> float:
        """Calculate adaptive timeout based on baseline.

        Args:
            multiplier: How many times the mean to use as timeout
            default: Default timeout if insufficient samples

        Returns:
            Timeout in seconds
        """
        if self.count < self.min_samples:
            return default

        # Use mean + (multiplier * stddev) for timeout
        # This provides a reasonable backstop while allowing longer-than-average operations
        return self.mean + (multiplier * self.stddev)

    def to_dict(self) -> dict[str, Any]:
        """Serialize baseline to dict for persistence."""
        return {
            "operation_type": self.operation_type,
            "endpoint": self.endpoint,
            "alpha": self.alpha,
            "mean": self.mean,
            "variance": self.variance,
            "count": self.count,
            "sigma_threshold": self.sigma_threshold,
            "min_samples": self.min_samples,
            "cold_start_multiplier": self.cold_start_multiplier,
            "cold_start_samples": self.cold_start_samples,
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperationBaseline:
        """Deserialize baseline from dict."""
        # Handle last_updated as string or datetime
        last_updated = data.get("last_updated")
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        elif last_updated is None:
            last_updated = datetime.utcnow()

        return cls(
            operation_type=data["operation_type"],
            endpoint=data.get("endpoint", ""),
            alpha=data.get("alpha", 0.2),
            mean=data.get("mean", 0.0),
            variance=data.get("variance", 0.0),
            count=data.get("count", 0),
            sigma_threshold=data.get("sigma_threshold", 2.0),
            min_samples=data.get("min_samples", 5),
            cold_start_multiplier=data.get("cold_start_multiplier", 3.0),
            cold_start_samples=data.get("cold_start_samples", 10),
            last_updated=last_updated,
        )


class BaselineRegistry:
    """Singleton registry of baselines by operation type.

    Thread-safe registry for managing operation baselines.
    Supports optional PostgreSQL persistence to survive restarts.
    """

    def __init__(self) -> None:
        self._baselines: dict[str, OperationBaseline] = {}
        self._lock = threading.Lock()
        self._loaded_from_db = False

    def _make_key(self, operation_type: str, endpoint: str = "") -> str:
        """Create unique key for operation+endpoint combination."""
        if endpoint:
            return f"{operation_type}:{endpoint}"
        return operation_type

    def get_or_create(
        self,
        operation_type: str,
        endpoint: str = "",
        **kwargs: Any,
    ) -> OperationBaseline:
        """Get existing baseline or create new one.

        Args:
            operation_type: Operation identifier
            endpoint: Optional endpoint context
            **kwargs: Override default OperationBaseline parameters

        Returns:
            OperationBaseline instance
        """
        key = self._make_key(operation_type, endpoint)

        with self._lock:
            if key not in self._baselines:
                self._baselines[key] = OperationBaseline(
                    operation_type=operation_type,
                    endpoint=endpoint,
                    **kwargs,
                )
                logger.debug(f"Created new baseline: {key}")

            return self._baselines[key]

    def get(self, operation_type: str, endpoint: str = "") -> OperationBaseline | None:
        """Get baseline if it exists.

        Args:
            operation_type: Operation identifier
            endpoint: Optional endpoint context

        Returns:
            OperationBaseline or None if not found
        """
        key = self._make_key(operation_type, endpoint)
        with self._lock:
            return self._baselines.get(key)

    def list_baselines(self) -> list[OperationBaseline]:
        """List all registered baselines."""
        with self._lock:
            return list(self._baselines.values())

    async def persist_to_db(self, pool: "Pool") -> int:
        """Persist all baselines to PostgreSQL.

        Creates/updates rows in meta.operation_baselines table.
        Returns count of baselines persisted.
        """
        with self._lock:
            baselines = list(self._baselines.values())

        if not baselines:
            return 0

        count = 0
        async with pool.acquire() as conn:
            for baseline in baselines:
                await conn.execute(
                    """
                    INSERT INTO meta.operation_baselines (
                        operation_type, endpoint, baseline_data, updated_at
                    ) VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (operation_type, endpoint)
                    DO UPDATE SET
                        baseline_data = $3,
                        updated_at = NOW()
                    """,
                    baseline.operation_type,
                    baseline.endpoint,
                    json.dumps(baseline.to_dict()),
                )
                count += 1

        logger.info(f"Persisted {count} operation baselines to database")
        return count

    async def load_from_db(self, pool: "Pool") -> int:
        """Load baselines from PostgreSQL.

        Restores baseline state from previous runs.
        Returns count of baselines loaded.
        """
        if self._loaded_from_db:
            return 0

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT operation_type, endpoint, baseline_data
                    FROM meta.operation_baselines
                    """
                )

            count = 0
            with self._lock:
                for row in rows:
                    data = json.loads(row["baseline_data"])
                    baseline = OperationBaseline.from_dict(data)
                    key = self._make_key(baseline.operation_type, baseline.endpoint)
                    self._baselines[key] = baseline
                    count += 1

            self._loaded_from_db = True
            logger.info(f"Loaded {count} operation baselines from database")
            return count

        except Exception as e:
            # Table might not exist yet - that's OK
            logger.debug(f"Could not load baselines from DB: {e}")
            self._loaded_from_db = True
            return 0

    def to_json(self) -> str:
        """Serialize all baselines to JSON."""
        with self._lock:
            data = {key: b.to_dict() for key, b in self._baselines.items()}
        return json.dumps(data, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "BaselineRegistry":
        """Deserialize registry from JSON."""
        registry = cls()
        data = json.loads(json_str)
        for key, baseline_data in data.items():
            baseline = OperationBaseline.from_dict(baseline_data)
            registry._baselines[key] = baseline
        return registry


def get_baseline_registry() -> BaselineRegistry:
    """Get the global singleton BaselineRegistry.

    Thread-safe lazy initialization.

    Raises:
        RuntimeError: If registry initialization fails (should never happen)
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = BaselineRegistry()
    # Fail-fast: _registry is guaranteed to be non-None after the block above
    if _registry is None:
        raise RuntimeError(
            "BaselineRegistry initialization failed unexpectedly\n"
            "  Guru Meditation: #BL.00000001.INITFAIL"
        )
    return _registry


# Common operation types as constants for consistency
class OperationTypes:
    """Standard operation type identifiers."""

    GPU_ALLOCATION = "gpu_allocation"
    MODEL_LOADING = "model_loading"
    LLM_INFERENCE = "llm_inference"
    VECTOR_SEARCH = "vector_search"
    KB_WRITE = "kb_write"
    EXTERNAL_API = "external_api"
    FLOW_STEP = "flow_step"
