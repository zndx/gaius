"""Tests for ThetaAgent Knowledge Gradient policy.

Tests the economic justification for consolidation decisions
based on Powell & Ryzhov's Optimal Learning.
"""

import pytest
import numpy as np

from gaius.agents.theta.kg_policy import (
    KnowledgeGradientPolicy,
    BeliefState,
    ConsolidationDecision,
    compute_kg_factor,
)
from gaius.agents.theta.subsumption import SubsumptionCandidate


class TestBeliefState:
    """Tests for BeliefState dataclass."""

    def test_create_belief_state(self):
        """Test creating a belief state."""
        state = BeliefState(
            prior_mean=0.5,
            prior_variance=0.25,
        )

        assert state.prior_mean == 0.5
        assert state.prior_variance == 0.25
        assert state.n_measurements == 0

    def test_belief_state_defaults(self):
        """Test default values."""
        state = BeliefState()

        assert state.prior_mean == 0.0
        assert state.prior_variance == 1.0
        assert state.n_measurements == 0

    def test_get_belief_new_candidate(self):
        """Test getting belief for new candidate."""
        state = BeliefState(prior_mean=0.3, prior_variance=0.5)

        mean, var = state.get_belief("new_candidate")

        assert mean == 0.3  # Prior mean
        assert var == 0.5  # Prior variance

    def test_update_belief(self):
        """Test Bayesian belief update."""
        state = BeliefState(
            prior_mean=0.0,
            prior_variance=1.0,
            measurement_noise=0.1,
        )

        # Update with positive observation
        new_mean, new_var = state.update("test_candidate", 0.8)

        # Mean should move toward observation
        assert new_mean > 0  # Moved toward 0.8
        # Variance should decrease
        assert new_var < 1.0
        # Sample count should increase
        assert state.n_measurements == 1

    def test_current_best(self):
        """Test getting current best value."""
        state = BeliefState()

        # No measurements yet
        assert state.current_best() == state.prior_mean

        # Add some beliefs
        state.update("candidate_a", 0.5)
        state.update("candidate_b", 0.8)

        # Should return max mean
        assert state.current_best() > 0.5


class TestComputeKGFactor:
    """Tests for KG factor computation."""

    def test_kg_factor_positive_z(self):
        """Test KG factor with positive z."""
        result = compute_kg_factor(1.0)
        assert result > 0

    def test_kg_factor_negative_z(self):
        """Test KG factor with negative z."""
        result = compute_kg_factor(-1.0)
        assert result > 0  # f(z) is always positive

    def test_kg_factor_zero(self):
        """Test KG factor at z=0."""
        result = compute_kg_factor(0.0)
        # At z=0: f(0) = 0*Φ(0) + φ(0) = 0 + 0.399 ≈ 0.399
        assert 0.39 < result < 0.41


class TestSubsumptionCandidate:
    """Tests for SubsumptionCandidate used with KG policy."""

    def test_create_candidate(self):
        """Test creating a subsumption candidate."""
        candidate = SubsumptionCandidate(
            subclass="neural_network",
            superclass="machine_learning",
            confidence=0.85,
            source_slice="2025-W50",
            target_slice="2025-W48",
        )

        assert candidate.subclass == "neural_network"
        assert candidate.superclass == "machine_learning"
        assert candidate.confidence == 0.85

    def test_candidate_to_dict(self):
        """Test candidate serialization."""
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.9,
        )

        d = candidate.to_dict()
        assert d["subclass"] == "A"
        assert d["superclass"] == "B"
        assert d["confidence"] == 0.9


class TestKnowledgeGradientPolicy:
    """Tests for the Knowledge Gradient policy."""

    def test_init_policy(self):
        """Test policy initialization."""
        policy = KnowledgeGradientPolicy(
            measurement_cost=0.5,
            research_mode=True,
        )

        assert policy.measurement_cost == 0.5
        assert policy.research_mode is True

    def test_candidate_key(self):
        """Test generating candidate keys."""
        policy = KnowledgeGradientPolicy()
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.9,
        )

        key = policy.candidate_key(candidate)
        assert key == "A⊑B"

    def test_compute_kg(self):
        """Test KG computation."""
        policy = KnowledgeGradientPolicy()
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.5,
        )

        kg = policy.compute_kg(candidate)
        assert kg >= 0  # KG always non-negative

    def test_should_verify_research_mode(self):
        """Test verification decision in research mode."""
        policy = KnowledgeGradientPolicy(research_mode=True)
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.9,
        )

        should, kg, reason = policy.should_verify(candidate)

        assert should is True
        assert reason == "research_mode"

    def test_should_verify_normal_mode(self):
        """Test verification decision in normal mode."""
        policy = KnowledgeGradientPolicy(
            research_mode=False,
            measurement_cost=0.001,  # Very low cost
        )
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.5,
        )

        should, kg, reason = policy.should_verify(candidate)

        # With very low cost and some uncertainty, should often verify
        assert isinstance(should, bool)
        assert reason in ["kg_exceeds_cost", "kg_below_cost"]

    def test_select_candidates(self):
        """Test candidate selection."""
        policy = KnowledgeGradientPolicy(research_mode=True)

        candidates = [
            SubsumptionCandidate(subclass="A", superclass="X", confidence=0.9),
            SubsumptionCandidate(subclass="B", superclass="X", confidence=0.7),
            SubsumptionCandidate(subclass="C", superclass="X", confidence=0.5),
        ]

        selected = policy.select_candidates(candidates, max_candidates=2)

        assert len(selected) == 2
        # Should be sorted by KG value

    def test_update_from_measurement(self):
        """Test belief update after measurement."""
        policy = KnowledgeGradientPolicy()
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.9,
        )

        initial_n = policy.belief_state.n_measurements

        new_mean, new_var = policy.update_from_measurement(
            candidate=candidate,
            observed_improvement=0.7,
        )

        assert policy.belief_state.n_measurements == initial_n + 1
        assert new_mean != 0  # Updated from prior

    def test_get_stats(self):
        """Test getting policy statistics."""
        policy = KnowledgeGradientPolicy()
        stats = policy.get_stats()

        assert "measurement_cost" in stats
        assert "research_mode" in stats
        assert "belief_state" in stats


class TestConsolidationDecision:
    """Tests for ConsolidationDecision dataclass."""

    def test_create_decision(self):
        """Test creating a consolidation decision."""
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.9,
        )

        decision = ConsolidationDecision(
            candidate=candidate,
            kg_value=0.15,
            cost_adjusted_kg=0.12,
            should_verify=True,
            reason="research_mode",
        )

        assert decision.should_verify is True
        assert decision.kg_value == 0.15
        assert decision.reason == "research_mode"

    def test_decision_to_dict(self):
        """Test decision serialization."""
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.9,
        )

        decision = ConsolidationDecision(
            candidate=candidate,
            kg_value=0.05,
            cost_adjusted_kg=0.02,
            should_verify=False,
            reason="kg_below_cost",
        )

        d = decision.to_dict()
        assert d["should_verify"] is False
        assert d["kg_value"] == 0.05
        assert d["reason"] == "kg_below_cost"
        assert "candidate" in d
