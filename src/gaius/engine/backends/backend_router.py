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
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import AgentConfig, EngineConfig
from ..metrics import EngineMetrics
from ..resources import ResourceManager
from .optillm_controller import OptillmController, OptillmRequest, OptillmResponse, OptillmTechnique
from .vllm_controller import VLLMController, VLLMProcess, VLLMRequest, VLLMResponse
from .external.router import ExternalInferenceRouter, get_external_router
from gaius.core.budgets import REASONING_MAX_TOKENS

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
        source_context: Provenance context for HX exchange tracking (external backends)
    """

    messages: list[dict[str, Any]]
    agent_alias: str
    temperature: float = 0.7
    max_tokens: int = REASONING_MAX_TOKENS
    technique: Optional[str] = None
    # Dual-constraint fulfilment plan (a gaius.engine.capabilities
    # CapabilityPlan from a capabilities[] request); None = legacy routing.
    plan: Optional[Any] = None
    source_context: Optional[dict[str, Any]] = None
    enable_thinking: bool = True
    reasoning_effort: str = "xhigh"
    preserve_thinking: bool = True
    extra_body: dict[str, Any] | None = None


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
        exchange_id: UUID of captured exchange (external backends only)
        request_hash: SHA-256 hash for lineage linking (external backends only)
    """

    content: str
    model: str
    backend: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    technique: Optional[str] = None
    error: Optional[str] = None
    exchange_id: Optional[str] = None
    request_hash: Optional[str] = None
    reasoning_content: str = ""
    finish_reason: str = ""
    # Structured tool calls the engine parsed (Engine-First; see VLLMResponse).
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # Reasoning layers a dual-constraint fulfilment produced, in order (model
    # layer first): {"layer": "model"|"method", "producer", "text", "tokens"}.
    reasoning_layers: list[dict[str, Any]] = field(default_factory=list)
    # How the engine fulfilled a capabilities[] request, e.g.
    # "cot_reflection@engine/Qwen3.8-27B@vllm:8081". Empty on the legacy path.
    fulfilled_by: str = ""

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


def _metrics_provider(backend: str | None) -> str:
    """Map InferenceResponse.backend onto record_inference provider labels."""
    raw = (backend or "").strip().lower()
    if raw.startswith("external:"):
        return raw.split(":", 1)[1] or "external"
    if raw in ("cerebras", "xai", "bytez"):
        return raw
    if raw:
        return "local"
    return ""


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
        """Get configuration for an agent (legacy instruct → thinking)."""
        from ..config import get_agent_by_alias

        return get_agent_by_alias(self.config, agent_alias)

    async def route(self, request: InferenceRequest) -> InferenceResponse:
        """Route an inference request to the appropriate backend.

        Args:
            request: The inference request

        Returns:
            InferenceResponse from the selected backend
        """
        from ..config import resolve_agent_name

        request.agent_alias = resolve_agent_name(request.agent_alias)
        agent_config = self.get_agent_config(request.agent_alias)

        response: InferenceResponse

        if not agent_config:
            # Check for dynamically created vLLM endpoint
            proc = self.vllm.get_process(request.agent_alias)
            if proc and proc.status.value == "healthy":
                logger.info(f"Routing to dynamic vLLM endpoint: {request.agent_alias}")
                response = await self._route_to_dynamic_vllm(request, proc)
            else:
                from ..config import GURU_NOAGENT

                response = InferenceResponse(
                    content="",
                    model="",
                    backend="",
                    error=f"{GURU_NOAGENT} unknown agent: {request.agent_alias}",
                )
        else:
            # Determine backend
            backend = agent_config.backend.lower()

            plan = getattr(request, "plan", None)
            # Dual-constraint fulfilment (capabilities[] conjunction): a planned
            # method runs engine-natively (single-call scaffold over vLLM — BOTH
            # reasoning layers captured) or through optillm (method layer only).
            if plan is not None and getattr(plan, "method", None):
                if getattr(plan, "engine_native", False):
                    response = await self._fulfil_engine_native(request, agent_config)
                else:
                    request.technique = plan.method
                    response = await self._route_to_optillm(
                        request, agent_config, planned=True
                    )
            # If technique is specified, route through optillm for optimization
            # optillm acts as a proxy that applies the technique then forwards to vLLM
            elif request.technique and backend == "vllm":
                logger.info(
                    f"Routing {request.agent_alias} through optillm "
                    f"(technique={request.technique})"
                )
                response = await self._route_to_optillm(request, agent_config)
            elif backend == "optillm":
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

        # Record metrics at core layer - ALL inference flows through here.
        # Split in/out must be passed: the total counter is not a substitute
        # (yield tape / tokens_in_total / tokens_out_total stay at 0 otherwise).
        metrics = EngineMetrics.get_instance()
        tokens_in = int(response.input_tokens or 0)
        tokens_out = int(response.output_tokens or 0)
        tokens = tokens_in + tokens_out
        metrics.record_inference(
            model=request.agent_alias,
            latency_ms=response.latency_ms,
            tokens=tokens,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            success=response.error is None,
            technique=response.technique or "",
            provider=_metrics_provider(response.backend),
        )

        return response

    async def _route_to_optillm(
        self,
        request: InferenceRequest,
        agent_config: AgentConfig,
        planned: bool = False,
    ) -> InferenceResponse:
        """Route request to optillm backend.

        Engine-First Architecture: Agents configured with backend="optillm"
        MUST route through optillm. There is no fallback to direct vLLM.
        If optillm is unhealthy, the request fails fast with an actionable
        error. The OptillmController watchdog handles auto-restart; manual
        recovery is available via /health fix optillm.

        Args:
            request: The inference request
            agent_config: Agent configuration
            planned: True when the technique came from a dual-constraint
                capabilities[] plan — unknown techniques then fail fast
                (#EP.00000020.NOMIX) instead of degrading to pass-through,
                and the method reasoning layer is built from the scaffold.

        Returns:
            InferenceResponse from optillm (error set if unhealthy)
        """
        # Determine technique
        technique_str = request.technique or agent_config.optillm_technique
        try:
            technique = OptillmTechnique(technique_str) if technique_str else OptillmTechnique.COT_REFLECTION
        except ValueError:
            if planned:
                from ..capabilities import GURU_NOMIX, offered_methods

                return InferenceResponse(
                    content="",
                    model=agent_config.model,
                    backend="optillm",
                    error=(
                        f"{GURU_NOMIX} technique {technique_str!r} is not servable; "
                        f"offered: {', '.join(offered_methods())}"
                    ),
                )
            logger.warning(
                "unknown optillm technique %r; passing through as NONE (legacy caller)",
                technique_str,
            )
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

        result = InferenceResponse(
            content=response.content,
            model=response.model,
            backend="optillm",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            technique=response.technique,
            error=response.error,
            # Forward what optillm gives; truncation stays visible through
            # the proxy hop (finish_reason was silently dropped before).
            reasoning_content=getattr(response, "reasoning_content", "") or "",
            finish_reason=getattr(response, "finish_reason", "") or "",
        )

        if planned and result.error is None:
            # Method layer from the technique scaffold (OPTILLM_RETURN_FULL_RESPONSE
            # keeps it in content). Tolerant when absent — never fabricate.
            # The model layer is dropped by the optillm hop; the servicer logs
            # #EP.00000021.METHODTRACE.
            from ..capabilities import split_cot_reflection

            method_trace, output = split_cot_reflection(result.content)
            if method_trace:
                result.content = output
                result.reasoning_layers.append(
                    {
                        "layer": "method",
                        "producer": f"{technique.value}@optillm",
                        "text": method_trace,
                        "tokens": 0,
                    }
                )
            result.fulfilled_by = f"{technique.value}@optillm/{result.model}"

        return result

    async def _fulfil_engine_native(
        self, request: InferenceRequest, agent_config: AgentConfig
    ) -> InferenceResponse:
        """Single-call technique (cot_reflection) applied by the ENGINE over vLLM.

        Captures BOTH reasoning layers — the model's native reasoning_content
        and the <thinking>/<reflection> scaffold — which the optillm proxy hop
        drops (that hop yields the method layer only). One vLLM call; metrics
        are recorded once by route() (never call self.route() from here).
        """
        from dataclasses import replace as _replace

        from ..capabilities import (
            compose_cot_reflection_messages,
            split_cot_reflection,
        )

        system_prompt: Optional[str] = None
        user_parts: list[str] = []
        for message in request.messages or []:
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "system" and system_prompt is None:
                system_prompt = content
            elif content:
                user_parts.append(content)
        prompt = "\n\n".join(user_parts)

        inner = _replace(
            request,
            messages=compose_cot_reflection_messages(system_prompt, prompt),
            technique=None,
            plan=None,
            enable_thinking=True,
            preserve_thinking=True,
        )
        response = await self._route_to_vllm(inner, agent_config)
        if response.error is not None:
            return response

        method_trace, output = split_cot_reflection(response.content)
        # vLLM usage does not surface a reasoning-token split yet — 0 is the
        # honest "unknown" per the proto contract.
        model_tokens = 0
        layers: list[dict[str, Any]] = []
        if response.reasoning_content:
            layers.append(
                {
                    "layer": "model",
                    "producer": response.model,
                    "text": response.reasoning_content,
                    "tokens": model_tokens,
                }
            )
        if method_trace:
            layers.append(
                {
                    "layer": "method",
                    "producer": "cot_reflection@engine",
                    "text": method_trace,
                    "tokens": max(0, int(response.output_tokens or 0) - model_tokens),
                }
            )
        response.content = output
        response.reasoning_layers = layers
        response.technique = "cot_reflection"  # metrics label parity with optillm path
        port = 0
        get_process = getattr(getattr(self, "vllm", None), "get_process", None)
        if callable(get_process):
            proc = get_process(request.agent_alias)
            port = int(getattr(proc, "port", 0) or 0)
        response.fulfilled_by = f"cot_reflection@engine/{response.model}@vllm:{port}"
        return response

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
                source_context=request.source_context,
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
                exchange_id=response.exchange_id,
                request_hash=response.request_hash,
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
            status = proc.status.value if proc else "absent"
            return InferenceResponse(
                content="",
                model=agent_config.model,
                backend="vllm",
                error=(
                    f"vLLM {request.agent_alias} is {status}, not HEALTHY.\n"
                    "  Guru: #EP.00000016.NOTREADY\n"
                    "  Complete does not wait out a 900s vLLM load. "
                    "Settings/boot starts light or medium Ask; retry when /gpu status is HEALTHY."
                ),
            )

        # Create vLLM request
        vllm_request = VLLMRequest(
            messages=request.messages,
            model=agent_config.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            agent_alias=request.agent_alias,
            enable_thinking=request.enable_thinking,
            reasoning_effort=request.reasoning_effort,
            preserve_thinking=request.preserve_thinking,
            extra_body=request.extra_body or {},
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
            reasoning_content=response.reasoning_content,
            finish_reason=getattr(response, "finish_reason", ""),
            tool_calls=getattr(response, "tool_calls", []) or [],
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
            enable_thinking=request.enable_thinking,
            reasoning_effort=request.reasoning_effort,
            preserve_thinking=request.preserve_thinking,
            extra_body=request.extra_body or {},
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
            reasoning_content=response.reasoning_content,
            finish_reason=getattr(response, "finish_reason", ""),
            tool_calls=getattr(response, "tool_calls", []) or [],
        )

    async def complete(
        self,
        prompt: str,
        agent_alias: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = REASONING_MAX_TOKENS,
        technique: Optional[str] = None,
        plan: Optional[Any] = None,
        source_context: Optional[dict[str, Any]] = None,
        task_type: Optional[str] = None,
        enable_thinking: bool = True,
        reasoning_effort: str = "xhigh",
        preserve_thinking: bool = True,
        extra_body: dict[str, Any] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> InferenceResponse:
        """Convenience method for simple completions.

        Args:
            prompt: User prompt
            agent_alias: Agent to use
            system_prompt: Optional system prompt
            messages: Full OpenAI messages[], used verbatim instead of the
                system_prompt/prompt pair. A tool loop needs this: assistant
                tool_calls and their tool results must reach the chat template
                as their own turns, or the model re-issues calls it has made.
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            technique: Optional optillm technique
            source_context: Full provenance context for HX exchange tracking
            task_type: Convenience - auto-builds source_context if not provided

        Returns:
            InferenceResponse with exchange_id/request_hash for external backends
        """
        if messages is None:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

        # Auto-build source_context if task_type provided but not full context
        if source_context is None and task_type:
            source_context = {
                "agent_alias": agent_alias,
                "task_type": task_type,
            }

        request = InferenceRequest(
            messages=messages,
            agent_alias=agent_alias,
            temperature=temperature,
            max_tokens=max_tokens,
            technique=technique,
            plan=plan,
            source_context=source_context,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
            preserve_thinking=preserve_thinking,
            extra_body=extra_body,
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
