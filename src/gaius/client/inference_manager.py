"""Inference Manager - High-level service lifecycle for models and orchestrator.

Provides imperative control over the inference stack with progress tracking:
- Startup sequence with nvidia/Orchestrator-8B as default
- Health monitoring and status reporting
- Symmetric operations for TUI and CLI
- Scale-to-zero management (future)

Agent-First Architecture:
- Uses engine client when gaius-engine is running
- Falls back to legacy orchestrator for standalone mode

Usage (TUI):
    manager = get_inference_manager()
    await manager.ensure_orchestrator_running(progress_callback)

Usage (CLI):
    manager = get_inference_manager()
    status = await manager.get_status()
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Any

from ..engine.backends.vllm_controller import ProcessStatus

logger = logging.getLogger(__name__)


@dataclass
class InferenceStatus:
    """Status of the inference stack."""
    orchestrator_running: bool
    endpoints_running: dict[str, ProcessStatus]  # endpoint_name -> status
    scheduler_healthy: bool
    default_model_ready: bool  # nvidia/Orchestrator-8B
    total_requests: int = 0
    queue_depth: int = 0


class InferenceManager:
    """Manages inference service lifecycle with progress tracking.

    Responsible for:
    - Ensuring orchestrator and scheduler are running
    - Dynamic endpoint discovery
    - Progress reporting during startup
    - Health monitoring
    """

    def __init__(self):
        # NOTE: Legacy orchestrator mode is no longer supported.
        # All orchestration goes through the engine gRPC service.
        self._use_engine = False
        self._engine_proxy = None
        self._default_endpoint: str | None = None  # Discovered dynamically
        self._endpoint_cache_time: datetime | None = None

        # Engine Federation Architecture: all orchestration goes through engine gRPC
        try:
            from .engine_proxy import use_engine_proxy
            self._use_engine = use_engine_proxy()
            if self._use_engine:
                logger.info("InferenceManager using engine client (agent-first mode)")
            else:
                logger.warning(
                    "Engine not available (#GR.00000001.ENGINEOFF). "
                    "InferenceManager will be limited to external endpoints only. "
                    "Start engine: devenv up gaius-engine"
                )
        except ImportError:
            logger.warning(
                "Engine proxy not available. InferenceManager will be limited. "
                "GPU orchestration requires the engine gRPC service."
            )

    def _require_engine(self) -> None:
        """Fail-fast if engine is not available.

        Raises:
            RuntimeError: If engine is not running and legacy mode not supported
        """
        if not self._use_engine:
            raise RuntimeError(
                "Engine not available - GPU orchestration requires gaius-engine.\n"
                "  Start with: just restart-clean\n"
                "  Guru Meditation: #INF.00000001.NOENGINE"
            )

    async def _get_engine_proxy(self):
        """Get or create engine orchestrator proxy."""
        if self._engine_proxy is None:
            from .engine_proxy import get_orchestrator_proxy
            self._engine_proxy = await get_orchestrator_proxy()
        return self._engine_proxy

    def _discover_default_endpoint(self) -> str | None:
        """Discover the best available endpoint dynamically.

        Priority order:
        1. orchestrator (meta-cognitive routing)
        2. fast (quick responses)
        3. Any configured endpoint

        Returns:
            Endpoint name or None

        Raises:
            RuntimeError: If engine is not available
        """
        priority = ["orchestrator", "thinking"]

        if self._use_engine:
            # Engine mode - use priority order with known endpoints
            return priority[0]  # orchestrator is default in engine mode
        else:
            # Legacy mode is no longer supported
            self._require_engine()

    def get_default_endpoint(self) -> str | None:
        """Get the default endpoint, with caching.

        Returns:
            Endpoint name to use for inference
        """
        # Check cache validity (1 minute)
        if self._default_endpoint and self._endpoint_cache_time:
            age = (datetime.now() - self._endpoint_cache_time).total_seconds()
            if age < 60:
                return self._default_endpoint

        # Discover and cache
        self._default_endpoint = self._discover_default_endpoint()
        self._endpoint_cache_time = datetime.now()
        return self._default_endpoint

    def get_configured_endpoints(self) -> list[str]:
        """Get all configured endpoints.

        Returns:
            List of endpoint names from config

        Raises:
            RuntimeError: If engine is not available
        """
        if self._use_engine:
            # Engine mode - return standard endpoints
            return ["orchestrator", "thinking", "embedding", "reasoning"]
        self._require_engine()
        return []  # unreachable but satisfies type checker

    def get_running_endpoints(self) -> list[str]:
        """Get currently running endpoints.

        Returns:
            List of healthy endpoint names

        Raises:
            RuntimeError: If engine is not available
        """
        if self._use_engine:
            # Engine mode - need async call, return cached if available
            # For sync interface, return empty or use cached value
            return []  # Caller should use async get_status() instead
        self._require_engine()
        return []  # unreachable but satisfies type checker

    async def get_status(self) -> InferenceStatus:
        """Get current inference stack status.

        Returns:
            InferenceStatus with all endpoint states
        """
        import httpx

        endpoints_running = {}

        if self._use_engine:
            # Engine mode - get status from engine
            proxy = await self._get_engine_proxy()
            orch_status = await proxy._get_status_async()

            # gRPC returns endpoints as a list of dicts with 'name' key
            endpoints_info = orch_status.get("endpoints", [])
            if isinstance(endpoints_info, list):
                for ep in endpoints_info:
                    endpoint_name = ep.get("name", "")
                    status_str = ep.get("status", "stopped")
                    try:
                        endpoints_running[endpoint_name] = ProcessStatus[status_str.upper()]
                    except KeyError:
                        endpoints_running[endpoint_name] = ProcessStatus.STOPPED
            else:
                # Legacy dict format
                for endpoint_name, info in endpoints_info.items():
                    status_str = info.get("status", "stopped")
                    try:
                        endpoints_running[endpoint_name] = ProcessStatus[status_str.upper()]
                    except KeyError:
                        endpoints_running[endpoint_name] = ProcessStatus.STOPPED
        else:
            # Legacy mode is no longer supported
            self._require_engine()

        # Check if any usable endpoint is ready (check common ports for external processes)
        default_ready = any(
            status == ProcessStatus.HEALTHY
            for status in endpoints_running.values()
        )

        # Also check common inference ports that might have external processes
        # (e.g., from devenv, MCP server, or manual vLLM starts)
        if not default_ready:
            common_ports = [8080, 8081, 8082, 8083, 8084, 8085]
            async with httpx.AsyncClient() as client:
                for port in common_ports:
                    try:
                        r = await client.get(f"http://localhost:{port}/v1/models", timeout=2)
                        if r.status_code == 200:
                            default_ready = True
                            # Try to identify which endpoint this is
                            try:
                                data = r.json()
                                model_id = data.get("data", [{}])[0].get("id", "")
                                # Map model to endpoint name (simplified without legacy orchestrator)
                                for name in endpoints_running:
                                        endpoints_running[name] = ProcessStatus.HEALTHY
                                        break
                            except Exception:
                                pass
                            break
                    except Exception:
                        pass

        return InferenceStatus(
            orchestrator_running=True,  # If we got status, orchestrator is running
            endpoints_running=endpoints_running,
            scheduler_healthy=True,  # TODO: Query scheduler health
            default_model_ready=default_ready,
            total_requests=orch_status.get("total_requests", 0),
        )

    async def ensure_orchestrator_running(
        self,
        progress_callback: Callable[[str, float, str], None] | None = None
    ) -> bool:
        """Ensure default inference endpoint is running.

        This is the main startup sequence:
        1. Discover best available endpoint from config
        2. Check if already running
        3. If not, start it with progress updates
        4. Wait for healthy status

        Uses engine's ensure_endpoint in agent-first mode for proper resource management.

        Args:
            progress_callback: Optional callback(task_name, progress_0_1, message)

        Returns:
            True if successful, False otherwise
        """
        # Discover the default endpoint
        default_endpoint = self.get_default_endpoint()
        if not default_endpoint:
            logger.error("No endpoints configured")
            return False

        task_name = f"Starting {default_endpoint}"

        def report(progress: float, message: str):
            if progress_callback:
                progress_callback(task_name, progress, message)
            logger.info(f"{task_name}: {message} ({progress:.0%})")

        try:
            report(0.0, "Checking endpoint status")

            # Check if already running
            status = await self.get_status()
            if status.default_model_ready:
                report(1.0, "Already running")
                return True

            report(0.2, f"Starting {default_endpoint} endpoint")

            if self._use_engine:
                # Engine mode - use ensure_endpoint for proper resource management
                proxy = await self._get_engine_proxy()
                try:
                    result = await proxy.ensure_endpoint(default_endpoint)
                except TimeoutError:
                    # #EP.00000002.ENSURETIMEOUT - Endpoint ensure operation timed out
                    error_msg = (
                        f"Endpoint startup timed out for {default_endpoint}.\n"
                        "  The vLLM model is still loading. Try:\n"
                        "  1. Wait 30-60 seconds and retry\n"
                        "  2. Check endpoint status: /gpu status\n"
                        "  3. View logs: /health diagnose inference"
                    )
                    logger.warning(f"#EP.00000002.ENSURETIMEOUT: {error_msg}")
                    report(0.0, f"Timeout - model still loading")
                    return False

                if result.get("healthy"):
                    report(1.0, "Ready")
                    return True
                else:
                    error_msg = result.get("message", result.get("status", "Failed"))
                    report(0.0, f"Failed: {error_msg}")
                    return False

            # Legacy mode is no longer supported
            self._require_engine()
            return False  # unreachable but satisfies type checker

        except Exception as e:
            report(0.0, f"Error: {e}")
            logger.exception(f"Failed to start {default_endpoint} endpoint")
            return False

    async def start_endpoint(
        self,
        endpoint_name: str,
        progress_callback: Callable[[str, float, str], None] | None = None
    ) -> bool:
        """Start a specific endpoint.

        Uses engine's ensure_endpoint in agent-first mode for proper resource management.

        Args:
            endpoint_name: Name of endpoint (e.g., "reasoning", "coding")
            progress_callback: Optional progress callback

        Returns:
            True if successful

        Note:
            Model is defined in the endpoint configuration, not passed here.
        """
        task_name = f"Starting {endpoint_name}"

        def report(progress: float, message: str):
            if progress_callback:
                progress_callback(task_name, progress, message)
            logger.info(f"{task_name}: {message}")

        try:
            report(0.2, "Starting endpoint")

            if self._use_engine:
                # Engine mode - use ensure_endpoint
                proxy = await self._get_engine_proxy()
                try:
                    result = await proxy.ensure_endpoint(endpoint_name)
                    success = result.get("healthy", False)
                except TimeoutError:
                    # #EP.00000002.ENSURETIMEOUT - Endpoint ensure operation timed out
                    logger.warning(
                        f"#EP.00000002.ENSURETIMEOUT: Endpoint {endpoint_name} startup timed out. "
                        "Model may still be loading."
                    )
                    report(0.0, "Timeout - model still loading")
                    return False

                if result.get("healthy"):
                    report(1.0, "Started")
                    return True
                else:
                    report(0.0, "Failed to start")
                    return False
            else:
                # Legacy mode is no longer supported
                self._require_engine()
                return False  # unreachable

        except Exception as e:
            report(0.0, f"Error: {e}")
            return False

    async def stop_endpoint(self, endpoint_name: str) -> bool:
        """Stop a specific endpoint."""
        try:
            if self._use_engine:
                proxy = await self._get_engine_proxy()
                return await proxy.stop_endpoint(endpoint_name)
            # Legacy mode is no longer supported
            self._require_engine()
            return False  # unreachable
        except Exception as e:
            logger.error(f"Failed to stop {endpoint_name}: {e}")
            return False

    async def restart_endpoint(
        self,
        endpoint_name: str,
        progress_callback: Callable[[str, float, str], None] | None = None
    ) -> bool:
        """Restart a specific endpoint."""
        await self.stop_endpoint(endpoint_name)
        await asyncio.sleep(2)  # Give it time to stop
        return await self.start_endpoint(endpoint_name, progress_callback=progress_callback)


# Module-level singleton
_manager: InferenceManager | None = None


def get_inference_manager() -> InferenceManager:
    """Get or create inference manager singleton."""
    global _manager
    if _manager is None:
        _manager = InferenceManager()
    return _manager
