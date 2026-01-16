"""Tests for ThetaAgent core functionality.

Tests the main ThetaAgent class including SITREP generation
and consolidation orchestration.
"""

import pytest
import tempfile
from pathlib import Path

from gaius.agents.theta import (
    ThetaAgent,
    ConsolidationResult,
    Horizon,
)


class TestThetaAgentInit:
    """Tests for ThetaAgent initialization."""

    def test_init_with_kb_root(self):
        """Test initialization with kb_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = ThetaAgent(kb_root=tmpdir)
            assert agent.kb_root == Path(tmpdir)

    def test_init_creates_dynamics(self):
        """Test that ThetaDynamics is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = ThetaAgent(kb_root=tmpdir)
            assert agent.dynamics is not None

    def test_init_creates_policy(self):
        """Test that KnowledgeGradientPolicy is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = ThetaAgent(kb_root=tmpdir)
            assert agent.kg_policy is not None


class TestHorizon:
    """Tests for Horizon enum."""

    def test_horizon_values(self):
        """Test horizon enum values."""
        assert Horizon.DAY.value == "day"
        assert Horizon.WEEK.value == "week"
        assert Horizon.QUARTER.value == "quarter"

    def test_horizon_from_string(self):
        """Test creating horizon from string."""
        assert Horizon("day") == Horizon.DAY
        assert Horizon("week") == Horizon.WEEK
        assert Horizon("quarter") == Horizon.QUARTER


class TestConsolidationResult:
    """Tests for ConsolidationResult dataclass."""

    def test_create_result(self):
        """Test creating a consolidation result."""
        result = ConsolidationResult(
            slice_id="2025-W52",
            candidates_evaluated=10,
            candidates_selected=3,
            documents_augmented=3,
        )

        assert result.slice_id == "2025-W52"
        assert result.candidates_evaluated == 10
        assert result.candidates_selected == 3
        assert result.documents_augmented == 3
        assert result.error is None

    def test_result_with_error(self):
        """Test result with error."""
        result = ConsolidationResult(
            slice_id="test",
            error="Something went wrong",
        )

        assert result.error == "Something went wrong"
        assert result.documents_augmented == 0

    def test_result_defaults(self):
        """Test result default values."""
        result = ConsolidationResult(slice_id="test")

        assert result.signal is None
        assert result.candidates_evaluated == 0
        assert result.candidates_selected == 0
        assert result.documents_augmented == 0
        assert result.augmentations == []
        assert result.effectiveness is None
        assert result.error is None


class TestThetaAgentConsolidation:
    """Tests for consolidation functionality."""

    @pytest.fixture
    def mock_agent(self, tmp_path):
        """Create agent with mock KB."""
        (tmp_path / "scratch" / "2025-W52").mkdir(parents=True)
        (tmp_path / "current" / "topics").mkdir(parents=True)

        # Create test document
        doc = tmp_path / "scratch" / "2025-W52" / "test.md"
        doc.write_text("# Test Document\n\nContent about neural networks.")

        return ThetaAgent(kb_root=tmp_path)

    def test_get_consolidation_stats(self, mock_agent):
        """Test getting consolidation statistics."""
        stats = mock_agent.get_consolidation_stats()

        assert "dynamics" in stats
        assert "kg_policy" in stats

    def test_dynamics_initial_state(self, mock_agent):
        """Test dynamics is properly initialized."""
        stats = mock_agent.get_consolidation_stats()

        dynamics = stats["dynamics"]
        assert "k" in dynamics
        assert "history_length" in dynamics
        assert dynamics["history_length"] == 0


class TestThetaAgentMethods:
    """Tests for ThetaAgent helper methods."""

    @pytest.fixture
    def agent_with_slices(self, tmp_path):
        """Create agent with multiple temporal slices."""
        for week in range(48, 53):
            week_dir = tmp_path / "scratch" / f"2025-W{week}"
            week_dir.mkdir(parents=True)
            (week_dir / f"doc_{week}.md").write_text(f"# Week {week}\n\nContent.")

        return ThetaAgent(kb_root=tmp_path)

    def test_dynamics_stats(self, agent_with_slices):
        """Test dynamics stats."""
        stats = agent_with_slices.get_consolidation_stats()

        assert "dynamics" in stats
        dynamics = stats["dynamics"]
        assert "k" in dynamics
        assert "history_length" in dynamics

    def test_dynamics_k_parameter(self, tmp_path):
        """Test dynamics k parameter."""
        agent = ThetaAgent(kb_root=tmp_path)

        # Check dynamics has reasonable k value
        assert agent.dynamics.k >= 2
        assert agent.dynamics.k <= 8
