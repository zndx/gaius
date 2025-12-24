"""NVAR-mediated consolidation dynamics for ThetaAgent.

Uses Next Generation Reservoir Computing (NGRC) via ReservoirPy NVAR
to compute consolidation signals from KB embedding time series.

The consolidation signal measures drift between predicted and actual
embedding centroids, indicating when cross-temporal linking is needed.

ACADEMIC IMPLEMENTATION (Gauthier et al. 2021):
- NVAR extracts nonlinear features via delay embedding + polynomial expansion
- A trained readout layer maps features → predictions via ridge regression
- Training: W_out = (X^T X + αI)^{-1} X^T Y (ridge, regularized for stability)
- Prediction: y_pred = features @ W_out

Reference: Gauthier et al. 2021 - Next Generation Reservoir Computing
           Nature Communications, DOI: 10.1038/s41467-021-25801-2
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

import logging

logger = logging.getLogger(__name__)

# Import ReservoirPy at module level - FAIL-FAST
try:
    from reservoirpy.nodes import NVAR
except ImportError as e:
    raise RuntimeError(
        "ReservoirPy required for NVAR dynamics.\n"
        "  Guru Meditation: #THETA.00000002.RESERVOIRPY_UNAVAILABLE\n"
        "  Try: uv add reservoirpy"
    ) from e


@dataclass
class ConsolidationSignal:
    """Result of NVAR-based consolidation signal computation.

    Attributes:
        urgency: Bounded [0, 1] consolidation urgency (tanh(drift))
        drift: Raw L2 norm of prediction error
        predicted: What NVAR expected for this slice
        actual: What was actually observed
        slice_id: Temporal slice identifier
        timestamp: When signal was computed
    """

    urgency: float
    drift: float
    predicted: np.ndarray
    actual: np.ndarray
    slice_id: str
    timestamp: datetime = field(default_factory=datetime.now)

    def should_consolidate(self, threshold: float = 0.5) -> bool:
        """Check if consolidation should be triggered.

        Args:
            threshold: Urgency threshold (default 0.5)

        Returns:
            True if urgency exceeds threshold
        """
        return self.urgency > threshold

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "urgency": self.urgency,
            "drift": self.drift,
            "slice_id": self.slice_id,
            "timestamp": self.timestamp.isoformat(),
            "should_consolidate": self.should_consolidate(),
        }


@dataclass
class TemporalSlice:
    """A time-bounded embedding centroid from KB.

    Attributes:
        slice_id: Identifier (e.g., "2025-W52", "2025-Q4")
        centroid: 768-dim normalized embedding centroid
        document_count: Number of documents in slice
        created_at: When slice was computed
    """

    slice_id: str
    centroid: np.ndarray
    document_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)


class ThetaDynamics:
    """NVAR-based theta oscillator for consolidation scheduling.

    Uses ReservoirPy NVAR (Nonlinear Vector Autoregression) to predict
    the next embedding centroid based on temporal history. The deviation
    between prediction and observation indicates consolidation need.

    ACADEMIC IMPLEMENTATION (Gauthier et al. 2021):
    - NVAR extracts nonlinear features via delay embedding + polynomial expansion
    - Features: [x_{t-k}, ..., x_{t-1}, x_t, x_{t-k}*x_{t-k+1}, ...]
    - A trained readout layer W_out maps features → predictions
    - Training: W_out = (X^T X + αI)^{-1} X^T Y (ridge regression)
    - Prediction: y_pred = features @ W_out

    DIMENSIONALITY REDUCTION:
    Full 768-dim embeddings with polynomial features would be intractable.
    We use PCA to reduce to `reduced_dim` components before NVAR processing,
    then project predictions back to full space.

    Args:
        k: Number of historical slices to consider (delay)
        polynomial_order: Order of polynomial feature expansion (default 2)
        drift_scale: Scaling factor for drift -> urgency (default 1.0)
        ridge_alpha: Regularization strength for ridge regression (default 1e-6)
        reduced_dim: Dimensionality after PCA reduction (default 32)
    """

    def __init__(
        self,
        k: int = 4,
        polynomial_order: int = 2,
        drift_scale: float = 1.0,
        ridge_alpha: float = 1e-6,
        reduced_dim: int = 32,
    ):
        self.k = k
        self.polynomial_order = polynomial_order
        self.drift_scale = drift_scale
        self.ridge_alpha = ridge_alpha
        self.reduced_dim = reduced_dim
        self.history: list[TemporalSlice] = []

        # NVAR node for feature extraction
        self._nvar = NVAR(
            delay=self.k,
            order=self.polynomial_order,
            strides=1,
        )
        logger.debug(
            f"Initialized NVAR(delay={self.k}, order={self.polynomial_order}, "
            f"reduced_dim={self.reduced_dim})"
        )

        # PCA for dimensionality reduction (fit incrementally)
        self._pca_mean: Optional[np.ndarray] = None
        self._pca_components: Optional[np.ndarray] = None
        self._raw_centroids: list[np.ndarray] = []  # For PCA fitting

        # Trained readout weights (Gauthier et al. 2021)
        self.W_out: Optional[np.ndarray] = None
        self._features_history: list[np.ndarray] = []
        self._targets_history: list[np.ndarray] = []

    def _fit_pca(self) -> None:
        """Fit PCA on accumulated centroids.

        Uses incremental SVD for efficiency.
        """
        if len(self._raw_centroids) < self.reduced_dim:
            # Not enough data - use identity projection (truncate)
            return

        # Stack centroids
        X = np.vstack(self._raw_centroids)

        # Compute mean
        self._pca_mean = X.mean(axis=0)
        X_centered = X - self._pca_mean

        # SVD for PCA
        U, S, Vt = np.linalg.svd(X_centered, full_matrices=False)

        # Keep top components
        self._pca_components = Vt[:self.reduced_dim].T  # Shape: (768, reduced_dim)

        logger.debug(
            f"Fitted PCA: {X.shape[0]} samples -> {self.reduced_dim} components"
        )

    def _reduce_dim(self, centroid: np.ndarray) -> np.ndarray:
        """Project centroid to reduced space.

        Args:
            centroid: Full 768-dim embedding

        Returns:
            Reduced-dim projection
        """
        if self._pca_components is None:
            # No PCA yet - just truncate
            return centroid[:self.reduced_dim]

        centered = centroid - self._pca_mean
        return centered @ self._pca_components

    def _expand_dim(self, reduced: np.ndarray) -> np.ndarray:
        """Project reduced representation back to full space.

        Args:
            reduced: Reduced-dim vector

        Returns:
            Approximate full-dim reconstruction
        """
        if self._pca_components is None:
            # No PCA yet - pad with zeros
            # Infer full dim from first raw centroid if available
            full_dim = len(self._raw_centroids[0]) if self._raw_centroids else 768
            result = np.zeros(full_dim)
            result[:self.reduced_dim] = reduced
            return result

        return reduced @ self._pca_components.T + self._pca_mean

    def _train_readout(self) -> None:
        """Train readout layer via ridge regression (Gauthier et al. 2021).

        Solves: W_out = argmin_W ||XW - Y||^2 + α||W||^2
        Closed form: W_out = (X^T X + αI)^{-1} X^T Y
        """
        if len(self._features_history) < 2:
            logger.debug("Insufficient features for readout training")
            return

        # Stack features and targets (one-step ahead prediction)
        # Features[t] should predict centroid[t+1]
        X = np.vstack(self._features_history[:-1])
        Y = np.vstack(self._targets_history[1:])

        # Solve via ridge regression for numerical stability
        # W_out = (X^T X + αI)^{-1} X^T Y
        XTX = X.T @ X
        reg_term = self.ridge_alpha * np.eye(XTX.shape[0])
        XTY = X.T @ Y

        try:
            self.W_out = np.linalg.solve(XTX + reg_term, XTY)
            logger.debug(f"Trained readout: W_out shape {self.W_out.shape}")
        except np.linalg.LinAlgError as e:
            logger.warning(f"Readout training failed (singular matrix): {e}")
            # Fall back to pseudo-inverse
            self.W_out = np.linalg.lstsq(X, Y, rcond=None)[0]

    def add_slice(
        self,
        slice_id: str,
        centroid: np.ndarray,
        document_count: int = 0,
    ) -> Optional[ConsolidationSignal]:
        """Add a temporal slice and compute consolidation signal.

        Args:
            slice_id: Temporal slice identifier (e.g., "2025-W52")
            centroid: 768-dim normalized embedding centroid
            document_count: Number of documents in slice

        Returns:
            ConsolidationSignal if enough history and trained readout, None otherwise
        """
        # Create and store slice (full resolution)
        ts = TemporalSlice(
            slice_id=slice_id,
            centroid=centroid,
            document_count=document_count,
        )
        self.history.append(ts)

        # Accumulate raw centroids for PCA
        self._raw_centroids.append(centroid.copy())

        # Refit PCA periodically (every 5 new slices after initial fit)
        if len(self._raw_centroids) >= self.reduced_dim and len(self._raw_centroids) % 5 == 0:
            self._fit_pca()

        # Need at least k+1 slices for NVAR features
        if len(self.history) < self.k + 1:
            logger.debug(
                f"Not enough history for NVAR: {len(self.history)}/{self.k + 1}"
            )
            return None

        # Extract NVAR features for current window (in reduced space)
        recent_slices = self.history[-self.k - 1:]
        reduced_centroids = [self._reduce_dim(s.centroid) for s in recent_slices]
        window = np.stack(reduced_centroids, axis=0)
        features = self._nvar.run(window)

        # Store features and target for readout training (in reduced space)
        reduced_target = self._reduce_dim(centroid)
        if len(features.shape) > 1:
            self._features_history.append(features[-1])
        else:
            self._features_history.append(features)
        self._targets_history.append(reduced_target)

        # Retrain readout with new data (online learning)
        self._train_readout()

        # Need trained W_out to make predictions
        if self.W_out is None:
            logger.debug("Readout not yet trained, cannot compute signal")
            return None

        # Compute consolidation signal
        return self._compute_signal(ts, features)

    def _compute_signal(
        self, current_slice: TemporalSlice, features: np.ndarray
    ) -> ConsolidationSignal:
        """Compute consolidation signal for current slice.

        Uses trained readout to predict what the centroid should be,
        then measures deviation from actual observation.

        Works in reduced space for computational efficiency.

        Args:
            current_slice: The current temporal slice
            features: NVAR features for current window (in reduced space)

        Returns:
            ConsolidationSignal with urgency and drift metrics
        """
        # Get feature vector for prediction (last row of features matrix)
        if len(features.shape) > 1:
            feat_vec = features[-1]
        else:
            feat_vec = features

        # Predict using trained readout (Gauthier et al. 2021)
        # Prediction is in reduced space
        predicted_reduced = feat_vec @ self.W_out

        # Normalize prediction (in reduced space)
        norm = np.linalg.norm(predicted_reduced)
        if norm > 0:
            predicted_reduced = predicted_reduced / norm

        # Get actual centroid in reduced space
        actual_reduced = self._reduce_dim(current_slice.centroid)

        # Compute drift in reduced space (L2 distance)
        drift = float(np.linalg.norm(predicted_reduced - actual_reduced))

        # Bound urgency via tanh for [0, 1] range
        urgency = float(np.tanh(drift * self.drift_scale))

        # Expand predictions back to full space for inspection
        predicted_full = self._expand_dim(predicted_reduced.flatten())
        norm_full = np.linalg.norm(predicted_full)
        if norm_full > 0:
            predicted_full = predicted_full / norm_full

        return ConsolidationSignal(
            urgency=urgency,
            drift=drift,
            predicted=predicted_full,
            actual=current_slice.centroid,
            slice_id=current_slice.slice_id,
        )

    def get_recent_slices(self, n: int = 4) -> list[TemporalSlice]:
        """Get n most recent temporal slices.

        Args:
            n: Number of slices to return

        Returns:
            List of recent TemporalSlice objects
        """
        return self.history[-n:] if self.history else []

    def clear_history(self) -> int:
        """Clear temporal slice history and reset readout.

        Returns:
            Number of slices cleared
        """
        count = len(self.history)
        self.history = []
        self.W_out = None
        self._features_history = []
        self._targets_history = []
        return count

    def get_stats(self) -> dict:
        """Get dynamics statistics.

        Returns:
            Dict with history length, k, readout status, PCA info, etc.
        """
        return {
            "history_length": len(self.history),
            "k": self.k,
            "polynomial_order": self.polynomial_order,
            "ridge_alpha": self.ridge_alpha,
            "reduced_dim": self.reduced_dim,
            "can_predict": len(self.history) >= self.k + 1 and self.W_out is not None,
            "readout_trained": self.W_out is not None,
            "readout_shape": list(self.W_out.shape) if self.W_out is not None else None,
            "features_collected": len(self._features_history),
            "pca_fitted": self._pca_components is not None,
            "raw_centroids_collected": len(self._raw_centroids),
            "slice_ids": [s.slice_id for s in self.history],
        }


# Convenience function for computing week identifier
def get_week_slice_id(dt: datetime | None = None) -> str:
    """Get ISO week identifier for a datetime.

    Args:
        dt: Datetime to get week for (default: now)

    Returns:
        Week identifier like "2025-W52"
    """
    if dt is None:
        dt = datetime.now()
    iso_cal = dt.isocalendar()
    return f"{iso_cal.year}-W{iso_cal.week:02d}"


def get_quarter_slice_id(dt: datetime | None = None) -> str:
    """Get quarter identifier for a datetime.

    Args:
        dt: Datetime to get quarter for (default: now)

    Returns:
        Quarter identifier like "2025-Q4"
    """
    if dt is None:
        dt = datetime.now()
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{quarter}"
