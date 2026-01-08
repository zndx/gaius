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
    VLLMConfig,
    LlamaCppConfig,
    get_model_registry,
    get_model_for_task,
    get_ci_model,
    CI_MODEL_MAPPING,
    CI_QWEN_TINY,
    CI_OLMO_TINY,
    CI_GLM_SMALL,
    CI_MISTRAL_TINY,
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
from .tiered_evaluation import (
    TieredEvaluator,
    TieredEvalConfig,
    LocalEvaluator,
    EvalBudget,
    get_tiered_evaluator,
    evaluate_with_budget,
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
from .merging import (
    MergeMethod,
    ModelSource,
    MergeConfig,
    MergeResult,
    ModelMerger,
    slerp,
    ties_merge,
    dare_sparsify,
    dare_ties_merge,
    linear_merge,
    get_merger,
)
from .lineage import (
    ModelLineageEntry,
    ModelLineageTracker,
    get_lineage_tracker,
    record_merge_lineage,
)

__all__ = [
    # Registry
    "ModelRegistry",
    "ModelSpec",
    "ModelCapability",
    "TaskType",
    "VLLMConfig",
    "LlamaCppConfig",
    "get_model_registry",
    "get_model_for_task",
    # CI Test Models (llama.cpp on CPU)
    "get_ci_model",
    "CI_MODEL_MAPPING",
    "CI_QWEN_TINY",
    "CI_OLMO_TINY",
    "CI_GLM_SMALL",
    "CI_MISTRAL_TINY",
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
    # Tiered Evaluation (budget-aware)
    "TieredEvaluator",
    "TieredEvalConfig",
    "LocalEvaluator",
    "EvalBudget",
    "get_tiered_evaluator",
    "evaluate_with_budget",
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
    # Model Merging
    "MergeMethod",
    "ModelSource",
    "MergeConfig",
    "MergeResult",
    "ModelMerger",
    "slerp",
    "ties_merge",
    "dare_sparsify",
    "dare_ties_merge",
    "linear_merge",
    "get_merger",
    # Model Lineage
    "ModelLineageEntry",
    "ModelLineageTracker",
    "get_lineage_tracker",
    "record_merge_lineage",
]
