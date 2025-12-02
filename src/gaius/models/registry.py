"""Model registry for task-specific model selection.

Defines available models and their capabilities, enabling
intelligent routing of tasks to the most appropriate model.

Usage:
    from gaius.models import get_model_for_task, TaskType

    # Get best model for reasoning
    model = get_model_for_task(TaskType.REASONING)
    print(model.model_id)  # "Qwen/QwQ-32B"

    # Get embedding model
    model = get_model_for_task(TaskType.TEXT_EMBEDDING)
    print(model.model_id)  # "nomic-ai/nomic-embed-text-v1"
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ModelCapability(Enum):
    """Capabilities a model can have."""

    CHAT = auto()  # Conversational completion
    REASONING = auto()  # Complex reasoning/chain-of-thought
    CODING = auto()  # Code generation/understanding
    ORCHESTRATION = auto()  # Task routing/planning
    TEXT_EMBEDDING = auto()  # Text to vector
    VISION_EMBEDDING = auto()  # Image to vector
    VISION_LANGUAGE = auto()  # Multimodal understanding
    FUNCTION_CALLING = auto()  # Tool use
    LONG_CONTEXT = auto()  # Extended context window


class TaskType(Enum):
    """Types of tasks that can be routed to models."""

    # Generation tasks
    REASONING = "reasoning"  # Complex analysis, math, logic
    CODING = "coding"  # Code generation and review
    ORCHESTRATION = "orchestration"  # Agent routing, task planning
    CHAT = "chat"  # General conversation
    SYNTHESIS = "synthesis"  # Document synthesis
    EVALUATION = "evaluation"  # Output evaluation

    # Embedding tasks
    TEXT_EMBEDDING = "text_embedding"
    VISION_EMBEDDING = "vision_embedding"

    # Specialized
    SWARM_LEADER = "swarm_leader"
    SWARM_AGENT = "swarm_agent"
    ADVERSARIAL = "adversarial"


@dataclass
class ModelSpec:
    """Specification for a model in the registry."""

    model_id: str  # HuggingFace model ID or API identifier
    name: str  # Human-readable name
    provider: str  # "local", "vllm", "openai", "xai", "nomic"

    # Capabilities
    capabilities: list[ModelCapability] = field(default_factory=list)

    # Task affinity scores (0-1, higher = better for task)
    task_scores: dict[TaskType, float] = field(default_factory=dict)

    # Model specs
    context_length: int = 8192
    embedding_dim: int | None = None  # For embedding models

    # Inference settings
    default_temperature: float = 0.7
    default_max_tokens: int = 2048

    # Endpoint configuration
    endpoint_url: str | None = None
    api_key_env: str | None = None  # Environment variable for API key

    # Cost/performance
    tokens_per_second: float | None = None  # Estimated throughput
    cost_per_1k_tokens: float | None = None  # For API models

    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def supports(self, capability: ModelCapability) -> bool:
        """Check if model has a capability."""
        return capability in self.capabilities

    def score_for_task(self, task: TaskType) -> float:
        """Get affinity score for a task (0-1)."""
        return self.task_scores.get(task, 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Model Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Reasoning model - QwQ-32B
QWQ_32B = ModelSpec(
    model_id="Qwen/QwQ-32B",
    name="QwQ-32B",
    provider="vllm",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.REASONING,
        ModelCapability.CODING,
        ModelCapability.LONG_CONTEXT,
    ],
    task_scores={
        TaskType.REASONING: 0.95,
        TaskType.CODING: 0.85,
        TaskType.SYNTHESIS: 0.80,
        TaskType.EVALUATION: 0.90,
        TaskType.SWARM_LEADER: 0.85,
        TaskType.ADVERSARIAL: 0.90,
    },
    context_length=32768,
    default_temperature=0.6,
    default_max_tokens=4096,
    description="QwQ reasoning model - excels at complex analysis and chain-of-thought",
    tags=["reasoning", "analysis", "math"],
)

# Orchestration model - nvidia Orchestrator-8B
ORCHESTRATOR_8B = ModelSpec(
    model_id="nvidia/Orchestrator-8B",
    name="Orchestrator-8B",
    provider="vllm",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.ORCHESTRATION,
        ModelCapability.FUNCTION_CALLING,
    ],
    task_scores={
        TaskType.ORCHESTRATION: 0.95,
        TaskType.SWARM_LEADER: 0.90,
        TaskType.CHAT: 0.70,
    },
    context_length=8192,
    default_temperature=0.3,
    default_max_tokens=1024,
    description="NVIDIA orchestration model - task routing and agent coordination",
    tags=["orchestration", "routing", "planning"],
)

# Current default - Qwen3 Coder (already deployed)
QWEN3_CODER = ModelSpec(
    model_id="Qwen/Qwen3-Coder-30B-A3B-Instruct",
    name="Qwen3-Coder-30B",
    provider="vllm",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.CODING,
        ModelCapability.REASONING,
        ModelCapability.LONG_CONTEXT,
    ],
    task_scores={
        TaskType.CODING: 0.95,
        TaskType.REASONING: 0.80,
        TaskType.CHAT: 0.85,
        TaskType.SYNTHESIS: 0.75,
        TaskType.SWARM_AGENT: 0.80,
    },
    context_length=200000,
    default_temperature=0.7,
    default_max_tokens=2048,
    endpoint_url="http://localhost:8088/v1",
    description="Qwen3 Coder - strong coding and general reasoning",
    tags=["coding", "general", "long-context"],
)

# Text embedding - Nomic
NOMIC_EMBED_TEXT = ModelSpec(
    model_id="nomic-ai/nomic-embed-text-v1",
    name="Nomic Embed Text",
    provider="nomic",
    capabilities=[ModelCapability.TEXT_EMBEDDING],
    task_scores={
        TaskType.TEXT_EMBEDDING: 1.0,
    },
    embedding_dim=768,
    description="Nomic text embeddings - unified space with vision model",
    tags=["embedding", "text", "retrieval"],
)

# Vision embedding - Nomic (same embedding space as text!)
NOMIC_EMBED_VISION = ModelSpec(
    model_id="nomic-ai/nomic-embed-vision-v1",
    name="Nomic Embed Vision",
    provider="nomic",
    capabilities=[ModelCapability.VISION_EMBEDDING],
    task_scores={
        TaskType.VISION_EMBEDDING: 1.0,
    },
    embedding_dim=768,  # Same as text!
    description="Nomic vision embeddings - unified space with text model",
    tags=["embedding", "vision", "multimodal"],
)

# xAI Grok for evaluation
GROK_2 = ModelSpec(
    model_id="grok-2-latest",
    name="Grok-2",
    provider="xai",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.REASONING,
        ModelCapability.CODING,
        ModelCapability.LONG_CONTEXT,
    ],
    task_scores={
        TaskType.EVALUATION: 1.0,  # Primary use: frontier evaluation
        TaskType.REASONING: 0.95,
        TaskType.CODING: 0.90,
        TaskType.ADVERSARIAL: 0.95,
    },
    context_length=131072,
    default_temperature=0.5,
    default_max_tokens=4096,
    api_key_env="XAI_API_KEY",
    cost_per_1k_tokens=0.002,  # Approximate
    description="xAI Grok-2 - frontier model for evaluation and adversarial testing",
    tags=["frontier", "evaluation", "adversarial"],
)

# OpenAI fallback
GPT4O_MINI = ModelSpec(
    model_id="gpt-4o-mini",
    name="GPT-4o Mini",
    provider="openai",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.REASONING,
        ModelCapability.CODING,
        ModelCapability.FUNCTION_CALLING,
    ],
    task_scores={
        TaskType.CHAT: 0.85,
        TaskType.CODING: 0.80,
        TaskType.REASONING: 0.75,
        TaskType.SYNTHESIS: 0.80,
    },
    context_length=128000,
    default_temperature=0.7,
    default_max_tokens=4096,
    api_key_env="OPENAI_API_KEY",
    cost_per_1k_tokens=0.00015,
    description="GPT-4o Mini - efficient fallback for general tasks",
    tags=["general", "fallback", "api"],
)


# ═══════════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════════


class ModelRegistry:
    """Registry of available models with task-based routing."""

    def __init__(self):
        self._models: dict[str, ModelSpec] = {}
        self._task_priorities: dict[TaskType, list[str]] = {}

        # Register default models
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default model set."""
        defaults = [
            QWQ_32B,
            ORCHESTRATOR_8B,
            QWEN3_CODER,
            NOMIC_EMBED_TEXT,
            NOMIC_EMBED_VISION,
            GROK_2,
            GPT4O_MINI,
        ]
        for model in defaults:
            self.register(model)

    def register(self, model: ModelSpec) -> None:
        """Register a model in the registry."""
        self._models[model.model_id] = model

        # Update task priorities
        for task, score in model.task_scores.items():
            if task not in self._task_priorities:
                self._task_priorities[task] = []

            # Insert in sorted order (highest score first)
            priorities = self._task_priorities[task]
            inserted = False
            for i, model_id in enumerate(priorities):
                existing = self._models[model_id]
                if score > existing.score_for_task(task):
                    priorities.insert(i, model.model_id)
                    inserted = True
                    break
            if not inserted:
                priorities.append(model.model_id)

    def get(self, model_id: str) -> ModelSpec | None:
        """Get a model by ID."""
        return self._models.get(model_id)

    def get_for_task(
        self,
        task: TaskType,
        require_local: bool = False,
        exclude_providers: list[str] | None = None,
    ) -> ModelSpec | None:
        """Get the best model for a task.

        Args:
            task: Task type to find model for
            require_local: If True, only return local models
            exclude_providers: Providers to exclude

        Returns:
            Best matching ModelSpec or None
        """
        exclude = set(exclude_providers or [])
        if require_local:
            exclude.update(["openai", "xai"])

        priorities = self._task_priorities.get(task, [])

        for model_id in priorities:
            model = self._models[model_id]
            if model.provider not in exclude:
                return model

        return None

    def get_all_for_task(self, task: TaskType) -> list[ModelSpec]:
        """Get all models that support a task, sorted by score."""
        priorities = self._task_priorities.get(task, [])
        return [self._models[mid] for mid in priorities]

    def list_models(self) -> list[ModelSpec]:
        """List all registered models."""
        return list(self._models.values())

    def list_by_capability(self, capability: ModelCapability) -> list[ModelSpec]:
        """List models with a specific capability."""
        return [m for m in self._models.values() if m.supports(capability)]

    def list_by_provider(self, provider: str) -> list[ModelSpec]:
        """List models from a specific provider."""
        return [m for m in self._models.values() if m.provider == provider]


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level API
# ═══════════════════════════════════════════════════════════════════════════════

_registry: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    """Get or create the model registry singleton."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def get_model_for_task(
    task: TaskType,
    require_local: bool = False,
    exclude_providers: list[str] | None = None,
) -> ModelSpec | None:
    """Convenience function to get best model for a task."""
    registry = get_model_registry()
    return registry.get_for_task(task, require_local, exclude_providers)
