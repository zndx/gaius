"""Welford's online algorithm for streaming statistics.

Maintains O(1) memory while computing exact mean/variance
without recomputing from scratch each update.
"""

import math
from dataclasses import dataclass, field


@dataclass
class WelfordEstimator:
    """Online algorithm for weighted mean/variance (Welford, 1962).

    For FLOPS-weighted GPU utilization:
    - Each sample is weighted by GPU's theoretical TFLOPS
    - Produces weighted mean across heterogeneous GPUs
    """

    count: int = 0
    weighted_sum: float = 0.0
    total_weight: float = 0.0
    M2: float = 0.0  # Variance accumulator
    _last_mean: float = 0.0

    def update(self, value: float, weight: float = 1.0) -> None:
        """Add weighted sample, updating mean and variance incrementally."""
        self.count += 1
        self.weighted_sum += value * weight
        self.total_weight += weight

        if self.total_weight > 0:
            new_mean = self.weighted_sum / self.total_weight
            # Welford's variance update (weighted)
            delta = value - self._last_mean
            delta2 = value - new_mean
            self.M2 += weight * delta * delta2
            self._last_mean = new_mean

    @property
    def mean(self) -> float:
        """Weighted mean of all samples."""
        return self.weighted_sum / self.total_weight if self.total_weight > 0 else 0.0

    @property
    def variance(self) -> float:
        """Weighted sample variance."""
        return self.M2 / self.total_weight if self.total_weight > 0 else 0.0

    @property
    def stddev(self) -> float:
        return math.sqrt(self.variance)

    def reset(self) -> None:
        """Reset all accumulators (for periodic refresh)."""
        self.count = 0
        self.weighted_sum = 0.0
        self.total_weight = 0.0
        self.M2 = 0.0
        self._last_mean = 0.0


# Theoretical peak TFLOPS (FP16) by GPU model
GPU_TFLOPS = {
    "NVIDIA GeForce RTX 4090": 82.6,
    "NVIDIA GeForce RTX 3090": 35.6,
    "NVIDIA A100-SXM4-80GB": 312.0,
    "NVIDIA A100-PCIE-40GB": 312.0,
    "NVIDIA H100": 989.0,
}
DEFAULT_TFLOPS = 82.6  # Fallback for unknown GPUs
