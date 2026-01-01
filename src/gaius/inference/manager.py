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
        self._orchestrator = None  # Lazily initialized
        self._use_engine = False
        self._engine_proxy = None
        self._default_endpoint: str | None = None  # Discovered dynamically
        self._endpoint_cache_time: datetime | None = None

        # Engine Federation Architecture: all orchestration goes through engine gRPC
        try:
            from ..client.engine_proxy import use_engine_proxy
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

    async def _get_engine_proxy(self):
        """Get or create engine orchestrator proxy."""
        if self._engine_proxy is None:
            from ..client.engine_proxy import get_orchestrator_proxy
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
        """
        priority = ["orchestrator", "fast", "coding"]

        if self._use_engine:
            # Engine mode - use priority order with known endpoints
            return priority[0]  # orchestrator is default in engine mode
        else:
            # Legacy mode
            default = self._orchestrator.get_default_endpoint()
            if default:
                return default

            configured = self._orchestrator.get_configured_endpoints()

            for name in priority:
                if name in configured:
                    return name

            return configured[0] if configured else None

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
        """
        if self._use_engine:
            # Engine mode - return standard endpoints
            return ["orchestrator", "fast", "embedding", "coding", "reasoning"]
        return self._orchestrator.get_configured_endpoints()

    def get_running_endpoints(self) -> list[str]:
        """Get currently running endpoints.

        Returns:
            List of healthy endpoint names
        """
        if self._use_engine:
            # Engine mode - need async call, return cached if available
            # For sync interface, return empty or use cached value
            return []  # Caller should use async get_status() instead
        return self._orchestrator.get_running_endpoints()

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
            # Legacy mode
            orch_status = self._orchestrator.get_status()

            endpoints_info = orch_status.get("endpoints", {})
            for endpoint_name, info in endpoints_info.items():
                status_str = info.get("status", "stopped")
                try:
                    endpoints_running[endpoint_name] = ProcessStatus[status_str.upper()]
                except KeyError:
                    endpoints_running[endpoint_name] = ProcessStatus.STOPPED

            # Probe all configured endpoints via HTTP to detect external processes
            async with httpx.AsyncClient() as client:
                for endpoint_name in endpoints_running:
                    if endpoints_running[endpoint_name] == ProcessStatus.HEALTHY:
                        continue  # Already known healthy
                    endpoint_cfg = self._orchestrator.get_endpoint_config(endpoint_name)
                    if endpoint_cfg:
                        base_url = endpoint_cfg.url.rstrip("/v1")
                        try:
                            r = await client.get(f"{base_url}/v1/models", timeout=2)
                            if r.status_code == 200:
                                endpoints_running[endpoint_name] = ProcessStatus.HEALTHY
                        except Exception:
                            pass

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
                                # Map model to endpoint name
                                for name, cfg in [(n, self._orchestrator.get_endpoint_config(n))
                                                  for n in endpoints_running]:
                                    if cfg and model_id in cfg.models:
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

            # Legacy mode
            success = await self._orchestrator.start_endpoint(default_endpoint)

            if not success:
                proc = self._orchestrator.get_endpoint_status(default_endpoint)
                if proc and proc.status == ProcessStatus.FAILED:
                    report(0.0, "vLLM binary not found - install with: pip install vllm")
                else:
                    report(0.0, "Failed to start endpoint")
                return False

            report(0.4, "Waiting for model to load")

            # Poll until healthy (with timeout)
            timeout = 120  # 2 minutes
            start_time = datetime.now()

            while (datetime.now() - start_time).total_seconds() < timeout:
                status = await self.get_status()

                if status.default_model_ready:
                    report(1.0, "Ready")
                    return True

                # Get detailed progress from vLLM output parsing
                vllm_message, vllm_progress = self._orchestrator.get_startup_progress(
                    default_endpoint
                )

                # Check for errors
                if vllm_progress < 0:
                    report(0.0, f"Error: {vllm_message}")
                    return False

                # Use vLLM-parsed progress if meaningful, otherwise fall back to time-based
                elapsed = (datetime.now() - start_time).total_seconds()
                time_progress = 0.4 + (elapsed / timeout) * 0.5  # 0.4 -> 0.9

                # Combine: vLLM progress scaled to 0.4-0.95 range
                if vllm_progress > 0.01:
                    progress = 0.4 + vllm_progress * 0.55
                    message = vllm_message
                else:
                    progress = time_progress
                    endpoint_status = status.endpoints_running.get(default_endpoint)
                    if endpoint_status == ProcessStatus.STARTING:
                        message = "Loading model into VRAM"
                    elif endpoint_status == ProcessStatus.UNHEALTHY:
                        message = "Model loaded, warming up"
                    else:
                        message = f"Status: {endpoint_status.value if endpoint_status else 'starting'}"

                report(progress, message)
                await asyncio.sleep(2)

            report(0.0, f"Timeout after {timeout}s")
            return False

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
            else:
                # Legacy mode
                success = await self._orchestrator.start_endpoint(endpoint_name)

            if success:
                report(1.0, "Started")
                return True
            else:
                report(0.0, "Failed to start")
                return False

        except Exception as e:
            report(0.0, f"Error: {e}")
            return False

    async def stop_endpoint(self, endpoint_name: str) -> bool:
        """Stop a specific endpoint."""
        try:
            if self._use_engine:
                proxy = await self._get_engine_proxy()
                return await proxy.stop_endpoint(endpoint_name)
            return await self._orchestrator.stop_endpoint(endpoint_name)
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
