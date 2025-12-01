"""Inference configuration.

Configuration hierarchy (highest to lowest priority):
1. CLI flags: --backend=optillm --technique=cot_reflection --offline
2. Environment: GAIUS_BACKEND, GAIUS_OPTILLM_TECHNIQUE, BRAVE_API_KEY
3. Defaults: offline-first, optillm backend
"""

from dataclasses import dataclass, field
from enum import Enum
import os


class InferenceBackend(Enum):
    """Available inference backends."""

    OPTILLM = "optillm"  # optillm proxy (default) - adds optimization techniques
    VLLM = "vllm"  # Direct vLLM server (local fallback)
    XAI = "xai"  # XAI Grok - outsider model for evaluation/critique
    OPENAI = "openai"  # OpenAI API (last resort fallback)


class OptillmTechnique(Enum):
    """optillm optimization techniques.

    See: https://github.com/codelion/optillm
    """

    NONE = ""  # Passthrough (no optimization)
    COT_REFLECTION = "cot_reflection"  # Chain-of-Thought with Reflection
    BON = "bon"  # Best of N
    MOA = "moa"  # Mixture of Agents
    MCTS = "mcts"  # Monte Carlo Tree Search
    PLANSEARCH = "plansearch"  # Plan-based search
    SELF_CONSISTENCY = "self_consistency"  # Self-consistency
    PVG = "pvg"  # Prover-Verifier Game
    LEAP = "leap"  # Learning from principles
    RE2 = "re2"  # Re-reading
    MARS = "mars"  # Multi-agent reasoning
    CEPO = "cepo"  # Combined optimization


@dataclass
class InferenceConfig:
    """Configuration for the inference module.

    Tiered inference architecture:
    1. optillm → vLLM: Local inference with optimization techniques (COT, MOA, etc.)
    2. vLLM direct: Local fallback if optillm unavailable
    3. XAI Grok: Outsider model for objective evaluation/critique
    4. OpenAI: Last resort fallback
    """

    # Backend selection
    backend: InferenceBackend = InferenceBackend.OPTILLM
    fallback_backend: InferenceBackend | None = InferenceBackend.VLLM  # Local fallback first

    # Model settings (default matches local vLLM)
    model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    fallback_model: str = "gpt-4o-mini"

    # optillm settings (proxy to local vLLM with optimization)
    optillm_url: str = "http://localhost:8080/v1"
    optillm_technique: OptillmTechnique = OptillmTechnique.NONE

    # vLLM settings (direct local inference)
    vllm_url: str = "http://localhost:8088/v1"

    # XAI settings (outsider model for evaluation)
    xai_url: str = "https://api.x.ai/v1"
    xai_api_key: str | None = field(
        default_factory=lambda: os.getenv("XAI_API_KEY")
    )
    xai_model: str = "grok-3-latest"  # Default XAI model for evals

    # OpenAI settings (last resort fallback)
    openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )

    # Brave API settings
    brave_api_key: str | None = field(
        default_factory=lambda: os.getenv("BRAVE_API_KEY")
    )

    # Behavior
    offline_mode: bool = False  # If True, never use remote APIs
    timeout: float = 60.0  # Request timeout in seconds
    max_tokens: int = 2048  # Default max tokens

    @classmethod
    def from_env(cls) -> "InferenceConfig":
        """Load configuration from environment variables.

        Local-first: optillm→vLLM for inference, XAI for outsider evals.
        """
        backend_str = os.getenv("GAIUS_BACKEND", "optillm")
        technique_str = os.getenv("GAIUS_OPTILLM_TECHNIQUE", "")

        try:
            backend = InferenceBackend(backend_str)
        except ValueError:
            backend = InferenceBackend.OPTILLM

        try:
            technique = OptillmTechnique(technique_str)
        except ValueError:
            technique = OptillmTechnique.NONE

        return cls(
            backend=backend,
            optillm_technique=technique,
            optillm_url=os.getenv("GAIUS_OPTILLM_URL", "http://localhost:8080/v1"),
            vllm_url=os.getenv("GAIUS_VLLM_URL", "http://localhost:8088/v1"),
            xai_url=os.getenv("XAI_API_URL", "https://api.x.ai/v1"),
            xai_model=os.getenv("XAI_MODEL", "grok-3-latest"),
            model=os.getenv("GAIUS_MODEL", "Qwen/Qwen3-Coder-30B-A3B-Instruct"),
            fallback_model=os.getenv("GAIUS_FALLBACK_MODEL", "gpt-4o-mini"),
            offline_mode=os.getenv("GAIUS_OFFLINE", "").lower() in ("1", "true", "yes"),
            timeout=float(os.getenv("GAIUS_TIMEOUT", "60")),
            max_tokens=int(os.getenv("GAIUS_MAX_TOKENS", "2048")),
        )

    def with_technique(self, technique: OptillmTechnique | str) -> "InferenceConfig":
        """Return a new config with the specified technique."""
        if isinstance(technique, str):
            technique = OptillmTechnique(technique)
        return InferenceConfig(
            backend=self.backend,
            fallback_backend=self.fallback_backend,
            model=self.model,
            fallback_model=self.fallback_model,
            optillm_url=self.optillm_url,
            optillm_technique=technique,
            vllm_url=self.vllm_url,
            xai_url=self.xai_url,
            xai_api_key=self.xai_api_key,
            xai_model=self.xai_model,
            openai_api_key=self.openai_api_key,
            brave_api_key=self.brave_api_key,
            offline_mode=self.offline_mode,
            timeout=self.timeout,
            max_tokens=self.max_tokens,
        )
