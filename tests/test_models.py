"""Tests for the model library.

Tests cover:
- Model registry and task routing
- Pareto optimization utilities
- Agent versioning data structures
- Evaluation result structures
"""

import pytest
import numpy as np
from datetime import datetime

# Registry tests
from gaius.models.registry import (
    ModelRegistry,
    ModelSpec,
    ModelCapability,
    TaskType,
    get_model_registry,
    get_model_for_task,
)

# Optimization tests
from gaius.models.optimization import (
    CandidateConfig,
    OptimizationObjective,
    OptimizationStrategy,
    OptimizationResult,
    TaskExample,
    is_dominated,
    compute_pareto_front,
    compute_pareto_ranks,
    crowding_distance,
)

# Versioning tests
from gaius.models.versioning import (
    AgentConfig,
    AgentVersion,
)

# Evaluation tests
from gaius.models.evaluation import (
    EvaluationDimension,
    DimensionScore,
    EvaluationResult,
)

# Embeddings tests
from gaius.models.embeddings import (
    EmbeddingResult,
    BatchEmbeddingResult,
)


class TestModelRegistry:
    """Test model registry and task routing."""

    def test_get_registry(self):
        """Registry singleton is created."""
        registry = get_model_registry()
        assert registry is not None
        assert isinstance(registry, ModelRegistry)

    def test_get_model_for_task(self):
        """Can get models for different task types."""
        # These raise RuntimeError if no model registered - no None checks needed
        reasoning_model = get_model_for_task(TaskType.REASONING)
        assert ModelCapability.REASONING in reasoning_model.capabilities

        coding_model = get_model_for_task(TaskType.CODING)
        assert coding_model.model_id  # Just verify we got a model

        text_embed = get_model_for_task(TaskType.TEXT_EMBEDDING)
        assert ModelCapability.TEXT_EMBEDDING in text_embed.capabilities

        vision_embed = get_model_for_task(TaskType.VISION_EMBEDDING)
        assert ModelCapability.VISION_EMBEDDING in vision_embed.capabilities

    def test_model_spec_properties(self):
        """ModelSpec has correct properties."""
        registry = get_model_registry()
        spec = registry.get_for_task(TaskType.REASONING)  # Raises if not found

        assert spec.model_id is not None
        assert spec.provider in ["huggingface", "xai", "openai", "vllm"]
        assert isinstance(spec.capabilities, (set, list))
        assert spec.context_length > 0

    def test_registry_model_list(self):
        """Registry contains expected models."""
        registry = get_model_registry()
        models = registry.list_models()

        assert len(models) > 0
        model_ids = [m.model_id for m in models]

        # Should have key models registered
        assert any("QwQ" in m or "qwq" in m.lower() for m in model_ids)
        assert any("nomic" in m.lower() for m in model_ids)


class TestParetoOptimization:
    """Test Pareto optimization utilities."""

    def test_is_dominated_simple(self):
        """Basic domination check."""
        a = {OptimizationObjective.ACCURACY: 0.5, OptimizationObjective.EFFICIENCY: 0.5}
        b = {OptimizationObjective.ACCURACY: 0.8, OptimizationObjective.EFFICIENCY: 0.6}

        # b dominates a (better in both)
        assert is_dominated(a, b) is True
        assert is_dominated(b, a) is False

    def test_is_dominated_pareto(self):
        """Neither dominates when on Pareto front."""
        a = {OptimizationObjective.ACCURACY: 0.9, OptimizationObjective.EFFICIENCY: 0.5}
        b = {OptimizationObjective.ACCURACY: 0.5, OptimizationObjective.EFFICIENCY: 0.9}

        # Neither dominates - both on Pareto front
        assert is_dominated(a, b) is False
        assert is_dominated(b, a) is False

    def test_compute_pareto_front(self):
        """Pareto front computation."""
        # Create candidates with multi-objective scores
        candidates = [
            CandidateConfig(
                system_prompt="A",
                temperature=0.7,
                model="test",
                objective_scores={
                    OptimizationObjective.ACCURACY: 0.9,
                    OptimizationObjective.EFFICIENCY: 0.7,
                },
            ),
            CandidateConfig(
                system_prompt="B",
                temperature=0.7,
                model="test",
                objective_scores={
                    OptimizationObjective.ACCURACY: 0.7,
                    OptimizationObjective.EFFICIENCY: 0.9,
                },
            ),
            CandidateConfig(
                system_prompt="C",
                temperature=0.7,
                model="test",
                objective_scores={
                    # C is dominated by A (A is better or equal in all objectives)
                    OptimizationObjective.ACCURACY: 0.6,
                    OptimizationObjective.EFFICIENCY: 0.5,
                },
            ),
        ]

        front = compute_pareto_front(candidates)

        # A and B are on the front, C is dominated by A
        assert len(front) == 2
        prompts = [c.system_prompt for c in front]
        assert "A" in prompts
        assert "B" in prompts
        assert "C" not in prompts

    def test_compute_pareto_ranks(self):
        """Non-dominated sorting assigns correct ranks."""
        candidates = [
            CandidateConfig(
                system_prompt="front",
                temperature=0.7,
                model="test",
                objective_scores={
                    OptimizationObjective.ACCURACY: 0.9,
                    OptimizationObjective.EFFICIENCY: 0.9,
                },
            ),
            CandidateConfig(
                system_prompt="rank1",
                temperature=0.7,
                model="test",
                objective_scores={
                    OptimizationObjective.ACCURACY: 0.7,
                    OptimizationObjective.EFFICIENCY: 0.7,
                },
            ),
            CandidateConfig(
                system_prompt="rank2",
                temperature=0.7,
                model="test",
                objective_scores={
                    OptimizationObjective.ACCURACY: 0.5,
                    OptimizationObjective.EFFICIENCY: 0.5,
                },
            ),
        ]

        compute_pareto_ranks(candidates)

        # Check ranks
        rank_map = {c.system_prompt: c.pareto_rank for c in candidates}
        assert rank_map["front"] == 0
        assert rank_map["rank1"] == 1
        assert rank_map["rank2"] == 2

        # Check is_pareto_optimal flag
        opt_map = {c.system_prompt: c.is_pareto_optimal for c in candidates}
        assert opt_map["front"] is True
        assert opt_map["rank1"] is False
        assert opt_map["rank2"] is False

    def test_crowding_distance(self):
        """Crowding distance preserves diversity."""
        candidates = [
            CandidateConfig(
                system_prompt="low",
                temperature=0.7,
                model="test",
                objective_scores={OptimizationObjective.ACCURACY: 0.1},
            ),
            CandidateConfig(
                system_prompt="mid",
                temperature=0.7,
                model="test",
                objective_scores={OptimizationObjective.ACCURACY: 0.5},
            ),
            CandidateConfig(
                system_prompt="high",
                temperature=0.7,
                model="test",
                objective_scores={OptimizationObjective.ACCURACY: 0.9},
            ),
        ]

        distances = crowding_distance(candidates, [OptimizationObjective.ACCURACY])

        # Boundary points have infinite distance
        assert distances[id(candidates[0])] == float("inf")
        assert distances[id(candidates[2])] == float("inf")

        # Middle point has finite distance
        assert distances[id(candidates[1])] < float("inf")

    def test_optimization_result_best_for_objective(self):
        """OptimizationResult.best_for_objective works."""
        config_a = CandidateConfig(
            system_prompt="A",
            temperature=0.7,
            model="test",
            objective_scores={
                OptimizationObjective.ACCURACY: 0.9,
                OptimizationObjective.EFFICIENCY: 0.5,
            },
        )
        config_b = CandidateConfig(
            system_prompt="B",
            temperature=0.7,
            model="test",
            objective_scores={
                OptimizationObjective.ACCURACY: 0.5,
                OptimizationObjective.EFFICIENCY: 0.9,
            },
        )

        result = OptimizationResult(
            success=True,
            pareto_front=[config_a, config_b],
        )

        best_accuracy = result.best_for_objective(OptimizationObjective.ACCURACY)
        assert best_accuracy.system_prompt == "A"

        best_efficiency = result.best_for_objective(OptimizationObjective.EFFICIENCY)
        assert best_efficiency.system_prompt == "B"


class TestAgentVersioning:
    """Test agent versioning data structures."""

    def test_agent_config_to_dict(self):
        """AgentConfig serializes correctly."""
        config = AgentConfig(
            system_prompt="You are a helpful assistant.",
            model="Qwen/QwQ-32B",
            temperature=0.7,
            max_tokens=2048,
            tags=["test", "v1"],
        )

        data = config.to_dict()
        assert data["system_prompt"] == "You are a helpful assistant."
        assert data["model"] == "Qwen/QwQ-32B"
        assert data["temperature"] == 0.7
        assert "test" in data["tags"]

    def test_agent_config_from_dict(self):
        """AgentConfig deserializes correctly."""
        data = {
            "system_prompt": "Test prompt",
            "model": "test-model",
            "temperature": 0.5,
        }

        config = AgentConfig.from_dict(data)
        assert config.system_prompt == "Test prompt"
        assert config.model == "test-model"
        assert config.temperature == 0.5

    def test_agent_config_hash(self):
        """Config hash is deterministic."""
        config1 = AgentConfig(system_prompt="Test", temperature=0.7, model="m")
        config2 = AgentConfig(system_prompt="Test", temperature=0.7, model="m")
        config3 = AgentConfig(system_prompt="Different", temperature=0.7, model="m")

        assert config1.config_hash() == config2.config_hash()
        assert config1.config_hash() != config3.config_hash()

    def test_agent_version_to_dict(self):
        """AgentVersion serializes correctly."""
        config = AgentConfig(system_prompt="Test", model="test")
        version = AgentVersion(
            version_id="test-v1",
            agent_id="leader",
            config=config,
            is_active=True,
            metrics={"accuracy": 0.85},
            evaluation_count=5,
            avg_overall_score=0.82,
        )

        data = version.to_dict()
        assert data["version_id"] == "test-v1"
        assert data["agent_id"] == "leader"
        assert data["is_active"] is True
        assert data["metrics"]["accuracy"] == 0.85
        assert data["evaluation_count"] == 5

    def test_agent_version_from_dict(self):
        """AgentVersion deserializes correctly."""
        data = {
            "version_id": "test-v2",
            "agent_id": "worker",
            "config": {"system_prompt": "Worker prompt", "model": "test"},
            "is_active": False,
            "metrics": {"coherence": 0.9},
            "evaluation_count": 3,
            "avg_overall_score": 0.88,
            "best_overall_score": 0.92,
            "created_at": "2025-11-30T12:00:00",
        }

        version = AgentVersion.from_dict(data)
        assert version.version_id == "test-v2"
        assert version.agent_id == "worker"
        assert version.config.system_prompt == "Worker prompt"
        assert version.metrics["coherence"] == 0.9


class TestEvaluation:
    """Test evaluation data structures."""

    def test_evaluation_dimensions(self):
        """All evaluation dimensions exist."""
        dims = list(EvaluationDimension)
        dim_values = [d.value for d in dims]

        assert "accuracy" in dim_values
        assert "coherence" in dim_values
        assert "relevance" in dim_values
        assert "completeness" in dim_values
        assert "clarity" in dim_values
        assert "actionability" in dim_values
        assert "creativity" in dim_values

    def test_dimension_score(self):
        """DimensionScore structure works."""
        score = DimensionScore(
            dimension=EvaluationDimension.ACCURACY,
            score=0.85,
            feedback="Good factual accuracy",
            suggestions=["Add citations"],
        )

        assert score.dimension == EvaluationDimension.ACCURACY
        assert score.score == 0.85
        assert "factual" in score.feedback

    def test_evaluation_result_to_dict(self):
        """EvaluationResult serializes correctly."""
        result = EvaluationResult(
            overall_score=0.82,
            summary="Good overall performance",
            strengths=["Clear", "Accurate"],
            weaknesses=["Could be more concise"],
            dimension_scores={
                EvaluationDimension.ACCURACY: DimensionScore(
                    dimension=EvaluationDimension.ACCURACY,
                    score=0.9,
                    feedback="Accurate",
                ),
            },
            evaluator_model="grok-2",
            tokens_used=500,
        )

        data = result.to_dict()
        assert data["overall_score"] == 0.82
        assert "Clear" in data["strengths"]
        assert "accuracy" in data["dimension_scores"]
        assert data["dimension_scores"]["accuracy"]["score"] == 0.9

    def test_evaluation_result_from_dict(self):
        """EvaluationResult deserializes correctly."""
        data = {
            "overall_score": 0.75,
            "summary": "Test summary",
            "strengths": ["A", "B"],
            "weaknesses": ["C"],
            "dimension_scores": {
                "coherence": {"score": 0.8, "feedback": "Good flow"},
            },
        }

        result = EvaluationResult.from_dict(data)
        assert result.overall_score == 0.75
        assert result.summary == "Test summary"
        assert EvaluationDimension.COHERENCE in result.dimension_scores


class TestEmbeddings:
    """Test embedding data structures."""

    def test_embedding_result(self):
        """EmbeddingResult structure works."""
        vector = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        result = EmbeddingResult(
            vector=vector,
            model="nomic-ai/nomic-embed-text-v1",
            input_type="text",
            tokens=10,
            latency_ms=50,
        )

        assert result.dim == 5
        assert result.model == "nomic-ai/nomic-embed-text-v1"
        assert result.input_type == "text"

        as_list = result.to_list()
        assert len(as_list) == 5
        assert as_list[0] == pytest.approx(0.1)

    def test_batch_embedding_result(self):
        """BatchEmbeddingResult structure works."""
        vectors = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
        result = BatchEmbeddingResult(
            vectors=vectors,
            model="nomic-ai/nomic-embed-text-v1",
            input_type="text",
            count=3,
            total_tokens=30,
            latency_ms=100,
        )

        assert result.dim == 2
        assert result.count == 3


class TestTaskExample:
    """Test task example structure."""

    def test_task_example_basic(self):
        """TaskExample works for basic cases."""
        example = TaskExample(
            input_prompt="What is 2 + 2?",
            expected_output="4",
            evaluation_criteria="Correct numerical answer",
        )

        assert example.input_prompt == "What is 2 + 2?"
        assert example.expected_output == "4"

    def test_task_example_with_context(self):
        """TaskExample works with context."""
        example = TaskExample(
            input_prompt="Summarize the document",
            context="The document discusses pension asset allocation...",
            reference_score=0.9,
        )

        assert example.context is not None
        assert example.reference_score == 0.9


class TestCandidateConfig:
    """Test candidate configuration structure."""

    def test_candidate_basic(self):
        """CandidateConfig basic structure."""
        candidate = CandidateConfig(
            system_prompt="You are a helpful assistant",
            temperature=0.7,
            model="Qwen/QwQ-32B",
        )

        assert candidate.temperature == 0.7
        assert candidate.pareto_rank == 0
        assert candidate.is_pareto_optimal is False

    def test_candidate_with_scores(self):
        """CandidateConfig with evaluation scores."""
        candidate = CandidateConfig(
            system_prompt="Test",
            temperature=0.7,
            model="test",
            scores=[0.8, 0.85, 0.9],
            avg_score=0.85,
            objective_scores={
                OptimizationObjective.ACCURACY: 0.9,
                OptimizationObjective.COHERENCE: 0.85,
            },
            generation_method="apo_mutation",
            generation=2,
        )

        assert candidate.avg_score == 0.85
        assert candidate.objective_scores[OptimizationObjective.ACCURACY] == 0.9
        assert candidate.generation_method == "apo_mutation"
