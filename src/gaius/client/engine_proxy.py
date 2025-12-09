"""Engine proxy that duck-types existing interfaces.

Provides drop-in replacements for GPUOrchestrator, InferenceScheduler,
and other components that delegate to gaius-engine via gRPC.

This enables the "dead code elimination" strategy where TUI/CLI/MCP
can be simplified to thin clients that communicate with the engine.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .grpc_client import GrpcEngineClient, get_grpc_client

logger = logging.getLogger(__name__)

# Type alias for backwards compatibility
EngineClient = GrpcEngineClient


async def get_client() -> GrpcEngineClient:
    """Get or create the gRPC engine client."""
    return await get_grpc_client()


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator Proxy
# ─────────────────────────────────────────────────────────────────────────────


class OrchestratorProxy:
    """Proxy for GPUOrchestrator that delegates to engine.

    Duck-types the GPUOrchestrator interface so existing code
    can use the engine without modification.

    Usage:
        # Instead of:
        from gaius.inference.orchestrator import get_orchestrator
        orch = get_orchestrator()

        # Use:
        from gaius.client.engine_proxy import get_orchestrator_proxy
        orch = await get_orchestrator_proxy()

        # Same API:
        await orch.start_endpoint("reasoning")
        status = orch.get_status()
    """

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy.

        Args:
            client: Connected gRPC engine client
        """
        self._client = client
        self._running = False

    async def start(self) -> None:
        """Start the orchestrator (no-op, engine manages this)."""
        self._running = True

    async def stop(self) -> None:
        """Stop the orchestrator."""
        self._running = False

    async def ensure_endpoint(self, endpoint: str) -> dict:
        """Ensure endpoint is running, starting if needed and resources available.

        This is the primary method for agent-first architecture. CLI and agents
        call this to ensure an endpoint is available before making requests.

        Args:
            endpoint: Endpoint/agent name

        Returns:
            Dict with:
                - healthy: bool - True if endpoint is ready
                - status: str - Endpoint status
                - port: int - Port if running
                - gpu_ids: list - Allocated GPUs
                - message: str - Error message if not healthy
        """
        result = await self._client.call(
            "Orchestrator", "ensure", {"endpoint": endpoint}
        )
        return result

    async def start_endpoint(self, endpoint: str) -> bool:
        """Start a vLLM endpoint.

        Args:
            endpoint: Endpoint/agent name

        Returns:
            True if started successfully
        """
        result = await self._client.call(
            "Orchestrator", "start", {"endpoint": endpoint}
        )
        return result.get("status") == "healthy"

    async def stop_endpoint(self, endpoint: str, timeout: float = 30.0) -> bool:
        """Stop a vLLM endpoint.

        Args:
            endpoint: Endpoint name
            timeout: Shutdown timeout

        Returns:
            True if stopped
        """
        result = await self._client.call(
            "Orchestrator", "stop", {"endpoint": endpoint}
        )
        return result.get("success", False)

    async def restart_endpoint(self, endpoint: str) -> bool:
        """Restart a vLLM endpoint."""
        result = await self._client.call(
            "Orchestrator", "restart", {"endpoint": endpoint}
        )
        return result.get("status") == "healthy"

    async def clean_start(
        self, endpoints: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Clean start with stale process cleanup.

        Args:
            endpoints: Endpoints to start

        Returns:
            Cleanup and startup results
        """
        return await self._client.call(
            "Orchestrator", "clean_start", {"endpoints": endpoints or ["reasoning"]}
        )

    async def cleanup_stale_processes(self) -> dict[str, Any]:
        """Kill stale vLLM processes."""
        result = await self.clean_start([])
        # Handle both old and new response formats
        if "cleanup" in result:
            return result.get("cleanup", {})
        # New format from CleanStartResponse
        return {
            "processes_found": result.get("processes_killed", 0),
            "processes_killed": result.get("processes_killed", 0),
        }

    def get_status(self) -> dict[str, Any]:
        """Get orchestrator status (sync wrapper)."""
        return asyncio.get_event_loop().run_until_complete(
            self._get_status_async()
        )

    async def _get_status_async(self) -> dict[str, Any]:
        """Get orchestrator status."""
        return await self._client.call("Orchestrator", "status", {})

    async def get_endpoint_status(self, endpoint: str) -> Optional[dict[str, Any]]:
        """Get status of a specific endpoint.

        Args:
            endpoint: Endpoint name

        Returns:
            Dict with status, port, gpu_ids, etc. or None if not found
        """
        status = await self._get_status_async()
        endpoints = status.get("endpoints", [])
        # Handle list format: [{"name": "reasoning", ...}, ...]
        if isinstance(endpoints, list):
            for ep in endpoints:
                if isinstance(ep, dict) and ep.get("name") == endpoint:
                    return ep
            return None
        # Handle dict format: {"reasoning": {...}, ...}
        return endpoints.get(endpoint)

    def get_logs(self, endpoint: str, lines: int = 50) -> list[str]:
        """Get endpoint logs (sync wrapper)."""
        return asyncio.get_event_loop().run_until_complete(
            self._get_logs_async(endpoint, lines)
        )

    async def _get_logs_async(self, endpoint: str, lines: int) -> list[str]:
        """Get endpoint logs."""
        result = await self._client.call(
            "Orchestrator", "logs", {"endpoint": endpoint, "lines": lines}
        )
        return result.get("logs", [])

    async def get_logs_async(self, endpoint: str, lines: int = 50) -> list[str]:
        """Get endpoint logs (async version)."""
        return await self._get_logs_async(endpoint, lines)

    def get_startup_progress(self, endpoint: str) -> tuple[str, float]:
        """Get startup progress for an endpoint."""
        status = self.get_status()
        endpoints = status.get("endpoints", [])
        # Handle list format: [{"name": "reasoning", ...}, ...]
        if isinstance(endpoints, list):
            for ep in endpoints:
                if isinstance(ep, dict) and ep.get("name") == endpoint:
                    return (ep.get("startup_message", ""), ep.get("startup_progress", 0.0))
            return ("Not started", 0.0)
        # Handle dict format: {"reasoning": {...}, ...}
        if endpoint in endpoints:
            ep = endpoints[endpoint]
            return (ep.get("startup_message", ""), ep.get("startup_progress", 0.0))
        return ("Not started", 0.0)

    async def health_check(self, endpoint: str) -> bool:
        """Check health of an endpoint."""
        status = await self._get_status_async()
        endpoints = status.get("endpoints", [])
        # Handle list format: [{"name": "reasoning", ...}, ...]
        if isinstance(endpoints, list):
            for ep in endpoints:
                if isinstance(ep, dict) and ep.get("name") == endpoint:
                    return ep.get("status") == "healthy"
            return False
        # Handle dict format: {"reasoning": {...}, ...}
        return endpoints.get(endpoint, {}).get("status") == "healthy"


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler Proxy
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CompletionResult:
    """Result from a completion request (matches existing interface)."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    technique: Optional[str] = None
    backend: Optional[str] = None
    raw_response: Optional[dict] = None


class SchedulerProxy:
    """Proxy for InferenceScheduler that delegates to engine.

    Duck-types the InferenceScheduler interface for drop-in replacement.
    """

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client

    async def complete(
        self,
        prompt: str,
        agent: str = "fast",
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        technique: Optional[str] = None,
    ) -> CompletionResult:
        """Complete a prompt.

        Args:
            prompt: User prompt
            agent: Agent to use
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            technique: Optional optillm technique

        Returns:
            CompletionResult
        """
        result = await self._client.call(
            "Scheduler",
            "complete",
            {
                "prompt": prompt,
                "agent": agent,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "technique": technique,
            },
        )

        return CompletionResult(
            content=result.get("content", ""),
            model=result.get("model", ""),
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            technique=result.get("technique"),
            backend=result.get("backend"),
            raw_response=result,
        )

    async def evaluate(
        self,
        prompt: str,
        force_xai: bool = False,
    ) -> CompletionResult:
        """Evaluate using tiered strategy.

        Args:
            prompt: Prompt to evaluate
            force_xai: Force XAI if budget allows

        Returns:
            CompletionResult
        """
        result = await self._client.call(
            "Scheduler",
            "evaluate",
            {
                "prompt": prompt,
                "force_xai": force_xai,
            },
        )

        return CompletionResult(
            content=result.get("content", ""),
            model=result.get("model", ""),
            raw_response=result,
        )

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status."""
        return asyncio.get_event_loop().run_until_complete(
            self._get_status_async()
        )

    async def _get_status_async(self) -> dict[str, Any]:
        """Get scheduler status."""
        return await self._client.call("Scheduler", "status", {})

    def get_metrics(self) -> dict[str, Any]:
        """Get inference metrics."""
        return asyncio.get_event_loop().run_until_complete(
            self._get_metrics_async()
        )

    async def _get_metrics_async(self) -> dict[str, Any]:
        """Get inference metrics."""
        return await self._client.call("Scheduler", "metrics", {})

    def get_xai_budget(self) -> dict[str, Any]:
        """Get XAI budget status."""
        return asyncio.get_event_loop().run_until_complete(
            self._get_budget_async()
        )

    async def _get_budget_async(self) -> dict[str, Any]:
        """Get XAI budget."""
        return await self._client.call("Scheduler", "budget", {})


# ─────────────────────────────────────────────────────────────────────────────
# Evolution Proxy
# ─────────────────────────────────────────────────────────────────────────────


class EvolutionProxy:
    """Proxy for EvolutionDaemon that delegates to engine.

    BDD Scenarios Supported:
    - Start/stop evolution daemon
    - Manual evolution trigger
    - View daemon status and recent cycles
    - View agent scores
    """

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client

    async def start(self) -> None:
        """Start the evolution daemon.

        BDD: "Start evolution daemon with '/evolve start'"
        """
        await self._client.call("Evolution", "start", {})

    async def stop(self) -> None:
        """Stop the evolution daemon.

        BDD: "Stop evolution daemon with '/evolve stop'"
        """
        await self._client.call("Evolution", "stop", {})

    async def trigger(self, agent_id: Optional[str] = None) -> dict[str, Any]:
        """Manually trigger evolution for an agent.

        BDD: "Manual evolution trigger with '/evolve trigger'"

        Args:
            agent_id: Agent to evolve (None = next in rotation)

        Returns:
            Evolution result
        """
        return await self._client.call(
            "Evolution", "trigger", {"agent_id": agent_id}
        )

    def get_status(self) -> dict[str, Any]:
        """Get evolution daemon status.

        BDD: "Evolution panel shows daemon status"
        """
        return asyncio.get_event_loop().run_until_complete(
            self._get_status_async()
        )

    async def _get_status_async(self) -> dict[str, Any]:
        """Get evolution status."""
        return await self._client.call("Evolution", "status", {})

    async def get_recent_cycles(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent evolution cycles.

        BDD: "Evolution panel shows recent cycles"

        Args:
            limit: Maximum cycles to return

        Returns:
            List of cycle dicts
        """
        result = await self._client.call(
            "Evolution", "recent_cycles", {"limit": limit}
        )
        return result.get("cycles", [])

    async def get_agent_scores(self) -> dict[str, dict[str, Any]]:
        """Get per-agent evolution scores.

        BDD: "Evolution panel shows agent scores"

        Returns:
            Dict mapping agent_id to score info
        """
        result = await self._client.call("Evolution", "agent_scores", {})
        return result.get("scores", {})


# ─────────────────────────────────────────────────────────────────────────────
# Health Proxy
# ─────────────────────────────────────────────────────────────────────────────


class HealthProxy:
    """Proxy for health monitoring.

    Features:
    - Comprehensive health checks
    - GPU utilization and detailed metrics
    - Endpoint health status
    - Health broadcast subscriptions
    """

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client
        self._health_callback = None

    async def check(self) -> dict[str, Any]:
        """Get comprehensive health status."""
        return await self._client.call("Health", "check", {})

    async def get_gpu_utilization(self) -> dict[int, float]:
        """Get GPU utilization percentages."""
        result = await self._client.call("Health", "gpu", {})
        return result.get("utilization", {})

    async def get_gpu_health(self) -> dict[int, dict[str, Any]]:
        """Get detailed GPU health (temperature, VRAM, etc.)."""
        result = await self._client.call("Health", "gpu_detailed", {})
        return result.get("gpus", {})

    async def get_endpoint_health(self) -> dict[str, dict[str, Any]]:
        """Get endpoint health status."""
        result = await self._client.call("Health", "endpoints", {})
        return result.get("endpoints", {})

    async def get_status(self) -> dict[str, Any]:
        """Get health service status."""
        return await self._client.call("Health", "status", {})

    def subscribe(self, callback) -> None:
        """Subscribe to health updates."""
        self._health_callback = callback
        self._client.subscribe_health(callback)

    def unsubscribe(self) -> None:
        """Unsubscribe from health updates."""
        if self._health_callback:
            self._client.unsubscribe_health(self._health_callback)
            self._health_callback = None


# ─────────────────────────────────────────────────────────────────────────────
# Compute Proxies
# ─────────────────────────────────────────────────────────────────────────────


class TDAProxy:
    """Proxy for TDA computation service."""

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client
        self._request_counter = 0

    async def compute(
        self,
        embeddings: list[list[float]],
        grid_coords: Optional[list[tuple[int, int]]] = None,
        max_dimension: int = 2,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Compute TDA features.

        Args:
            embeddings: High-dimensional embeddings
            grid_coords: Optional grid coordinates
            max_dimension: Maximum homology dimension
            force_refresh: Bypass cache

        Returns:
            TDA result dict
        """
        self._request_counter += 1
        return await self._client.call(
            "Compute",
            "tda",
            {
                "request_id": f"tda-{self._request_counter}",
                "embeddings": embeddings,
                "grid_coords": grid_coords,
                "max_dimension": max_dimension,
                "force_refresh": force_refresh,
            },
        )

    async def get_status(self) -> dict[str, Any]:
        """Get TDA service status."""
        return await self._client.call("Compute", "tda_status", {})


class GridProxy:
    """Proxy for grid projection service."""

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client
        self._request_counter = 0

    async def project(
        self,
        embeddings: list[list[float]],
        metadata: Optional[list[dict[str, Any]]] = None,
        method: str = "umap",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Project embeddings to 19x19 grid.

        Args:
            embeddings: High-dimensional embeddings
            metadata: Optional metadata for each embedding
            method: Projection method (umap or pca)
            force_refresh: Reset fitted projector

        Returns:
            Projection result dict
        """
        self._request_counter += 1
        return await self._client.call(
            "Compute",
            "project",
            {
                "request_id": f"grid-{self._request_counter}",
                "embeddings": embeddings,
                "metadata": metadata or [],
                "method": method,
                "force_refresh": force_refresh,
            },
        )

    async def project_query(
        self, query_embedding: list[float]
    ) -> Optional[tuple[int, int]]:
        """Project a single query to grid.

        Args:
            query_embedding: Single embedding vector

        Returns:
            Grid coordinates (x, y) or None
        """
        result = await self._client.call(
            "Compute",
            "project_query",
            {"embedding": query_embedding},
        )
        if result.get("success"):
            return (result["x"], result["y"])
        return None

    async def get_status(self) -> dict[str, Any]:
        """Get grid service status."""
        return await self._client.call("Compute", "grid_status", {})


# ─────────────────────────────────────────────────────────────────────────────
# Cognition Proxy
# ─────────────────────────────────────────────────────────────────────────────


class CognitionProxy:
    """Proxy for cognition service.

    Provides access to the engine's cognition daemon for:
    - Recent thoughts and activity
    - Cognition cycle status
    - Engine "signs of life"
    """

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client

    async def get_recent_thoughts(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent thoughts from cognition daemon.

        Args:
            limit: Maximum thoughts to return

        Returns:
            List of thought dicts with type, title, summary, salience, timestamp
        """
        result = await self._client.call(
            "Cognition", "recent_thoughts", {"limit": limit}
        )
        return result.get("thoughts", [])

    async def get_activity(self) -> dict[str, Any]:
        """Get cognition daemon activity summary.

        Returns comprehensive "signs of life" including:
        - Recent thoughts count and types
        - Cognition cycles completed
        - Current task if any
        - Last activity timestamp

        Returns:
            Activity summary dict
        """
        return await self._client.call("Cognition", "activity", {})

    async def get_status(self) -> dict[str, Any]:
        """Get cognition daemon status.

        Returns:
            Status dict with running state, cycles, etc.
        """
        return await self._client.call("Cognition", "status", {})

    async def trigger_cycle(
        self,
        max_thoughts: int = 5,
        trigger_reason: str = "manual",
    ) -> dict[str, Any]:
        """Manually trigger a cognition cycle.

        Args:
            max_thoughts: Maximum thoughts to generate
            trigger_reason: Why this was triggered

        Returns:
            Cycle result with thoughts generated
        """
        return await self._client.call(
            "Cognition",
            "trigger",
            {"max_thoughts": max_thoughts, "trigger_reason": trigger_reason},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Factory Functions
# ─────────────────────────────────────────────────────────────────────────────

_orchestrator_proxy: Optional[OrchestratorProxy] = None
_scheduler_proxy: Optional[SchedulerProxy] = None
_evolution_proxy: Optional[EvolutionProxy] = None
_health_proxy: Optional[HealthProxy] = None
_tda_proxy: Optional[TDAProxy] = None
_grid_proxy: Optional[GridProxy] = None
_cognition_proxy: Optional[CognitionProxy] = None


async def get_orchestrator_proxy() -> OrchestratorProxy:
    """Get or create orchestrator proxy singleton."""
    global _orchestrator_proxy
    if _orchestrator_proxy is None:
        client = await get_client()
        _orchestrator_proxy = OrchestratorProxy(client)
    return _orchestrator_proxy


async def get_scheduler_proxy() -> SchedulerProxy:
    """Get or create scheduler proxy singleton."""
    global _scheduler_proxy
    if _scheduler_proxy is None:
        client = await get_client()
        _scheduler_proxy = SchedulerProxy(client)
    return _scheduler_proxy


async def get_evolution_proxy() -> EvolutionProxy:
    """Get or create evolution proxy singleton."""
    global _evolution_proxy
    if _evolution_proxy is None:
        client = await get_client()
        _evolution_proxy = EvolutionProxy(client)
    return _evolution_proxy


async def get_health_proxy() -> HealthProxy:
    """Get or create health proxy singleton."""
    global _health_proxy
    if _health_proxy is None:
        client = await get_client()
        _health_proxy = HealthProxy(client)
    return _health_proxy


async def get_tda_proxy() -> TDAProxy:
    """Get or create TDA proxy singleton."""
    global _tda_proxy
    if _tda_proxy is None:
        client = await get_client()
        _tda_proxy = TDAProxy(client)
    return _tda_proxy


async def get_grid_proxy() -> GridProxy:
    """Get or create grid proxy singleton."""
    global _grid_proxy
    if _grid_proxy is None:
        client = await get_client()
        _grid_proxy = GridProxy(client)
    return _grid_proxy


async def get_cognition_proxy() -> CognitionProxy:
    """Get or create cognition proxy singleton."""
    global _cognition_proxy
    if _cognition_proxy is None:
        client = await get_client()
        _cognition_proxy = CognitionProxy(client)
    return _cognition_proxy


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility Layer
# ─────────────────────────────────────────────────────────────────────────────

def use_engine_proxy() -> bool:
    """Check if engine proxy should be used.

    Returns True if gRPC server is reachable or GAIUS_ENGINE=true.
    Uses gRPC on port 50051 as the only transport.
    """
    import os
    import socket

    if os.environ.get("GAIUS_ENGINE", "").lower() == "true":
        return True

    # Check if gRPC server is reachable
    host = os.environ.get("GAIUS_GRPC_HOST", "localhost")
    port = int(os.environ.get("GAIUS_GRPC_PORT", "50051"))

    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (socket.error, socket.timeout):
        return False
