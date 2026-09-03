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
from typing import Any, AsyncIterator, Callable, Optional

from .grpc_client import GrpcEngineClient, get_grpc_client
from gaius.core.budgets import REASONING_MAX_TOKENS

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

    async def ensure_endpoint(self, endpoint: str, timeout: float = 120.0) -> dict:
        """Ensure endpoint is running, starting if needed and resources available.

        This is the primary method for agent-first architecture. CLI and agents
        call this to ensure an endpoint is available before making requests.

        Args:
            endpoint: Endpoint/agent name
            timeout: Request timeout in seconds (default 120s for vLLM startup)

        Returns:
            Dict with:
                - healthy: bool - True if endpoint is ready
                - status: str - Endpoint status
                - port: int - Port if running
                - gpu_ids: list - Allocated GPUs
                - message: str - Error message if not healthy
        """
        result = await self._client.call(
            "Orchestrator", "ensure", {"endpoint": endpoint}, timeout=timeout
        )
        return result

    async def start_endpoint(self, endpoint: str, timeout: float = 120.0) -> bool:
        """Start a vLLM endpoint.

        Args:
            endpoint: Endpoint/agent name
            timeout: Request timeout in seconds (default 120s for vLLM startup)

        Returns:
            True if started successfully
        """
        result = await self._client.call(
            "Orchestrator", "start", {"endpoint": endpoint}, timeout=timeout
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
    Includes client-side wait for endpoints during engine initialization.
    """

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client
        self._endpoints_ready = False

    async def _wait_for_endpoints(self, timeout: float = 300.0) -> bool:
        """Wait for at least one inference endpoint to be ready.

        Called before inference requests to ensure engine has completed
        initialization (~240s for vLLM preload).

        Args:
            timeout: Maximum wait time in seconds (default 5 minutes)

        Returns:
            True if endpoints are ready, False if timeout
        """
        if self._endpoints_ready:
            return True

        import asyncio
        import logging
        logger = logging.getLogger(__name__)

        start = asyncio.get_event_loop().time()
        wait_time = 1.0

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout:
                logger.warning(f"Endpoint wait timeout after {elapsed:.0f}s")
                return False

            try:
                # Check orchestrator status for healthy endpoints
                status = await self._client.call("Orchestrator", "status", {})
                endpoints = status.get("endpoints", [])
                healthy = sum(1 for ep in endpoints if ep.get("status") == "healthy")

                if healthy > 0:
                    logger.info(f"Endpoints ready after {elapsed:.1f}s ({healthy} healthy)")
                    self._endpoints_ready = True
                    return True

                logger.debug(f"Waiting for endpoints... ({elapsed:.0f}s, {len(endpoints)} found, 0 healthy)")

            except Exception as e:
                logger.debug(f"Endpoint check failed: {e}")

            await asyncio.sleep(wait_time)
            wait_time = min(wait_time * 1.5, 10.0)  # Exponential backoff, cap at 10s

    async def complete(
        self,
        prompt: str,
        agent: str = "thinking",
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = REASONING_MAX_TOKENS,
        technique: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CompletionResult:
        """Complete a prompt.

        Args:
            prompt: User prompt
            agent: Agent to use
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            technique: Optional optillm technique
            timeout: gRPC timeout in seconds (default 120s for inference)

        Returns:
            CompletionResult
        """
        # Wall-clock safety net. The real timeout protection is the idle-timeout
        # in OptillmController that monitors vLLM metrics for forward progress.
        # A 24B model with cot_reflection can take 120-300s for complex prompts.
        inference_timeout = timeout or 600.0

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
            timeout=inference_timeout,
        )

        # gRPC CompleteResponse uses 'text' field, not 'content'
        return CompletionResult(
            content=result.get("text", result.get("content", "")),
            model=result.get("model", ""),
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("tokens_used", result.get("output_tokens", 0)),
            technique=result.get("technique"),
            backend=result.get("backend", "grpc_engine"),
            raw_response=result,
        )

    async def submit_job(
        self,
        prompt: str,
        *,
        agent: str = "thinking",
        system_prompt: Optional[str] = None,
        max_tokens: int = REASONING_MAX_TOKENS,
        temperature: float = 0.7,
        priority: str = "normal",
        wait: bool = True,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Submit a job to the ENGINE's scheduler queue (Engine-First).

        The queue lives in the engine (SchedulerService behind SubmitJob /
        GetJobResult). With wait=True, polls GetJobResult until the job
        completes, fails, or the timeout elapses.

        Returns:
            The GetJobResult record (keys: job_id, status, text, tokens_used,
            latency_ms, error) — or the SubmitJob response when wait=False.
        """
        submitted = await self._client.call(
            "Scheduler",
            "submit",
            {
                "prompt": prompt,
                "agent": agent,
                "system_prompt": system_prompt or "",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "priority": priority,
            },
        )
        job_id = submitted.get("job_id", "")
        if not wait or not job_id:
            return submitted

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            record = await self._client.call(
                "Scheduler", "get_result", {"job_id": job_id}
            )
            status = record.get("status", "")
            if status in ("completed", "failed", "not_found"):
                return record
            if loop.time() > deadline:
                record["status"] = "timeout"
                record.setdefault(
                    "error",
                    f"job {job_id} did not complete within {timeout:.0f}s",
                )
                return record
            await asyncio.sleep(poll_interval)

    async def evaluate(
        self,
        prompt: str,
        force_xai: bool = False,
    ) -> CompletionResult:
        """Evaluate through Engine/Complete.

        Engine-First: the XAI judge is the engine's external backend lane
        (agent="xai" routes to ExternalInferenceRouter inside the engine) —
        never a client-side SDK call.

        Args:
            prompt: Prompt to evaluate
            force_xai: Route to the XAI external lane (else local thinking)

        Returns:
            CompletionResult
        """
        result = await self._client.call(
            "Scheduler",
            "complete",
            {
                "prompt": prompt,
                "agent": "xai" if force_xai else "thinking",
                "max_tokens": REASONING_MAX_TOKENS,
                "temperature": 0.5,
            },
            timeout=180.0,
        )

        return CompletionResult(
            content=result.get("text", result.get("content", "")),
            model=result.get("model", ""),
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("tokens_used", result.get("output_tokens", 0)),
            raw_response=result,
        )

    async def run_swarm_stream(
        self,
        domain: str,
        context: str = "",
        roles: list[str] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        clt: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream swarm analysis with real-time progress updates.

        Uses gRPC SwarmStream which handles backend wait internally,
        streaming QUEUED/WAITING_FOR_BACKENDS status while endpoints
        initialize. This prevents client timeouts during the ~240s
        engine startup phase.

        Args:
            domain: Domain to analyze
            context: Additional context
            roles: Agent roles to include (default: all core roles)
            on_event: Optional callback for each event
            clt: Use CLT-enhanced swarm with interpretable features

        Yields:
            SwarmEvent dicts with:
                - type: Event type (QUEUED, WAITING_FOR_BACKENDS, STARTED,
                        AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED, COMPLETED)
                - timestamp_ms: Event timestamp
                - agent: Agent name (for AGENT_* events)
                - progress: 0.0-1.0 overall progress
                - message: Human-readable status message
                - data: JSON payload (results on COMPLETED, includes _clt if clt=True)
        """
        from .grpc_client import get_grpc_client

        client = await get_grpc_client()
        async for event in client.swarm_stream(domain, context, roles, clt=clt):
            if on_event:
                on_event(event)
            yield event

    async def run_swarm(
        self,
        domain: str,
        context: str = "",
        roles: list[str] | None = None,
        on_progress: Callable[[str, float], None] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], str]:
        """Run multi-agent swarm analysis via engine and persist to KB.

        All swarm invocations (CLI, TUI, MCP) go through this method,
        ensuring consistent KB persistence.

        Uses streaming internally to handle backend initialization gracefully,
        preventing timeouts during the ~240s engine startup phase.

        Args:
            domain: Domain to analyze
            context: Additional context
            roles: Agent roles to include (default: all core roles)
            on_progress: Optional callback (message, progress_0_to_1)

        Returns:
            Tuple of (results dict, saved KB path)
        """
        import json

        results: dict[str, dict[str, Any]] = {}
        saved_path = ""

        async for event in self.run_swarm_stream(domain, context, roles):
            event_type = event.get("type", "")

            # Call progress callback if provided
            if on_progress:
                on_progress(event.get("message", ""), event.get("progress", 0.0))

            # Collect agent results as they come in
            if event_type == "AGENT_COMPLETED":
                agent = event.get("agent", "")
                if agent and event.get("data"):
                    try:
                        results[agent] = json.loads(event["data"])
                    except json.JSONDecodeError:
                        pass

            # Final event contains all results
            elif event_type == "COMPLETED":
                if event.get("data"):
                    try:
                        final_data = json.loads(event["data"])
                        results = final_data.get("results", results)
                        saved_path = final_data.get("saved_path", "")
                    except json.JSONDecodeError:
                        pass

            elif event_type == "FAILED":
                # Return empty results on failure
                logger.error(f"Swarm failed: {event.get('message', 'unknown error')}")
                return {}, ""

        return results, saved_path

    async def run_swarm_clt(
        self,
        domain: str,
        context: str = "",
        roles: list[str] | None = None,
        on_progress: Callable[[str, float], None] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], str]:
        """Run CLT-enhanced swarm analysis via engine.

        Uses Cross-Layer Transcoders for interpretable agent collaboration.
        All CLT processing happens in the engine.

        Args:
            domain: Domain to analyze
            context: Additional context
            roles: Agent roles to include (default: all core roles)
            on_progress: Optional callback (message, progress_0_to_1)

        Returns:
            Tuple of (results dict with _clt data, saved KB path)
        """
        import json

        results: dict[str, dict[str, Any]] = {}
        saved_path = ""

        # Use streaming internally for graceful backend handling
        async for event in self.run_swarm_stream(domain, context, roles, clt=True):
            event_type = event.get("type", "")

            if on_progress:
                on_progress(event.get("message", ""), event.get("progress", 0.0))

            if event_type == "AGENT_COMPLETED":
                agent = event.get("agent", "")
                if agent and event.get("data"):
                    try:
                        results[agent] = json.loads(event["data"])
                    except json.JSONDecodeError:
                        pass

            elif event_type == "COMPLETED":
                if event.get("data"):
                    try:
                        final_data = json.loads(event["data"])
                        results = final_data.get("results", results)
                        saved_path = final_data.get("saved_path", "")
                        # Include CLT data
                        if "_clt" in final_data:
                            results["_clt"] = final_data["_clt"]
                    except json.JSONDecodeError:
                        pass

            elif event_type == "FAILED":
                logger.error(f"CLT swarm failed: {event.get('message', 'unknown error')}")
                return {}, ""

        return results, saved_path

    def _calculate_swarm_summary(self, results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Calculate summary statistics from swarm results."""
        total = len(results)
        completed = sum(1 for r in results.values() if r.get("status") == "completed")
        failed = total - completed
        # Engine returns input_tokens and output_tokens separately
        total_tokens = sum(
            r.get("input_tokens", 0) + r.get("output_tokens", 0)
            for r in results.values()
        )
        total_latency = sum(r.get("latency_ms", 0) for r in results.values())

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "total_tokens": total_tokens,
            "total_latency_ms": total_latency,
        }

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
        """Get inference metrics via SchedulerStatus (metrics_json field)."""
        import json as _json

        status = await self._client.call("Scheduler", "status", {})
        metrics_json = status.get("metrics_json")
        if metrics_json:
            try:
                return _json.loads(metrics_json)
            except (ValueError, TypeError):
                pass
        return status

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
# Workload Proxy
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WorkloadAllocation:
    """Result from workload resource allocation."""

    success: bool
    workload_id: str
    allocated_endpoints: dict[str, dict[str, Any]]
    evicted_endpoints: list[str]
    error: Optional[str] = None


class WorkloadProxy:
    """Proxy for workload management.

    Enables callers to request GPU resources for multi-step workloads
    (like /init) using Yunikorn-style priority scheduling.

    Usage:
        proxy = await get_workload_proxy()
        result = await proxy.begin_workload(
            workload_id="init-2024-12-11",
            workload_type="INIT",
            required_capabilities=["TEXT_EMBEDDING"],
            priority="CRITICAL",
            estimated_duration_s=300,
            estimated_memory_mb=2000,
        )
        if result.success:
            try:
                # Use allocated endpoints
                ...
            finally:
                await proxy.complete_workload(result.workload_id)
    """

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client

    async def begin_workload(
        self,
        workload_id: str,
        workload_type: str,
        required_capabilities: list[str],
        priority: str = "NORMAL",
        estimated_duration_s: int = 60,
        estimated_memory_mb: int = 0,
    ) -> WorkloadAllocation:
        """Request resources for a workload.

        The engine will evict lower-priority idle endpoints if needed
        to satisfy resource requirements.

        Args:
            workload_id: Unique workload identifier
            workload_type: INIT, SWARM, INFERENCE, or EMBEDDING
            required_capabilities: List of TaskType names needed
            priority: CRITICAL, HIGH, NORMAL, or LOW
            estimated_duration_s: Expected duration hint
            estimated_memory_mb: GPU memory needed

        Returns:
            WorkloadAllocation with allocated endpoints or error
        """
        result = await self._client.call(
            "Workload",
            "begin",
            {
                "workload_id": workload_id,
                "workload_type": workload_type,
                "required_capabilities": required_capabilities,
                "priority": priority,
                "estimated_duration_s": estimated_duration_s,
                "estimated_memory_mb": estimated_memory_mb,
            },
        )

        return WorkloadAllocation(
            success=result.get("success", False),
            workload_id=workload_id,
            allocated_endpoints=result.get("allocated_endpoints", {}),
            evicted_endpoints=result.get("evicted_endpoints", []),
            error=result.get("error"),
        )

    async def complete_workload(self, workload_id: str) -> None:
        """Mark workload complete and restore evicted endpoints.

        Args:
            workload_id: Workload to complete
        """
        await self._client.call(
            "Workload",
            "complete",
            {"workload_id": workload_id},
        )

    async def get_active_workloads(self) -> list[dict[str, Any]]:
        """Get currently active workloads.

        Returns:
            List of active workload dicts
        """
        result = await self._client.call("Workload", "active", {})
        return result.get("workloads", [])


# ─────────────────────────────────────────────────────────────────────────────
# Embedding Proxy
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class EmbeddingResult:
    """Result from embedding request."""

    embeddings: list[list[float]]
    model_used: str
    latency_ms: int
    texts_processed: int
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


class EmbeddingProxy:
    """Proxy for engine-managed embeddings.

    Routes embedding requests through the engine's resource management,
    ensuring GPU resources are properly allocated and coordinated.

    Usage:
        proxy = await get_embedding_proxy()
        result = await proxy.embed_texts(["hello", "world"])
        if result.success:
            embeddings = result.embeddings
    """

    def __init__(self, client: GrpcEngineClient):
        """Initialize proxy."""
        self._client = client

    async def embed_texts(
        self,
        texts: list[str],
        model: str = "",
        batch_size: int = 32,
    ) -> EmbeddingResult:
        """Generate embeddings for texts via engine.

        Args:
            texts: Texts to embed
            model: Optional model name (empty = default)
            batch_size: Processing batch size

        Returns:
            EmbeddingResult with embeddings or error
        """
        result = await self._client.call(
            "Embedding",
            "embed_texts",
            {
                "texts": texts,
                "model": model,
            },
        )

        return EmbeddingResult(
            embeddings=result.get("embeddings", []),
            model_used=result.get("model_used", model or "unknown"),
            latency_ms=result.get("latency_ms", 0),
            texts_processed=len(result.get("embeddings", [])),
            error=result.get("error"),
        )

    async def get_model_info(self) -> dict[str, Any]:
        """Get information about loaded embedding models.

        Returns:
            Dict with model info
        """
        return await self._client.call("Embedding", "model_info", {})


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
_workload_proxy: Optional[WorkloadProxy] = None
_embedding_proxy: Optional[EmbeddingProxy] = None


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


async def get_workload_proxy() -> WorkloadProxy:
    """Get or create workload proxy singleton."""
    global _workload_proxy
    if _workload_proxy is None:
        client = await get_client()
        _workload_proxy = WorkloadProxy(client)
    return _workload_proxy


async def get_embedding_proxy() -> EmbeddingProxy:
    """Get or create embedding proxy singleton."""
    global _embedding_proxy
    if _embedding_proxy is None:
        client = await get_client()
        _embedding_proxy = EmbeddingProxy(client)
    return _embedding_proxy


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility Layer
# ─────────────────────────────────────────────────────────────────────────────

def use_engine_proxy() -> bool:
    """Check if engine proxy should be used.

    Returns True if:
    1. GAIUS_ENGINE=true environment variable is set, OR
    2. The gRPC client singleton is already connected, OR
    3. A socket test to the gRPC server succeeds

    The check prioritizes the singleton state since the TUI establishes
    the gRPC connection during startup. This prevents false negatives
    in thread pool code (like /init) that runs after the TUI is connected.
    """
    import os
    import socket

    # Always use engine if explicitly configured
    if os.environ.get("GAIUS_ENGINE", "").lower() == "true":
        return True

    # Check if gRPC client singleton is already connected
    # This is the primary check - if TUI has connected, we should use it
    from .grpc_client import _grpc_client
    if _grpc_client is not None and _grpc_client.is_connected:
        return True

    # Fallback: try socket connection (for CLI or standalone use)
    host = os.environ.get("GAIUS_GRPC_HOST", "localhost")
    port = int(os.environ.get("GAIUS_GRPC_PORT", "50051"))

    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (socket.error, socket.timeout):
        return False


def begin_workload_sync(
    workload_id: str,
    workload_type: str = "INIT",
    required_capabilities: list[str] | None = None,
    priority: str = "CRITICAL",
    estimated_duration_s: int = 300,
    estimated_memory_mb: int = 2000,
) -> WorkloadAllocation:
    """Synchronous wrapper for begin_workload (for use in thread pools).

    NOTE: This function creates a fresh gRPC connection to avoid event loop
    conflicts when called from a thread pool (the main TUI may have a gRPC
    client in a different event loop).

    Requests GPU resources from the engine, potentially triggering
    preemption of lower-priority idle endpoints.

    Args:
        workload_id: Unique workload identifier
        workload_type: INIT, SWARM, INFERENCE, or EMBEDDING
        required_capabilities: List of TaskType names (default: TEXT_EMBEDDING)
        priority: CRITICAL, HIGH, NORMAL, or LOW
        estimated_duration_s: Expected duration hint
        estimated_memory_mb: GPU memory needed

    Returns:
        WorkloadAllocation with result
    """
    import asyncio

    if required_capabilities is None:
        required_capabilities = ["TEXT_EMBEDDING"]

    if not use_engine_proxy():
        return WorkloadAllocation(
            success=False,
            workload_id=workload_id,
            allocated_endpoints={},
            evicted_endpoints=[],
            error="Engine not available",
        )

    async def _begin():
        # Create a fresh client for this sync call to avoid event loop conflicts
        from .grpc_client import GrpcEngineClient, GrpcClientConfig

        # Use config from environment (GrpcClientConfig.from_env())
        client = GrpcEngineClient()
        await client.connect()

        try:
            proxy = WorkloadProxy(client)
            return await proxy.begin_workload(
                workload_id=workload_id,
                workload_type=workload_type,
                required_capabilities=required_capabilities,
                priority=priority,
                estimated_duration_s=estimated_duration_s,
                estimated_memory_mb=estimated_memory_mb,
            )
        finally:
            await client.close()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_begin())
    finally:
        loop.close()


def complete_workload_sync(workload_id: str) -> None:
    """Synchronous wrapper for complete_workload (for use in thread pools).

    Marks a workload complete and triggers restoration of evicted endpoints.

    NOTE: This function creates a fresh gRPC connection to avoid event loop
    conflicts when called from a thread pool.

    Args:
        workload_id: Workload to complete
    """
    import asyncio

    if not use_engine_proxy():
        return

    async def _complete():
        # Create a fresh client for this sync call to avoid event loop conflicts
        from .grpc_client import GrpcEngineClient

        # Use config from environment (GrpcClientConfig.from_env())
        client = GrpcEngineClient()
        await client.connect()

        try:
            proxy = WorkloadProxy(client)
            await proxy.complete_workload(workload_id)
        finally:
            await client.close()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_complete())
    finally:
        loop.close()


def embed_texts_sync(
    texts: list[str],
    model: str = "",
) -> list[list[float]]:
    """Synchronous wrapper for engine embeddings (for use in thread pools).

    Tries to use engine if available, otherwise falls back to in-process.
    This is intended for legacy code that runs in thread pools (like /init).

    Args:
        texts: Texts to embed
        model: Optional model name

    Returns:
        List of embedding vectors
    """
    import asyncio

    if not use_engine_proxy():
        # Engine not available, return empty to trigger fallback
        return []

    async def _embed():
        proxy = await get_embedding_proxy()
        result = await proxy.embed_texts(texts, model)
        if result.success:
            return result.embeddings
        return []

    # Run in a new event loop (safe from thread pool)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_embed())
    finally:
        loop.close()
