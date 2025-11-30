"""Model router for phase-based model selection.

Routes inference requests to appropriate models based on workflow phase:
- exploration: Fast local model (e.g., Qwen3) for initial analysis
- synthesis: optillm with COT for deep reasoning
- evaluation: Frontier model (Claude) for critical assessment

Usage:
    from gaius.inference.router import ModelRouter, WorkflowPhase

    router = ModelRouter()

    # Route by phase
    config = router.get_config(WorkflowPhase.SYNTHESIS)

    # Or use convenience methods
    result = await router.explore(prompt)
    result = await router.synthesize(prompt)
    result = await router.evaluate(prompt)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .config import InferenceConfig, InferenceBackend, OptillmTechnique


class WorkflowPhase(Enum):
    """Workflow phases with different model requirements."""

    EXPLORATION = "exploration"  # Fast, local model for discovery
    SYNTHESIS = "synthesis"  # Deep reasoning with optillm
    EVALUATION = "evaluation"  # Frontier model for assessment
    SWARM = "swarm"  # Multi-agent with balanced models


@dataclass
class PhaseConfig:
    """Configuration for a workflow phase."""

    phase: WorkflowPhase
    model: str
    backend: InferenceBackend
    technique: OptillmTechnique = OptillmTechnique.NONE
    temperature: float = 0.7
    max_tokens: int = 2048

    def to_inference_config(self, base: InferenceConfig) -> InferenceConfig:
        """Convert to InferenceConfig with these settings."""
        return InferenceConfig(
            backend=self.backend,
            fallback_backend=base.fallback_backend,
            model=self.model,
            fallback_model=base.fallback_model,
            optillm_url=base.optillm_url,
            optillm_technique=self.technique,
            vllm_url=base.vllm_url,
            openai_api_key=base.openai_api_key,
            brave_api_key=base.brave_api_key,
            offline_mode=base.offline_mode,
            timeout=base.timeout,
            max_tokens=self.max_tokens,
        )


# Default phase configurations
DEFAULT_PHASE_CONFIGS: dict[WorkflowPhase, PhaseConfig] = {
    WorkflowPhase.EXPLORATION: PhaseConfig(
        phase=WorkflowPhase.EXPLORATION,
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        backend=InferenceBackend.VLLM,
        technique=OptillmTechnique.NONE,
        temperature=0.7,
        max_tokens=1024,
    ),
    WorkflowPhase.SYNTHESIS: PhaseConfig(
        phase=WorkflowPhase.SYNTHESIS,
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        backend=InferenceBackend.OPTILLM,
        technique=OptillmTechnique.COT_REFLECTION,
        temperature=0.6,
        max_tokens=2048,
    ),
    WorkflowPhase.EVALUATION: PhaseConfig(
        phase=WorkflowPhase.EVALUATION,
        model="claude-sonnet-4-20250514",
        backend=InferenceBackend.OPENAI,  # Uses OpenAI-compatible endpoint
        technique=OptillmTechnique.NONE,
        temperature=0.5,
        max_tokens=2048,
    ),
    WorkflowPhase.SWARM: PhaseConfig(
        phase=WorkflowPhase.SWARM,
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        backend=InferenceBackend.OPTILLM,
        technique=OptillmTechnique.NONE,  # Speed over depth for parallel agents
        temperature=0.7,
        max_tokens=1024,
    ),
}


class ModelRouter:
    """Routes inference requests to appropriate models by phase.

    Supports phase-based routing with fallback handling.
    """

    def __init__(
        self,
        base_config: InferenceConfig | None = None,
        phase_configs: dict[WorkflowPhase, PhaseConfig] | None = None,
    ):
        """Initialize router.

        Args:
            base_config: Base inference configuration
            phase_configs: Phase-specific configurations (default: use defaults)
        """
        if base_config is None:
            base_config = InferenceConfig.from_env()
        self.base_config = base_config

        if phase_configs is None:
            phase_configs = DEFAULT_PHASE_CONFIGS.copy()
        self.phase_configs = phase_configs

        # Apply HOCON config overrides if available
        self._apply_hocon_config()

    def _apply_hocon_config(self) -> None:
        """Apply overrides from HOCON config."""
        try:
            from ..core.config import get_config

            config = get_config()
            phase_models = config.inference.phase_models

            # Override exploration model
            if phase_models.exploration:
                self.phase_configs[WorkflowPhase.EXPLORATION].model = (
                    phase_models.exploration
                )

            # Override synthesis model
            if phase_models.synthesis:
                self.phase_configs[WorkflowPhase.SYNTHESIS].model = (
                    phase_models.synthesis
                )

            # Override evaluation model
            if phase_models.evaluation:
                self.phase_configs[WorkflowPhase.EVALUATION].model = (
                    phase_models.evaluation
                )

            # Apply optillm technique override
            if config.inference.optillm.technique:
                try:
                    technique = OptillmTechnique(config.inference.optillm.technique)
                    self.phase_configs[WorkflowPhase.SYNTHESIS].technique = technique
                except ValueError:
                    pass

        except Exception:
            pass  # HOCON config not available, use defaults

    def get_config(self, phase: WorkflowPhase) -> InferenceConfig:
        """Get inference config for a workflow phase.

        Args:
            phase: Workflow phase

        Returns:
            InferenceConfig configured for the phase
        """
        phase_config = self.phase_configs.get(phase)
        if phase_config is None:
            return self.base_config

        return phase_config.to_inference_config(self.base_config)

    def get_phase_config(self, phase: WorkflowPhase) -> PhaseConfig:
        """Get phase configuration.

        Args:
            phase: Workflow phase

        Returns:
            PhaseConfig for the phase
        """
        return self.phase_configs.get(
            phase, DEFAULT_PHASE_CONFIGS[WorkflowPhase.EXPLORATION]
        )

    async def route(
        self,
        prompt: str,
        phase: WorkflowPhase,
        **kwargs: Any,
    ) -> Any:
        """Route a prompt to the appropriate model.

        Args:
            prompt: The prompt to send
            phase: Workflow phase for model selection
            **kwargs: Additional arguments for the inference call

        Returns:
            Inference response
        """
        config = self.get_config(phase)
        phase_config = self.get_phase_config(phase)

        # Override temperature if not specified
        if "temperature" not in kwargs:
            kwargs["temperature"] = phase_config.temperature

        # Override max_tokens if not specified
        if "max_tokens" not in kwargs:
            kwargs["max_tokens"] = phase_config.max_tokens

        # Get inference client and call
        try:
            from . import get_client, Message

            client = get_client()
            return await client.complete(
                [Message(role="user", content=prompt)], **kwargs
            )
        except Exception as e:
            # Return error response
            from dataclasses import dataclass

            @dataclass
            class ErrorResponse:
                content: str
                error: str
                model: str = ""

            return ErrorResponse(
                content="",
                error=str(e),
                model=config.model,
            )

    async def explore(self, prompt: str, **kwargs: Any) -> Any:
        """Run exploration phase inference."""
        return await self.route(prompt, WorkflowPhase.EXPLORATION, **kwargs)

    async def synthesize(self, prompt: str, **kwargs: Any) -> Any:
        """Run synthesis phase inference."""
        return await self.route(prompt, WorkflowPhase.SYNTHESIS, **kwargs)

    async def evaluate(self, prompt: str, **kwargs: Any) -> Any:
        """Run evaluation phase inference."""
        return await self.route(prompt, WorkflowPhase.EVALUATION, **kwargs)

    async def swarm(self, prompt: str, **kwargs: Any) -> Any:
        """Run swarm phase inference."""
        return await self.route(prompt, WorkflowPhase.SWARM, **kwargs)


# Module-level singleton
_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """Get or create model router singleton."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
