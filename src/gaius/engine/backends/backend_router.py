"""Backend router for inference request routing.

Routes inference requests to the appropriate backend (vLLM or optillm)
based on agent configuration.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from ..config import AgentConfig, EngineConfig
from ..resources import ResourceManager
from .optillm_controller import OptillmController, OptillmRequest, OptillmResponse, OptillmTechnique
from .vllm_controller import VLLMController, VLLMRequest, VLLMResponse

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
    ):
        """Initialize backend router.

        Args:
            config: Engine configuration
            resource_manager: Resource manager for GPU allocation
            vllm_controller: Optional pre-created vLLM controller
            optillm_controller: Optional pre-created optillm controller
        """
        self.config = config
        self.resource_manager = resource_manager

        # Create controllers if not provided
        self.vllm = vllm_controller or VLLMController(config, resource_manager)
        self.optillm = optillm_controller or OptillmController(config)

        logger.info("BackendRouter initialized")

    async def start(self) -> None:
        """Start the router and all backend controllers."""
        await self.vllm.start()
        await self.optillm.start()
        logger.info("BackendRouter started")

    async def stop(self) -> None:
        """Stop the router and all backend controllers."""
        await self.vllm.stop()
        await self.optillm.stop()
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

        if not agent_config:
            return InferenceResponse(
                content="",
                model="",
                backend="",
                error=f"Unknown agent: {request.agent_alias}",
            )

        # Determine backend
        backend = agent_config.backend.lower()

        if backend == "optillm":
            return await self._route_to_optillm(request, agent_config)
        elif backend == "vllm":
            return await self._route_to_vllm(request, agent_config)
        else:
            return InferenceResponse(
                content="",
                model=agent_config.model,
                backend=backend,
                error=f"Unknown backend: {backend}",
            )

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
        # Ensure endpoint is running
        proc = self.vllm.get_process(request.agent_alias)

        if not proc or proc.status.value != "healthy":
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

        return {
            "optillm": {
                "healthy": optillm_healthy,
                "enabled": self.optillm.is_enabled,
            },
            "vllm": self.vllm.get_status(),
        }

    def get_status(self) -> dict[str, Any]:
        """Get router status.

        Returns:
            Status dict with backend information
        """
        return {
            "optillm": self.optillm.get_status(),
            "vllm": self.vllm.get_status(),
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
