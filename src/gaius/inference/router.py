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


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Endpoint Router for Distributed GPU Deployment
# ═══════════════════════════════════════════════════════════════════════════════

from dataclasses import field

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@dataclass
class EndpointConfig:
    """Configuration for a vLLM endpoint."""

    name: str
    url: str
    models: list[str] = field(default_factory=list)
    gpus: list[int] = field(default_factory=list)
    tensor_parallel: int = 1
    api_key: str = "sk-vllm"
    priority: int = 0  # Higher = preferred for overflow
    healthy: bool = True


@dataclass
class EndpointRouterConfig:
    """Configuration for the multi-endpoint router."""

    endpoints: dict[str, EndpointConfig] = field(default_factory=dict)
    model_routing: dict[str, str] = field(default_factory=dict)
    default_endpoint: str = "coding"
    failover_enabled: bool = True


class EndpointRouter:
    """Routes inference to appropriate vLLM endpoints based on model/role.

    Manages multiple vLLM endpoints across GPUs, handles failover,
    and supports role-specific model selection.

    Usage:
        from gaius.inference.router import get_endpoint_router

        router = get_endpoint_router()
        result = await router.complete(
            messages=[Message(role="user", content="Hello")],
            model="Qwen/QwQ-32B",  # Routes to reasoning endpoint
        )

        # Or route by agent role
        from gaius.agents.roles import AgentRole
        result = await router.complete_for_role(
            messages=[...],
            role=AgentRole.LEADER,
        )
    """

    def __init__(self, config: EndpointRouterConfig | None = None):
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "openai package required. Install with: uv sync --extra inference"
            )

        self.config = config or self._load_config()
        self._clients: dict[str, AsyncOpenAI] = {}
        self._init_clients()

    def _load_config(self) -> EndpointRouterConfig:
        """Load router config from application config."""
        try:
            from ..core.config import get_config

            app_config = get_config()
            inference = app_config._raw.get("gaius", {}).get("inference", {})

            endpoints_raw = inference.get("endpoints", {})
            model_routing = inference.get("model_routing", {})

            endpoints = {}
            for name, ep in endpoints_raw.items():
                if isinstance(ep, dict):
                    endpoints[name] = EndpointConfig(
                        name=name,
                        url=ep.get("url", f"http://localhost:808{len(endpoints)+1}/v1"),
                        models=ep.get("models", []),
                        gpus=ep.get("gpus", []),
                        tensor_parallel=ep.get("tensor_parallel", 1),
                    )

            return EndpointRouterConfig(
                endpoints=endpoints,
                model_routing={k: v for k, v in model_routing.items() if k != "default"},
                default_endpoint=model_routing.get("default", "coding"),
            )

        except Exception:
            # Fallback to minimal config
            return EndpointRouterConfig(
                endpoints={
                    "default": EndpointConfig(
                        name="default",
                        url="http://localhost:8088/v1",
                    )
                },
                default_endpoint="default",
            )

    def _init_clients(self) -> None:
        """Initialize OpenAI clients for each endpoint."""
        for name, endpoint in self.config.endpoints.items():
            self._clients[name] = AsyncOpenAI(
                api_key=endpoint.api_key,
                base_url=endpoint.url,
                timeout=60,
            )

    def get_endpoint_for_model(self, model: str) -> str:
        """Get the endpoint name that serves a model."""
        # Check explicit routing
        if model in self.config.model_routing:
            return self.config.model_routing[model]

        # Check which endpoints have this model
        for name, endpoint in self.config.endpoints.items():
            if model in endpoint.models:
                return name

        return self.config.default_endpoint

    def get_endpoint_for_role(self, role) -> str:
        """Get the best endpoint for an agent role."""
        from ..agents.roles import get_role

        role_def = get_role(role)

        # Use role's preferred model
        if role_def.preferred_model_id:
            return self.get_endpoint_for_model(role_def.preferred_model_id)

        # Match by capabilities
        for name, endpoint in self.config.endpoints.items():
            if "reasoning" in role_def.model_capabilities and "reasoning" in name:
                return name
            if "coding" in role_def.model_capabilities and "coding" in name:
                return name

        return self.config.default_endpoint

    async def complete(
        self,
        messages: list,
        model: str | None = None,
        endpoint: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ):
        """Complete a conversation using appropriate endpoint.

        Args:
            messages: Chat messages (list of Message or dicts)
            model: Model to use (determines endpoint if not specified)
            endpoint: Explicit endpoint override
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            CompletionResult with response
        """
        from .client import CompletionResult

        # Determine endpoint
        if endpoint is None:
            if model:
                endpoint = self.get_endpoint_for_model(model)
            else:
                endpoint = self.config.default_endpoint

        # Get client
        client = self._clients.get(endpoint)
        if client is None:
            # Fallback to default
            client = list(self._clients.values())[0] if self._clients else None
            if client is None:
                raise ValueError(f"No endpoints available")

        # Get model for endpoint if not specified
        if model is None:
            ep_config = self.config.endpoints.get(endpoint)
            if ep_config and ep_config.models:
                model = ep_config.models[0]
            else:
                model = "default"

        # Convert messages
        openai_messages = []
        for m in messages:
            if hasattr(m, "role"):
                openai_messages.append({"role": m.role, "content": m.content})
            else:
                openai_messages.append(m)

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=openai_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            choice = response.choices[0]
            usage = response.usage

            return CompletionResult(
                content=choice.message.content or "",
                model=response.model,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            )

        except Exception as e:
            # Try failover if enabled
            if self.config.failover_enabled:
                return await self._failover_complete(
                    messages, model, endpoint, temperature, max_tokens, e
                )
            raise

    async def _failover_complete(
        self,
        messages: list,
        model: str,
        failed_endpoint: str,
        temperature: float,
        max_tokens: int,
        original_error: Exception,
    ):
        """Attempt completion on alternate endpoints."""
        from .client import CompletionResult

        # Mark endpoint unhealthy
        if failed_endpoint in self.config.endpoints:
            self.config.endpoints[failed_endpoint].healthy = False

        # Try other endpoints
        for name, ep in self.config.endpoints.items():
            if name != failed_endpoint and ep.healthy:
                try:
                    return await self.complete(
                        messages=messages,
                        model=None,  # Use endpoint's default
                        endpoint=name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception:
                    continue

        # All endpoints failed - return error result
        return CompletionResult(
            content="",
            model=model or "unknown",
            input_tokens=0,
            output_tokens=0,
            raw_response={"error": str(original_error)},
        )

    async def complete_for_role(
        self,
        messages: list,
        role,
        **kwargs,
    ):
        """Complete using the best endpoint for an agent role."""
        from ..agents.roles import get_role

        role_def = get_role(role)
        endpoint = self.get_endpoint_for_role(role)

        return await self.complete(
            messages=messages,
            model=role_def.preferred_model_id,
            endpoint=endpoint,
            temperature=role_def.temperature,
            max_tokens=role_def.max_tokens,
            **kwargs,
        )

    async def health_check(self) -> dict[str, bool]:
        """Check health of all endpoints."""
        import httpx

        results = {}

        async with httpx.AsyncClient() as client:
            for name, endpoint in self.config.endpoints.items():
                try:
                    base_url = endpoint.url.rstrip("/v1")
                    r = await client.get(f"{base_url}/v1/models", timeout=5)
                    endpoint.healthy = r.status_code == 200
                    results[name] = endpoint.healthy
                except Exception:
                    endpoint.healthy = False
                    results[name] = False

        return results

    def get_status(self) -> dict[str, Any]:
        """Get router status summary."""
        return {
            "endpoints": {
                name: {
                    "url": ep.url,
                    "models": ep.models,
                    "gpus": ep.gpus,
                    "healthy": ep.healthy,
                }
                for name, ep in self.config.endpoints.items()
            },
            "model_routing": self.config.model_routing,
            "default_endpoint": self.config.default_endpoint,
        }


# Module-level singleton for endpoint router
_endpoint_router: EndpointRouter | None = None


def get_endpoint_router() -> EndpointRouter:
    """Get or create the multi-endpoint router singleton."""
    global _endpoint_router
    if _endpoint_router is None:
        _endpoint_router = EndpointRouter()
    return _endpoint_router
