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
from gaius.core.budgets import REASONING_MAX_TOKENS


class ModelCapability(Enum):
    """Capabilities a model can have."""

    CHAT = auto()  # Conversational completion
    REASONING = auto()  # Complex reasoning/chain-of-thought
    CODING = auto()  # Code generation/understanding
    ORCHESTRATION = auto()  # Task routing/planning
    TEXT_EMBEDDING = auto()  # Text to vector
    VISION_EMBEDDING = auto()  # Image to vector
    VISION_LANGUAGE = auto()  # Multimodal understanding (surface label: vision)
    FUNCTION_CALLING = auto()  # Tool use
    LONG_CONTEXT = auto()  # Extended context window
    LATENT_MAS_CLT = auto()  # Cross-Layer Transcoder for latent-space operations
    THINKING = auto()  # Request-mode thinking traces (on by default for Qwen3.8)
    OPEN_THINKING = auto()  # Olmo 3: full model flow is public (data, code, checkpoints)

    def surface_label(self) -> str:
        """Operator-facing capability token. Ordered arrays use these strings."""
        if self is ModelCapability.VISION_LANGUAGE:
            return "vision"
        if self is ModelCapability.OPEN_THINKING:
            return "open-thinking"
        if self is ModelCapability.TEXT_EMBEDDING:
            return "text-embedding"
        if self is ModelCapability.VISION_EMBEDDING:
            return "vision-embedding"
        if self is ModelCapability.FUNCTION_CALLING:
            return "function-calling"
        if self is ModelCapability.LONG_CONTEXT:
            return "long-context"
        return self.name.lower().replace("_", "-")


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

    # Interpretability / Latent operations
    CLT_TRACING = "clt_tracing"  # Circuit tracing with CLT

    # Extended capabilities (on-demand scheduling)
    THINKING = "thinking"  # Extended reasoning with thinking traces
    INSTRUCT = "instruct"  # Long-context instruction following


@dataclass
class VLLMConfig:
    """vLLM-specific launch configuration."""

    tensor_parallel_size: int = 1  # Number of GPUs for tensor parallelism
    gpu_memory_utilization: float = 0.9
    max_model_len: int | None = None  # None = use model default
    max_num_seqs: int = 256
    dtype: str = "auto"  # "auto", "float16", "bfloat16"
    trust_remote_code: bool = False

    # Startup optimization
    enforce_eager: bool = False  # Skip CUDA graph compilation for fast startup
    swap_space: int = 0  # Swap space in GB for KV cache overflow

    # Tool/reasoning support
    tool_call_parser: str | None = None  # e.g., "glm45", "hermes"
    reasoning_parser: str | None = None  # e.g., "glm45", "deepseek"
    enable_auto_tool_choice: bool = False

    # Attention backend
    attention_backend: str | None = None  # "FLASHINFER", "FLASH_ATTN", etc.

    # Additional vLLM args
    extra_args: dict[str, Any] = field(default_factory=dict)

    def to_cli_args(self) -> list[str]:
        """Convert to vLLM CLI arguments."""
        args = [
            f"--tensor-parallel-size={self.tensor_parallel_size}",
            f"--gpu-memory-utilization={self.gpu_memory_utilization}",
            f"--max-num-seqs={self.max_num_seqs}",
            f"--dtype={self.dtype}",
        ]
        if self.max_model_len:
            args.append(f"--max-model-len={self.max_model_len}")
        if self.trust_remote_code:
            args.append("--trust-remote-code")
        if self.enforce_eager:
            args.append("--enforce-eager")
        if self.swap_space > 0:
            args.append(f"--swap-space={self.swap_space}")
        if self.tool_call_parser:
            args.append(f"--tool-call-parser={self.tool_call_parser}")
        if self.reasoning_parser:
            args.append(f"--reasoning-parser={self.reasoning_parser}")
        if self.enable_auto_tool_choice:
            args.append("--enable-auto-tool-choice")
        for key, val in self.extra_args.items():
            args.append(f"--{key}={val}")
        return args

    def to_env_vars(self) -> dict[str, str]:
        """Get environment variables for vLLM."""
        env = {}
        if self.attention_backend:
            env["VLLM_ATTENTION_BACKEND"] = self.attention_backend
        return env


@dataclass
class LlamaCppConfig:
    """llama.cpp server configuration for CPU inference in CI.

    These models are used in GitHub Actions where GPU hardware is unavailable.
    They run on CPU with small context windows for fast, deterministic testing.

    The goal is pipeline correctness, not output quality.
    """

    # Model file (GGUF format)
    gguf_file: str  # e.g., "qwen2.5-0.5b-instruct-q4_k_m.gguf"

    # HuggingFace repo for download
    hf_repo: str  # e.g., "Qwen/Qwen2.5-0.5B-Instruct-GGUF"

    # Server configuration
    context_size: int = 512  # Small context for fast CI tests
    n_predict: int = 64  # Short completions for speed
    threads: int = 4  # Match GitHub runner vCPUs
    port: int = 8080

    def download_command(self, local_dir: str = "./models") -> str:
        """Generate huggingface-cli download command."""
        return (
            f"huggingface-cli download {self.hf_repo} {self.gguf_file} "
            f"--local-dir {local_dir}"
        )

    def serve_command(self, model_path: str) -> str:
        """Generate llama-server command."""
        return (
            f"llama-server -m {model_path}/{self.gguf_file} "
            f"--port {self.port} "
            f"-c {self.context_size} "
            f"-n {self.n_predict} "
            f"-t {self.threads}"
        )


@dataclass
class ResourceRequirements:
    """Resource requirements for running a model.

    Used by the orchestrator for workload-driven GPU management.
    """

    num_gpus: int = 1
    memory_mb: int = 0


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
    parameters_b: float | None = None  # Model size in billions

    # GPU resource requirements
    memory_mb: int = 0  # GPU memory footprint in MB (0 = estimate from parameters)

    # Inference settings
    default_temperature: float = 0.7
    default_max_tokens: int = REASONING_MAX_TOKENS

    # Endpoint configuration
    endpoint_url: str | None = None
    api_key_env: str | None = None  # Environment variable for API key
    default_port: int | None = None  # Preferred port when serving

    # vLLM configuration (for local models)
    vllm_config: VLLMConfig | None = None

    # llama.cpp configuration (for CI testing with tiny models)
    llamacpp_config: LlamaCppConfig | None = None

    # Cost/performance
    tokens_per_second: float | None = None  # Estimated throughput
    cost_per_1k_tokens: float | None = None  # For API models

    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def capability_labels(self) -> list[str]:
        """Ordered surface labels (thinking before vision for Qwen3.8)."""
        return [c.surface_label() for c in self.capabilities]

    def supports(self, capability: ModelCapability) -> bool:
        """Check if model has a capability."""
        return capability in self.capabilities

    def score_for_task(self, task: TaskType) -> float:
        """Get affinity score for a task (0-1)."""
        return self.task_scores.get(task, 0.0)

    def get_resource_requirements(self) -> ResourceRequirements:
        """Get resource requirements for this model.

        Returns:
            ResourceRequirements with GPU count and memory estimate
        """
        num_gpus = 1
        if self.vllm_config:
            num_gpus = self.vllm_config.tensor_parallel_size

        memory = self.memory_mb
        if memory == 0 and self.parameters_b:
            # Estimate: ~2 bytes/param for fp16 + 20% overhead
            memory = int(self.parameters_b * 2 * 1024 * 1.2)

        return ResourceRequirements(num_gpus=num_gpus, memory_mb=memory)

    def serve_command(
        self,
        port: int | None = None,
        gpus: list[int] | None = None,
        served_model_name: str | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Generate vLLM serve command and environment variables.

        Args:
            port: Override default port
            gpus: List of GPU indices to use (sets CUDA_VISIBLE_DEVICES)
            served_model_name: Override served model name

        Returns:
            Tuple of (command_string, env_vars_dict)
        """
        if self.provider != "vllm" or not self.vllm_config:
            raise ValueError(f"Model {self.model_id} is not a vLLM model")

        port = port or self.default_port or 8000
        cfg = self.vllm_config

        # Build command
        args = ["vllm", "serve", self.model_id]
        args.append(f"--port={port}")
        if served_model_name:
            args.append(f"--served-model-name={served_model_name}")
        args.extend(cfg.to_cli_args())

        # Build env vars
        env = cfg.to_env_vars()
        if gpus:
            env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in gpus)

        return " ".join(args), env


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
    parameters_b=32,
    memory_mb=80000,  # ~80GB with TP=4 for full context
    default_temperature=0.6,
    default_max_tokens=4096,
    vllm_config=VLLMConfig(
        tensor_parallel_size=4,
        max_model_len=32768,
        max_num_seqs=32,  # Reduced for 32B model on 4x 24GB GPUs
        trust_remote_code=True,
    ),
    description="QwQ reasoning model - excels at complex analysis and chain-of-thought",
    tags=["reasoning", "analysis", "math"],
)

# DeepSeek R1 Distill - Strong reasoning via R1 distillation
DEEPSEEK_R1_DISTILL = ModelSpec(
    model_id="deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
    name="DeepSeek-R1-Distill-32B",
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
        TaskType.SYNTHESIS: 0.85,
        TaskType.EVALUATION: 0.90,
        TaskType.SWARM_LEADER: 0.85,
    },
    context_length=65536,
    parameters_b=32,
    memory_mb=80000,  # ~80GB with TP=4 for long context
    default_temperature=0.6,
    default_max_tokens=4096,
    vllm_config=VLLMConfig(
        tensor_parallel_size=4,
        max_model_len=65536,
        max_num_seqs=32,  # Reduced for long context
    ),
    description="DeepSeek R1 distilled into Qwen-32B - SOTA reasoning",
    tags=["reasoning", "r1", "distillation"],
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
    context_length=32768,
    parameters_b=8,
    memory_mb=8000,  # ~8GB for 8B model on single GPU
    default_temperature=0.3,
    default_max_tokens=1024,
    vllm_config=VLLMConfig(
        tensor_parallel_size=1,
        max_model_len=32768,
    ),
    description="NVIDIA orchestration model - task routing and agent coordination",
    tags=["orchestration", "routing", "planning"],
)

# GLM-4.6V-Flash - Fast multimodal with tool use
GLM_46V_FLASH = ModelSpec(
    model_id="zai-org/GLM-4.6V-Flash",
    name="GLM-4.6V-Flash",
    provider="vllm",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.VISION_LANGUAGE,
        ModelCapability.REASONING,
        ModelCapability.FUNCTION_CALLING,
        ModelCapability.LONG_CONTEXT,
    ],
    task_scores={
        TaskType.CHAT: 0.90,
        TaskType.REASONING: 0.85,
        TaskType.SWARM_AGENT: 0.85,
    },
    context_length=65536,
    parameters_b=9,
    memory_mb=24000,  # ~24GB with TP=4 for vision + long context
    default_temperature=0.7,
    default_max_tokens=8192,
    vllm_config=VLLMConfig(
        tensor_parallel_size=4,  # Works well on 4 GPUs
        max_model_len=65536,
        attention_backend="FLASHINFER",
        tool_call_parser="glm45",
        reasoning_parser="glm45",
        enable_auto_tool_choice=True,
    ),
    description="GLM-4.6V Flash - fast multimodal with tool use and reasoning",
    tags=["multimodal", "vision", "tool-use", "fast"],
)

# Mistral 7B - Fast general purpose
MISTRAL_7B = ModelSpec(
    model_id="mistralai/Mistral-7B-Instruct-v0.3",
    name="Mistral-7B",
    provider="vllm",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.CODING,
        ModelCapability.FUNCTION_CALLING,
    ],
    task_scores={
        TaskType.CHAT: 0.80,
        TaskType.CODING: 0.75,
        TaskType.SWARM_AGENT: 0.85,
    },
    context_length=32768,
    parameters_b=7,
    memory_mb=7000,  # ~7GB for 7B model
    default_temperature=0.7,
    default_max_tokens=2048,
    vllm_config=VLLMConfig(
        tensor_parallel_size=1,
        max_model_len=32768,
    ),
    description="Mistral 7B - fast and efficient for general tasks",
    tags=["fast", "general", "efficient"],
)

# Qwen3 Coder
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
    parameters_b=30,
    memory_mb=20000,  # MoE model, active params ~3B, ~20GB with TP=2
    default_temperature=0.7,
    default_max_tokens=2048,
    vllm_config=VLLMConfig(
        tensor_parallel_size=2,
        max_model_len=65536,  # Practical limit for memory
        trust_remote_code=True,
    ),
    description="Qwen3 Coder - strong coding and general reasoning",
    tags=["coding", "general", "long-context"],
)

COLBERT_ZERO = ModelSpec(
    model_id="lightonai/ColBERT-Zero",
    name="ColBERT-Zero",
    provider="colbert",
    capabilities=[
        ModelCapability.TEXT_EMBEDDING,
    ],
    task_scores={
        TaskType.TEXT_EMBEDDING: 1.0,
    },
    embedding_dim=128,
    context_length=519,
    parameters_b=0.149,
    memory_mb=600,
    description=(
        "Open late-interaction ColBERT (MaxSim, 128-d). "
        "Contrastive pre-training in the multi-vector setting on public Nomic data."
    ),
    tags=["open-embedding", "colbert", "late-interaction", "pylate", "apache-2"],
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
    memory_mb=800,  # ~800MB for nomic text embedding model
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
    memory_mb=1200,  # ~1.2GB for nomic vision embedding model
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


# Cross-Layer Transcoder (CLT) for interpretable features
# Uses BluelightAI's circuit-tracer with Qwen3
CLT_QWEN3_1_7B = ModelSpec(
    model_id="bluelightai/clt-qwen3-1.7b-base-20k",
    name="CLT Qwen3 1.7B",
    provider="clt",  # Custom provider for CLT models
    capabilities=[ModelCapability.LATENT_MAS_CLT],
    task_scores={
        TaskType.CLT_TRACING: 1.0,
    },
    context_length=32768,
    parameters_b=1.7,
    memory_mb=6000,  # ~4GB base + ~2GB CLT transcoders
    default_temperature=0.0,  # Deterministic for interpretability
    default_max_tokens=1024,
    description="Cross-Layer Transcoder for Qwen3-1.7B with 20K features per layer",
    tags=["clt", "interpretability", "circuit-tracing", "latent-mas"],
)


# ═══════════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════════


QWEN3_8B = ModelSpec(
    model_id="Qwen/Qwen3-8B",
    name="Qwen3-8B",
    provider="vllm",
    capabilities=[ModelCapability.CHAT, ModelCapability.REASONING, ModelCapability.CODING, ModelCapability.FUNCTION_CALLING],
    task_scores={
        TaskType.CHAT: 0.90,
        TaskType.REASONING: 0.88,
        TaskType.CODING: 0.85,
        TaskType.SWARM_AGENT: 0.82,
    },
    context_length=40960,
    parameters_b=8.2,
    memory_mb=8500,  # ~8.5GB for 8B model
    default_temperature=0.7,
    default_max_tokens=2048,
    vllm_config=VLLMConfig(
        tensor_parallel_size=1,
        max_model_len=40960,
        trust_remote_code=True,
    ),
    description="Qwen3-8B - advanced language model with reasoning, coding, and multilingual capabilities",
    tags=["transformers", "safetensors", "qwen3", "text-generation", "conversational", "reasoning", "coding", "multilingual"],
)


META_LLAMA_3_1_8B_INSTRUCT = ModelSpec(
    model_id="meta-llama/Llama-3.1-8B-Instruct",
    name="Llama-3.1-8B-Instruct",
    provider="vllm",
    capabilities=[ModelCapability.CHAT, ModelCapability.TEXT_EMBEDDING],
    task_scores={
        TaskType.CHAT: 0.85,
        TaskType.TEXT_EMBEDDING: 0.9,
    },
    context_length=32768,
    parameters_b=8.0,
    memory_mb=10000,  # ~10GB with TP=2
    default_temperature=0.7,
    default_max_tokens=2048,
    vllm_config=VLLMConfig(
        tensor_parallel_size=2,  # 8B model uses 2 for tensor parallelization
        max_model_len=32768,
    ),
    description="Llama-3.1-8B Instruct - text generation model with text embedding capabilities",
    tags=["transformers", "safetensors", "llama", "text-generation", "facebook", "meta", "pytorch", "llama-3", "conversational", "en", "de", "fr", "it", "pt", "hi"],
)


# Note: This import is redundant since we're already in registry.py
# Kept for backwards compatibility with generated ModelSpecs
# from gaius.models.registry import ModelSpec, VLLMConfig, ModelCapability, TaskType

QWEN38_27B = ModelSpec(
    model_id="Qwen/Qwen3.8-27B",
    name="Qwen3.8-27B",
    provider="vllm",
    # thinking first, vision next — request-mode thinking, native VL
    capabilities=[
        ModelCapability.THINKING,
        ModelCapability.VISION_LANGUAGE,
        ModelCapability.CHAT,
        ModelCapability.LONG_CONTEXT,
        ModelCapability.FUNCTION_CALLING,
        ModelCapability.CODING,
    ],
    task_scores={
        TaskType.THINKING: 1.0,
        TaskType.INSTRUCT: 0.95,
        TaskType.CHAT: 0.90,
        TaskType.CODING: 0.95,
        TaskType.SYNTHESIS: 0.90,
        TaskType.SWARM_AGENT: 0.85,
    },
    context_length=262144,
    parameters_b=27.0,
    memory_mb=54000,  # BF16 weights ~54GB, TP=4
    default_temperature=1.0,
    default_max_tokens=2048,
    default_port=8091,
    vllm_config=VLLMConfig(
        tensor_parallel_size=4,
        max_model_len=262144,
        max_num_seqs=8,
        dtype="bfloat16",
        trust_remote_code=True,
        gpu_memory_utilization=0.90,
        enforce_eager=True,
        swap_space=8,
        reasoning_parser="qwen3",
        tool_call_parser="qwen3_coder",
        enable_auto_tool_choice=True,
        extra_args={
            "default-chat-template-kwargs": (
                '{"enable_thinking":true,"preserve_thinking":true}'
            ),
        },
    ),
    description=(
        "Qwen3.8-27B native BF16 — capabilities [thinking, vision]; "
        "thinking on by default, multimodal VL"
    ),
    tags=["vllm", "bf16", "thinking", "vision", "long-context", "qwen3.8", "262k"],
)

# OLMo3-32B-Think — open-thinking (full model flow is public)
OLMO3_32B_THINK = ModelSpec(
    model_id="allenai/Olmo-3-32B-Think",
    name="OLMo3-32B-Think",
    provider="vllm",
    capabilities=[
        ModelCapability.OPEN_THINKING,
        ModelCapability.CHAT,
        ModelCapability.REASONING,
    ],
    task_scores={
        TaskType.THINKING: 0.90,
        TaskType.REASONING: 0.95,
        TaskType.EVALUATION: 0.85,
        TaskType.SYNTHESIS: 0.80,
    },
    context_length=65536,
    parameters_b=32.0,
    memory_mb=64000,  # ~64GB BF16 weights, distributed across 4 GPUs
    default_temperature=0.6,
    default_max_tokens=4096,
    default_port=8090,
    vllm_config=VLLMConfig(
        tensor_parallel_size=4,
        max_model_len=65536,  # Full 64K native context
        max_num_seqs=16,
        dtype="bfloat16",
        gpu_memory_utilization=0.95,
        enforce_eager=True,  # Skip CUDA graph compilation
        swap_space=8,
    ),
    description=(
        "Olmo 3-32B-Think — open-thinking: training data, code, and "
        "checkpoints are public, not just weights"
    ),
    tags=["vllm", "open-thinking", "olmo", "model-flow", "64k"],
)


# ═══════════════════════════════════════════════════════════════════════════════
# CI Test Models (llama.cpp on CPU)
#
# These tiny GGUF models enable real LLM inference in GitHub Actions without GPU.
# They map to production model families to minimize message format differences.
#
# Selection criteria:
# - Official models from original vendors (Qwen, AllenAI, THUDM)
# - Same model family as production (Qwen2.5 for Qwen3, OLMo-2 for OLMo-3)
# - Smallest available size for fast CI (~0.5B-1B parameters)
# - Q4_K_M quantization for balance of speed and quality
#
# Reference: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/tests
# ═══════════════════════════════════════════════════════════════════════════════

# CI test model for Qwen family (QwQ-32B, Qwen3-8B, Qwen3-Coder)
# Uses Qwen2.5-0.5B - official Qwen GGUF, same chat template
CI_QWEN_TINY = ModelSpec(
    model_id="ci-test/qwen-tiny",
    name="CI-Qwen-Tiny",
    provider="llamacpp",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.REASONING,
        ModelCapability.CODING,
    ],
    task_scores={
        TaskType.REASONING: 0.10,  # Low scores - only used when CI mode enabled
        TaskType.CODING: 0.10,
        TaskType.CHAT: 0.10,
    },
    context_length=512,  # Small for fast tests
    parameters_b=0.5,
    memory_mb=400,  # Q4_K_M ~400MB
    default_temperature=0.7,
    default_max_tokens=64,
    llamacpp_config=LlamaCppConfig(
        gguf_file="qwen2.5-0.5b-instruct-q4_k_m.gguf",
        hf_repo="Qwen/Qwen2.5-0.5B-Instruct-GGUF",
    ),
    description="Tiny Qwen for CI testing - maps to QwQ-32B, Qwen3-8B, Qwen3-Coder",
    tags=["ci", "test", "qwen", "tiny", "llamacpp"],
)

# CI test model for OLMo family (OLMo3-32B-Think)
# Uses OLMo-2-1B - official AllenAI GGUF
CI_OLMO_TINY = ModelSpec(
    model_id="ci-test/olmo-tiny",
    name="CI-OLMo-Tiny",
    provider="llamacpp",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.REASONING,
        ModelCapability.THINKING,
    ],
    task_scores={
        TaskType.REASONING: 0.10,
        TaskType.THINKING: 0.10,
        TaskType.EVALUATION: 0.10,
    },
    context_length=512,
    parameters_b=1.0,
    memory_mb=600,  # Q2_K ~600MB
    default_temperature=0.6,
    default_max_tokens=64,
    llamacpp_config=LlamaCppConfig(
        gguf_file="OLMo-2-0425-1B-Q4_K_M.gguf",
        hf_repo="allenai/OLMo-2-0425-1B-GGUF",
    ),
    description="Tiny OLMo for CI testing - maps to OLMo3-32B-Think",
    tags=["ci", "test", "olmo", "tiny", "llamacpp"],
)

# CI test model for GLM family (GLM-4.6V-Flash)
# Uses glm-edge-4b - official THUDM GGUF, smallest available
CI_GLM_SMALL = ModelSpec(
    model_id="ci-test/glm-small",
    name="CI-GLM-Small",
    provider="llamacpp",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.REASONING,
        ModelCapability.FUNCTION_CALLING,
    ],
    task_scores={
        TaskType.CHAT: 0.10,
        TaskType.REASONING: 0.10,
        TaskType.SWARM_AGENT: 0.10,
    },
    context_length=512,
    parameters_b=4.0,
    memory_mb=2500,  # Larger but still fits CI runner
    default_temperature=0.7,
    default_max_tokens=64,
    llamacpp_config=LlamaCppConfig(
        gguf_file="glm-edge-4b-chat-q4_k_m.gguf",
        hf_repo="THUDM/glm-edge-4b-chat-gguf",
    ),
    description="Small GLM for CI testing - maps to GLM-4.6V-Flash",
    tags=["ci", "test", "glm", "small", "llamacpp"],
)

# CI test model for Mistral family (Mistral-7B)
# Uses Mistral-7B Q2_K - smallest quantization of smallest Mistral
CI_MISTRAL_TINY = ModelSpec(
    model_id="ci-test/mistral-tiny",
    name="CI-Mistral-Tiny",
    provider="llamacpp",
    capabilities=[
        ModelCapability.CHAT,
        ModelCapability.CODING,
        ModelCapability.FUNCTION_CALLING,
    ],
    task_scores={
        TaskType.CHAT: 0.10,
        TaskType.CODING: 0.10,
        TaskType.SWARM_AGENT: 0.10,
    },
    context_length=512,
    parameters_b=7.0,
    memory_mb=2500,  # Q2_K ~2.5GB
    default_temperature=0.7,
    default_max_tokens=64,
    llamacpp_config=LlamaCppConfig(
        gguf_file="mistral-7b-instruct-v0.2.Q2_K.gguf",
        hf_repo="TheBloke/Mistral-7B-Instruct-v0.2-GGUF",
    ),
    description="Tiny Mistral for CI testing - maps to Mistral-7B",
    tags=["ci", "test", "mistral", "tiny", "llamacpp"],
)


# Mapping from production model IDs to CI test equivalents
CI_MODEL_MAPPING: dict[str, str] = {
    # Qwen family → CI_QWEN_TINY
    "Qwen/QwQ-32B": "ci-test/qwen-tiny",
    "Qwen/Qwen3-8B": "ci-test/qwen-tiny",
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": "ci-test/qwen-tiny",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B": "ci-test/qwen-tiny",
    # OLMo family → CI_OLMO_TINY
    "allenai/Olmo-3-32B-Think": "ci-test/olmo-tiny",
    # GLM family → CI_GLM_SMALL
    "zai-org/GLM-4.6V-Flash": "ci-test/glm-small",
    # Mistral family → CI_MISTRAL_TINY
    "mistralai/Mistral-7B-Instruct-v0.3": "ci-test/mistral-tiny",
    "mistralai/Devstral-Small-2-24B-Instruct-2512": "ci-test/mistral-tiny",
    "Qwen/Qwen3.8-27B": "ci-test/qwen-tiny",
    # Orchestration → Use Qwen (closest to Llama-based NVIDIA model)
    "nvidia/Orchestrator-8B": "ci-test/qwen-tiny",
}


def get_ci_model(production_model_id: str) -> ModelSpec | None:
    """Get the CI test equivalent for a production model.

    Args:
        production_model_id: The production model's HuggingFace ID

    Returns:
        CI test ModelSpec if mapping exists, None otherwise

    Usage:
        # In test fixtures
        if os.environ.get("GAIUS_CI_MODE"):
            model = get_ci_model("Qwen/QwQ-32B") or CI_QWEN_TINY
    """
    ci_model_id = CI_MODEL_MAPPING.get(production_model_id)
    if ci_model_id == "ci-test/qwen-tiny":
        return CI_QWEN_TINY
    elif ci_model_id == "ci-test/olmo-tiny":
        return CI_OLMO_TINY
    elif ci_model_id == "ci-test/glm-small":
        return CI_GLM_SMALL
    elif ci_model_id == "ci-test/mistral-tiny":
        return CI_MISTRAL_TINY
    return None


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
            QWEN38_27B,
            META_LLAMA_3_1_8B_INSTRUCT,
            QWEN3_8B,
            # Local vLLM models
            QWQ_32B,
            DEEPSEEK_R1_DISTILL,
            ORCHESTRATOR_8B,
            GLM_46V_FLASH,
            MISTRAL_7B,
            QWEN3_CODER,
            # On-demand capabilities (open-thinking)
            OLMO3_32B_THINK,
            # Embedding models
            COLBERT_ZERO,
            NOMIC_EMBED_TEXT,
            NOMIC_EMBED_VISION,
            # API models
            GROK_2,
            GPT4O_MINI,
            # CLT models (interpretability)
            CLT_QWEN3_1_7B,
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
    ) -> ModelSpec:
        """Get the best model for a task.

        Args:
            task: Task type to find model for
            require_local: If True, only return local models
            exclude_providers: Providers to exclude

        Returns:
            Best matching ModelSpec

        Raises:
            RuntimeError: If no model is registered for the task
        """
        exclude = set(exclude_providers or [])
        if require_local:
            exclude.update(["openai", "xai"])

        priorities = self._task_priorities.get(task, [])

        for model_id in priorities:
            model = self._models[model_id]
            if model.provider not in exclude:
                return model

        raise RuntimeError(
            f"No model registered for task: {task.name}\n"
            f"  Register a model with task_scores[{task.name}] > 0\n"
            f"  Guru Meditation: #MOD.00000001.NOTASK"
        )

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
) -> ModelSpec:
    """Convenience function to get best model for a task.

    Raises:
        RuntimeError: If no model is registered for the task
    """
    registry = get_model_registry()
    return registry.get_for_task(task, require_local, exclude_providers)
