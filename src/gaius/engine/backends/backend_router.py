"""Backend router for inference request routing.

Routes inference requests to the appropriate backend:
- vLLM: Local GPU inference via vLLM processes
- optillm: Prompt optimization proxy (local)
- external: Remote LLM APIs (Cerebras, XAI, Bytez) via ExternalInferenceRouter

Engine-First Architecture:
All inference flows through this router, ensuring centralized:
- Budget tracking (XAI/Cerebras per-token limits)
- Metrics collection
- Request routing based on agent configuration
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from ..config import AgentConfig, EngineConfig
from ..metrics import EngineMetrics
from ..resources import ResourceManager
from .optillm_controller import OptillmController, OptillmRequest, OptillmResponse, OptillmTechnique
from .vllm_controller import VLLMController, VLLMProcess, VLLMRequest, VLLMResponse
from .external.router import ExternalInferenceRouter, get_external_router

logger = logging.getLogger(__name__)


@dataclass
class InferenceRequest:
    """Unified inference request.

    Attributes:
        messages: Chat messages in OpenAI format
        agent_alias: Agent to route to (determines backend and model)
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        technique: optillm technique (for optillm backend)
    """

    messages: list[dict[str, str]]
    agent_alias: str
    temperature: float = 0.7
    max_tokens: int = 2048
    technique: Optional[str] = None


@dataclass
class InferenceResponse:
    """Unified inference response.

    Attributes:
        content: Generated text content
        model: Model that generated response
        backend: Backend that served the request ("vllm" or "optillm")
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Request latency in milliseconds
        technique: optillm technique if used
        error: Error message if request failed
    """

    content: str
    model: str
    backend: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    technique: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


class BackendRouter:
    """Routes inference requests to appropriate backends.

    Uses agent configuration to determine whether to route to
    vLLM (direct GPU inference) or optillm (prompt optimization proxy).
    """

    def __init__(
        self,
        config: EngineConfig,
        resource_manager: ResourceManager,
        vllm_controller: Optional[VLLMController] = None,
        optillm_controller: Optional[OptillmController] = None,
        external_router: Optional[ExternalInferenceRouter] = None,
    ):
        """Initialize backend router.

        Args:
            config: Engine configuration
            resource_manager: Resource manager for GPU allocation
            vllm_controller: Optional pre-created vLLM controller
            optillm_controller: Optional pre-created optillm controller
            external_router: Optional pre-created external router for Cerebras/XAI/Bytez
        """
        self.config = config
        self.resource_manager = resource_manager

        # Create controllers if not provided
        self.vllm = vllm_controller or VLLMController(config, resource_manager)
        self.optillm = optillm_controller or OptillmController(config)

        # External router for Cerebras/XAI/Bytez (lazy initialization via singleton)
        self._external = external_router

        logger.info("BackendRouter initialized")

    @property
    def external(self) -> ExternalInferenceRouter:
        """Get or create external router (lazy initialization via singleton)."""
        if self._external is None:
            self._external = get_external_router()
        return self._external

    async def start(self) -> None:
        """Start the router and all backend controllers."""
        await self.vllm.start()
        await self.optillm.start()
        logger.info("BackendRouter started")

    async def stop(self) -> None:
        """Stop the router and all backend controllers."""
        await self.vllm.stop()
        await self.optillm.stop()
        # Close external router if initialized
        if self._external:
            await self._external.close()
        logger.info("BackendRouter stopped")

    def get_agent_config(self, agent_alias: str) -> Optional[AgentConfig]:
        """Get configuration for an agent.

        Args:
            agent_alias: Agent identifier

        Returns:
            AgentConfig if found, None otherwise
        """
        return self.config.agents.get(agent_alias)

    async def route(self, request: InferenceRequest) -> InferenceResponse:
        """Route an inference request to the appropriate backend.

        Args:
            request: The inference request

        Returns:
            InferenceResponse from the selected backend
        """
        # Get agent configuration
        agent_config = self.get_agent_config(request.agent_alias)

        response: InferenceResponse

        if not agent_config:
            # Check for dynamically created vLLM endpoint
            proc = self.vllm.get_process(request.agent_alias)
            if proc and proc.status.value == "healthy":
                logger.info(f"Routing to dynamic vLLM endpoint: {request.agent_alias}")
                response = await self._route_to_dynamic_vllm(request, proc)
            else:
                response = InferenceResponse(
                    content="",
                    model="",
                    backend="",
                    error=f"Unknown agent: {request.agent_alias}",
                )
        else:
            # Determine backend
            backend = agent_config.backend.lower()

            if backend == "optillm":
                response = await self._route_to_optillm(request, agent_config)
            elif backend == "vllm":
                response = await self._route_to_vllm(request, agent_config)
            elif backend in ("external", "cerebras", "xai", "bytez"):
                response = await self._route_to_external(request, agent_config, backend)
            else:
                response = InferenceResponse(
                    content="",
                    model=agent_config.model,
                    backend=backend,
                    error=f"Unknown backend: {backend}",
                )

        # Record metrics at core layer - ALL inference flows through here
        metrics = EngineMetrics.get_instance()
        tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
        metrics.record_inference(
            model=request.agent_alias,
            latency_ms=response.latency_ms,
            tokens=tokens,
            success=response.error is None,
        )

        return response

    async def _route_to_optillm(
        self, request: InferenceRequest, agent_config: AgentConfig
    ) -> InferenceResponse:
        """Route request to optillm backend.

        Args:
            request: The inference request
            agent_config: Agent configuration

        Returns:
            InferenceResponse from optillm
        """
        # Determine technique
        technique_str = request.technique or agent_config.optillm_technique
        try:
            technique = OptillmTechnique(technique_str) if technique_str else OptillmTechnique.COT_REFLECTION
        except ValueError:
            technique = OptillmTechnique.NONE

        # Create optillm request
        optillm_request = OptillmRequest(
            messages=request.messages,
            model=agent_config.model,
            technique=technique,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            agent_alias=request.agent_alias,
        )

        # Execute request
        response = await self.optillm.complete(optillm_request)

        return InferenceResponse(
            content=response.content,
            model=response.model,
            backend="optillm",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            technique=response.technique,
            error=response.error,
        )

    async def _route_to_external(
        self, request: InferenceRequest, agent_config: AgentConfig, backend: str
    ) -> InferenceResponse:
        """Route request to external backend (Cerebras, XAI, Bytez).

        Engine-First Architecture: All external API calls go through the
        ExternalInferenceRouter which handles:
        - Budget tracking (per-token limits)
        - Provider selection
        - Exchange capture to Iceberg (training data)

        Args:
            request: The inference request
            agent_config: Agent configuration
            backend: Specific backend ("cerebras", "xai", "bytez") or "external" for auto

        Returns:
            InferenceResponse from external provider
        """
        import time

        start_time = time.time()

        # Determine provider from backend or agent config
        # "external" = auto-route, otherwise use specific provider
        provider = None if backend == "external" else backend

        # Determine model from agent config or request
        model = agent_config.model if agent_config else None

        try:
            response = await self.external.complete(
                messages=request.messages,
                provider=provider,
                model=model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            return InferenceResponse(
                content=response.content,
                model=response.model,
                backend=f"external:{response.provider}",
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=latency_ms,
                error=response.error,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return InferenceResponse(
                content="",
                model=model or "",
                backend=f"external:{backend}",
                latency_ms=latency_ms,
                error=str(e),
            )

    async def _route_to_vllm(
        self, request: InferenceRequest, agent_config: AgentConfig
    ) -> InferenceResponse:
        """Route request to vLLM backend.

        Args:
            request: The inference request
            agent_config: Agent configuration

        Returns:
            InferenceResponse from vLLM
        """
        # Debug logging for routing
        logger.info(
            f"BackendRouter._route_to_vllm: agent_alias={request.agent_alias}, "
            f"model={agent_config.model}, backend={agent_config.backend}"
        )

        # Ensure endpoint is running
        proc = self.vllm.get_process(request.agent_alias)

        if not proc or proc.status.value != "healthy":
            logger.info(
                f"Endpoint not healthy for {request.agent_alias}, "
                f"proc={proc.status.value if proc else 'None'}, attempting start"
            )
            # Try to start the endpoint
            try:
                proc = await self.vllm.start_endpoint(request.agent_alias, agent_config)
                if proc.status.value != "healthy":
                    return InferenceResponse(
                        content="",
                        model=agent_config.model,
                        backend="vllm",
                        error=f"Failed to start vLLM endpoint for {request.agent_alias}",
                    )
            except Exception as e:
                return InferenceResponse(
                    content="",
                    model=agent_config.model,
                    backend="vllm",
                    error=str(e),
                )

        # Create vLLM request
        vllm_request = VLLMRequest(
            messages=request.messages,
            model=agent_config.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            agent_alias=request.agent_alias,
        )

        # Execute request
        response = await self.vllm.complete(vllm_request)

        return InferenceResponse(
            content=response.content,
            model=response.model,
            backend="vllm",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            error=response.error,
        )

    async def _route_to_dynamic_vllm(
        self, request: InferenceRequest, proc: VLLMProcess
    ) -> InferenceResponse:
        """Route request to a dynamically created vLLM endpoint.

        This handles endpoints created by the scheduler that don't have
        static agent configuration. Uses the running process info directly.

        Args:
            request: The inference request
            proc: The running vLLM process info

        Returns:
            InferenceResponse from vLLM
        """
        # Create vLLM request using process info
        vllm_request = VLLMRequest(
            messages=request.messages,
            model=proc.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            agent_alias=request.agent_alias,
        )

        # Execute request
        response = await self.vllm.complete(vllm_request)

        return InferenceResponse(
            content=response.content,
            model=response.model,
            backend="vllm",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            error=response.error,
        )

    async def complete(
        self,
        prompt: str,
        agent_alias: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        technique: Optional[str] = None,
    ) -> InferenceResponse:
        """Convenience method for simple completions.

        Args:
            prompt: User prompt
            agent_alias: Agent to use
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            technique: Optional optillm technique

        Returns:
            InferenceResponse
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request = InferenceRequest(
            messages=messages,
            agent_alias=agent_alias,
            temperature=temperature,
            max_tokens=max_tokens,
            technique=technique,
        )

        return await self.route(request)

    async def ensure_agent_ready(self, agent_alias: str) -> bool:
        """Ensure an agent's backend is ready.

        For vLLM agents, starts the endpoint if not running.
        For optillm agents, verifies optillm is healthy.

        Args:
            agent_alias: Agent identifier

        Returns:
            True if agent is ready
        """
        agent_config = self.get_agent_config(agent_alias)
        if not agent_config:
            return False

        backend = agent_config.backend.lower()

        if backend == "optillm":
            return self.optillm.is_healthy

        elif backend == "vllm":
            proc = self.vllm.get_process(agent_alias)
            if proc and proc.status.value == "healthy":
                return True

            # Try to start
            try:
                proc = await self.vllm.start_endpoint(agent_alias, agent_config)
                return proc.status.value == "healthy"
            except Exception:
                return False

        return False

    async def health_check(self) -> dict[str, Any]:
        """Check health of all backends.

        Returns:
            Health status dict
        """
        optillm_healthy = await self.optillm.health_check()

        # Get external backends status (lazy initialization)
        external_status = {}
        if self._external:
            external_status = {
                "available": self._external.available_backends,
                "token_tier": self._external.token_tier_backends,
                "subscription_tier": self._external.subscription_tier_backends,
            }

        return {
            "optillm": {
                "healthy": optillm_healthy,
                "enabled": self.optillm.is_enabled,
            },
            "vllm": self.vllm.get_status(),
            "external": external_status,
        }

    def get_status(self) -> dict[str, Any]:
        """Get router status.

        Returns:
            Status dict with backend information
        """
        # Get external backends info (lazy initialization)
        external_info = {}
        if self._external:
            external_info = {
                "available": self._external.available_backends,
                "budget": self._external.budget.to_dict() if self._external.budget else {},
            }

        return {
            "optillm": self.optillm.get_status(),
            "vllm": self.vllm.get_status(),
            "external": external_info,
            "agents": {
                alias: {
                    "model": config.model,
                    "backend": config.backend,
                    "optillm_technique": config.optillm_technique,
                }
                for alias, config in self.config.agents.items()
            },
        }

    def list_agents_by_backend(self, backend: str) -> list[str]:
        """List agents using a specific backend.

        Args:
            backend: Backend name ("vllm" or "optillm")

        Returns:
            List of agent aliases
        """
        return [
            alias
            for alias, config in self.config.agents.items()
            if config.backend.lower() == backend.lower()
        ]

    @property
    def vllm_agents(self) -> list[str]:
        """Agents using vLLM backend."""
        return self.list_agents_by_backend("vllm")

    @property
    def optillm_agents(self) -> list[str]:
        """Agents using optillm backend."""
        return self.list_agents_by_backend("optillm")
