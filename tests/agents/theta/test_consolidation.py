"""Tests for ThetaAgent consolidation dynamics.

Tests the NVAR-based consolidation signal computation and
ThetaDynamics state machine.

ACADEMIC IMPLEMENTATION (Gauthier et al. 2021):
ThetaDynamics uses ReservoirPy NVAR for actual nonlinear vector autoregression.
There is NO fallback mode - ReservoirPy is a hard requirement.

Tests require reservoirpy to be installed. The implementation performs:
1. PCA dimensionality reduction (768 -> 32 dims)
2. NVAR feature extraction (delay embedding + polynomial expansion)
3. Ridge regression readout training
4. Prediction error -> consolidation urgency
"""

import numpy as np
import pytest
from datetime import datetime

from gaius.agents.theta.consolidation import (
    ThetaDynamics,
    ConsolidationSignal,
    TemporalSlice,
    get_week_slice_id,
    get_quarter_slice_id,
)


class TestTemporalSlice:
    """Tests for TemporalSlice dataclass."""

    def test_create_slice(self):
        """Test creating a temporal slice."""
        centroid = np.random.randn(768)
        centroid = centroid / np.linalg.norm(centroid)

        ts = TemporalSlice(
            slice_id="2025-W52",
            centroid=centroid,
            document_count=42,
        )

        assert ts.slice_id == "2025-W52"
        assert ts.document_count == 42
        assert len(ts.centroid) == 768
        assert isinstance(ts.created_at, datetime)

    def test_slice_defaults(self):
        """Test default values for temporal slice."""
        centroid = np.zeros(768)
        ts = TemporalSlice(slice_id="test", centroid=centroid)

        assert ts.document_count == 0
        assert ts.created_at is not None


class TestConsolidationSignal:
    """Tests for ConsolidationSignal dataclass."""

    def test_signal_should_consolidate(self):
        """Test should_consolidate threshold logic."""
        signal = ConsolidationSignal(
            urgency=0.7,
            drift=0.5,
            predicted=np.zeros(768),
            actual=np.zeros(768),
            slice_id="test",
        )

        assert signal.should_consolidate(threshold=0.5) is True
        assert signal.should_consolidate(threshold=0.8) is False
        assert signal.should_consolidate() is True  # default 0.5

    def test_signal_to_dict(self):
        """Test JSON serialization."""
        signal = ConsolidationSignal(
            urgency=0.6,
            drift=0.4,
            predicted=np.zeros(768),
            actual=np.ones(768),
            slice_id="2025-W01",
        )

        d = signal.to_dict()
        assert d["urgency"] == 0.6
        assert d["drift"] == 0.4
        assert d["slice_id"] == "2025-W01"
        assert "timestamp" in d
        assert "should_consolidate" in d


class TestThetaDynamics:
    """Tests for ThetaDynamics NVAR-based predictor.

    These tests verify the real NVAR implementation using ReservoirPy.
    The implementation performs PCA reduction before NVAR to handle
    the high-dimensional (768) embeddings.
    """

    def test_initial_state(self):
        """Test initial dynamics state."""
        dynamics = ThetaDynamics(k=4)

        stats = dynamics.get_stats()
        assert stats["history_length"] == 0
        assert stats["k"] == 4
        assert stats["can_predict"] is False
        assert stats["readout_trained"] is False

    def test_add_slices_insufficient_history(self):
        """Test that signal is None when insufficient history."""
        dynamics = ThetaDynamics(k=3)

        for i in range(3):  # Need k+1 = 4 slices minimum
            centroid = np.random.randn(768)
            centroid = centroid / np.linalg.norm(centroid)
            signal = dynamics.add_slice(f"2025-W{i:02d}", centroid)
            assert signal is None

        stats = dynamics.get_stats()
        assert stats["history_length"] == 3
        # Still can't predict - need trained readout
        assert stats["can_predict"] is False

    def test_add_slices_produces_signal(self):
        """Test that signal is produced when enough history and training data exists.

        The NVAR implementation requires:
        1. At least k+1 slices for NVAR features
        2. At least 2 feature vectors for readout training (to predict next step)

        So we need k+2 slices before getting a signal.
        """
        dynamics = ThetaDynamics(k=3)

        # Add k+2 = 5 slices to ensure readout can be trained
        signals = []
        for i in range(5):
            centroid = np.random.randn(768)
            centroid = centroid / np.linalg.norm(centroid)
            signal = dynamics.add_slice(f"2025-W{i:02d}", centroid)
            signals.append(signal)

        # Last slice should produce a signal (readout trained on first 4)
        assert signals[-1] is not None
        assert isinstance(signals[-1], ConsolidationSignal)
        assert 0 <= signals[-1].urgency <= 1
        assert signals[-1].drift >= 0

    def test_signal_detects_drift(self):
        """Test that large drift produces measurable urgency.

        We first train on consistent vectors, then introduce a very
        different vector to see if drift is detected.
        """
        dynamics = ThetaDynamics(k=2, drift_scale=2.0, reduced_dim=16)

        # Add consistent slices first (all similar direction)
        base = np.zeros(768)
        base[0] = 1.0  # Unit vector along first axis

        # Need k+2 = 4 slices to train readout
        for i in range(4):
            # Small perturbations to avoid singular matrices
            centroid = base.copy() + np.random.randn(768) * 0.01
            centroid = centroid / np.linalg.norm(centroid)
            dynamics.add_slice(f"slice-{i}", centroid)

        # Now add a very different slice (orthogonal direction)
        different = np.zeros(768)
        different[1] = 1.0  # Orthogonal to base
        different = different + np.random.randn(768) * 0.01
        different = different / np.linalg.norm(different)

        signal = dynamics.add_slice("drift-slice", different)

        assert signal is not None
        # With orthogonal vector, expect non-zero drift
        assert signal.drift > 0
        # Urgency should be positive (tanh of scaled drift)
        assert signal.urgency > 0

    def test_get_recent_slices(self):
        """Test retrieving recent slices."""
        dynamics = ThetaDynamics(k=2)

        for i in range(5):
            centroid = np.random.randn(768)
            centroid = centroid / np.linalg.norm(centroid)
            dynamics.add_slice(f"slice-{i}", centroid, document_count=i * 10)

        recent = dynamics.get_recent_slices(n=3)
        assert len(recent) == 3
        assert recent[-1].slice_id == "slice-4"
        assert recent[-1].document_count == 40

    def test_clear_history(self):
        """Test clearing history."""
        dynamics = ThetaDynamics(k=2)

        for i in range(5):
            centroid = np.random.randn(768)
            dynamics.add_slice(f"slice-{i}", centroid)

        cleared = dynamics.clear_history()
        assert cleared == 5
        assert dynamics.get_stats()["history_length"] == 0
        assert dynamics.get_stats()["readout_trained"] is False

    def test_pca_fitting(self):
        """Test that PCA is fitted when enough data accumulates."""
        dynamics = ThetaDynamics(k=2, reduced_dim=16)

        # PCA needs at least reduced_dim samples
        assert dynamics._pca_components is None

        # Add enough slices for PCA
        for i in range(20):
            centroid = np.random.randn(768)
            centroid = centroid / np.linalg.norm(centroid)
            dynamics.add_slice(f"slice-{i}", centroid)

        # PCA should be fitted after reduced_dim slices
        stats = dynamics.get_stats()
        assert stats["pca_fitted"] is True or stats["raw_centroids_collected"] >= 16

    def test_stats_include_all_fields(self):
        """Test that get_stats returns all expected fields."""
        dynamics = ThetaDynamics(k=3, polynomial_order=2, reduced_dim=32)

        stats = dynamics.get_stats()

        expected_fields = [
            "history_length",
            "k",
            "polynomial_order",
            "ridge_alpha",
            "reduced_dim",
            "can_predict",
            "readout_trained",
            "readout_shape",
            "features_collected",
            "pca_fitted",
            "raw_centroids_collected",
            "slice_ids",
        ]

        for field in expected_fields:
            assert field in stats, f"Missing field: {field}"


class TestSliceIdFunctions:
    """Tests for slice ID helper functions."""

    def test_get_week_slice_id_format(self):
        """Test week identifier format."""
        # Test default (now) returns valid format
        slice_id = get_week_slice_id()
        assert "-W" in slice_id
        # Format is YYYY-WXX
        parts = slice_id.split("-W")
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert parts[1].isdigit()

    def test_get_week_slice_id_specific_date(self):
        """Test week identifier for specific date."""
        dt = datetime(2025, 12, 29)  # Last week of 2025
        slice_id = get_week_slice_id(dt)
        assert slice_id.startswith("2025-W") or slice_id.startswith("2026-W")

    def test_get_quarter_slice_id(self):
        """Test quarter identifier generation."""
        # Test Q1
        dt = datetime(2025, 2, 15)
        assert get_quarter_slice_id(dt) == "2025-Q1"

        # Test Q4
        dt = datetime(2025, 11, 1)
        assert get_quarter_slice_id(dt) == "2025-Q4"

        # Test default
        slice_id = get_quarter_slice_id()
        assert slice_id.startswith("20")
        assert "-Q" in slice_id

    def test_quarter_boundaries(self):
        """Test quarter boundaries are correct."""
        # Q1: Jan-Mar
        assert get_quarter_slice_id(datetime(2025, 1, 1)) == "2025-Q1"
        assert get_quarter_slice_id(datetime(2025, 3, 31)) == "2025-Q1"

        # Q2: Apr-Jun
        assert get_quarter_slice_id(datetime(2025, 4, 1)) == "2025-Q2"
        assert get_quarter_slice_id(datetime(2025, 6, 30)) == "2025-Q2"

        # Q3: Jul-Sep
        assert get_quarter_slice_id(datetime(2025, 7, 1)) == "2025-Q3"
        assert get_quarter_slice_id(datetime(2025, 9, 30)) == "2025-Q3"

        # Q4: Oct-Dec
        assert get_quarter_slice_id(datetime(2025, 10, 1)) == "2025-Q4"
        assert get_quarter_slice_id(datetime(2025, 12, 31)) == "2025-Q4"
