"""Inference Manager - High-level service lifecycle for models and orchestrator.

Provides imperative control over the inference stack with progress tracking:
- Startup sequence with nvidia/Orchestrator-8B as default
- Health monitoring and status reporting
- Symmetric operations for TUI and CLI
- Scale-to-zero management (future)

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

from .orchestrator import get_orchestrator, ProcessStatus

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
    - Starting default models (nvidia/Orchestrator-8B)
    - Progress reporting during startup
    - Health monitoring
    """

    def __init__(self):
        self._orchestrator = get_orchestrator()
        self._default_endpoint = "orchestration"  # nvidia/Orchestrator-8B
        self._default_model = "nvidia/Orchestrator-8B"

    async def get_status(self) -> InferenceStatus:
        """Get current inference stack status.

        Returns:
            InferenceStatus with all endpoint states
        """
        import httpx

        orch_status = self._orchestrator.get_status()

        endpoints_running = {}
        for endpoint_name, process in orch_status.get("processes", {}).items():
            endpoints_running[endpoint_name] = ProcessStatus[process["status"].upper()]

        # Check if default model (fast/Mistral-7B) is ready
        # First check tracked processes, then do HTTP check for external processes
        default_ready = False
        if self._default_endpoint in endpoints_running:
            default_ready = endpoints_running[self._default_endpoint] == ProcessStatus.HEALTHY

        # Also check via HTTP (catches external processes like MCP-started ones)
        if not default_ready:
            try:
                # Get the endpoint URL from config (fast=8080, reasoning=8081)
                endpoint_cfg = orch_status.get("endpoints", {}).get(self._default_endpoint, {})
                endpoint_url = endpoint_cfg.get("url", "http://localhost:8080/v1")
                base_url = endpoint_url.rstrip("/v1")

                async with httpx.AsyncClient() as client:
                    r = await client.get(f"{base_url}/v1/models", timeout=3)
                    if r.status_code == 200:
                        default_ready = True
                        # Update endpoints_running to reflect this
                        endpoints_running[self._default_endpoint] = ProcessStatus.HEALTHY
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
        """Ensure orchestrator and default model are running.

        This is the main startup sequence:
        1. Check if nvidia/Orchestrator-8B is already running
        2. If not, start it with progress updates
        3. Wait for healthy status

        Args:
            progress_callback: Optional callback(task_name, progress_0_1, message)

        Returns:
            True if successful, False otherwise
        """
        task_name = "Starting nvidia/Orchestrator-8B"

        def report(progress: float, message: str):
            if progress_callback:
                progress_callback(task_name, progress, message)
            logger.info(f"{task_name}: {message} ({progress:.0%})")

        try:
            report(0.0, "Checking orchestrator status")

            # Check if already running
            status = await self.get_status()
            if status.default_model_ready:
                report(1.0, "Already running")
                return True

            report(0.2, "Starting orchestrator endpoint")

            # Start the orchestration endpoint (model defined in endpoint config)
            success = await self._orchestrator.start_endpoint(self._default_endpoint)

            if not success:
                # Check if it's a binary not found issue
                proc = self._orchestrator.get_endpoint_status(self._default_endpoint)
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
                    self._default_endpoint
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
                    endpoint_status = status.endpoints_running.get(self._default_endpoint)
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
            logger.exception("Failed to start fast endpoint")
            return False

    async def start_endpoint(
        self,
        endpoint_name: str,
        progress_callback: Callable[[str, float, str], None] | None = None
    ) -> bool:
        """Start a specific endpoint.

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
            result = await self._orchestrator.stop_endpoint(endpoint_name)
            return result.get("success", False)
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
