"""Model library for task-specific local inference.

Provides a registry of models optimized for different tasks:
- Reasoning: Qwen/QwQ-32B
- Orchestration: nvidia/Orchestrator-8B
- Text Embedding: nomic-ai/nomic-embed-text-v1
- Vision Embedding: nomic-ai/nomic-embed-vision-v1

The Nomic embedding models share the same embedding space,
enabling unified text+vision retrieval.
"""

from .registry import (
    ModelRegistry,
    ModelSpec,
    ModelCapability,
    TaskType,
    get_model_registry,
    get_model_for_task,
)
from .embeddings import (
    NomicEmbeddings,
    EmbeddingResult,
    get_embeddings,
)
from .evaluation import (
    XAIEvaluator,
    EvaluationResult,
    EvaluationDimension,
    get_evaluator,
    evaluate_output,
)
from .versioning import (
    AgentVersion,
    AgentConfig,
    VersionManager,
    get_version_manager,
)
from .optimization import (
    AgentOptimizer,
    OptimizationStrategy,
    OptimizationObjective,
    OptimizationResult,
    TaskExample,
    CandidateConfig,
    compute_pareto_front,
    get_optimizer,
    optimize_agent,
)

__all__ = [
    # Registry
    "ModelRegistry",
    "ModelSpec",
    "ModelCapability",
    "TaskType",
    "get_model_registry",
    "get_model_for_task",
    # Embeddings
    "NomicEmbeddings",
    "EmbeddingResult",
    "get_embeddings",
    # Evaluation
    "XAIEvaluator",
    "EvaluationResult",
    "EvaluationDimension",
    "get_evaluator",
    "evaluate_output",
    # Versioning
    "AgentVersion",
    "AgentConfig",
    "VersionManager",
    "get_version_manager",
    # Optimization (GEPA Pareto-based)
    "AgentOptimizer",
    "OptimizationStrategy",
    "OptimizationObjective",
    "OptimizationResult",
    "TaskExample",
    "CandidateConfig",
    "compute_pareto_front",
    "get_optimizer",
    "optimize_agent",
]
