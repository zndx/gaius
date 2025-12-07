"""Orchestrator service for GPU endpoint lifecycle management.

Wraps the GPUOrchestrator functionality and integrates with the
backend router for unified endpoint management.

BDD Alignment (swarm_evolution.feature):
- Start evolution daemon with '/evolve start' → clean start, endpoint management
- Evolution daemon monitors GPU idle state → health monitoring
- Orphaned vLLM processes should be cleaned up → cleanup_stale_processes
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ..backends import BackendRouter, ProcessStatus, VLLMController
from ..config import EngineConfig
from ..resources import ResourceManager

logger = logging.getLogger(__name__)


@dataclass
class EndpointStatus:
    """Status of an inference endpoint.

    Attributes:
        agent_alias: Agent this endpoint serves
        model: Model loaded
        port: Serving port
        gpu_ids: GPUs allocated
        status: Process status
        pid: Process ID if running
        started_at: When started
        requests_served: Number of requests handled
        startup_progress: Current startup progress (0-1)
        startup_message: Current startup status message
    """

    agent_alias: str
    model: str
    port: Optional[int]
    gpu_ids: list[int]
    status: str
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    requests_served: int = 0
    startup_progress: float = 0.0
    startup_message: str = ""


@dataclass
class CleanupResult:
    """Result of cleanup operation.

    Attributes:
        processes_found: Number of stale processes found
        processes_killed: Number killed
        pids_killed: List of PIDs that were killed
        cuda_cache_cleared: Whether CUDA cache was cleared
        errors: Any errors encountered
    """

    processes_found: int = 0
    processes_killed: int = 0
    pids_killed: list[int] = None
    cuda_cache_cleared: bool = False
    errors: list[str] = None

    def __post_init__(self):
        if self.pids_killed is None:
            self.pids_killed = []
        if self.errors is None:
            self.errors = []


class OrchestratorService:
    """GPU endpoint orchestration service.

    Manages vLLM endpoint lifecycle with clean start support,
    health monitoring, and resource coordination.

    BDD Scenarios Supported:
    - Start evolution daemon with '/evolve start' (clean_start)
    - Evolution daemon monitors GPU idle state (get_gpu_utilization)
    - Orphaned vLLM processes should be cleaned up (cleanup_stale_processes)
    """

    def __init__(
        self,
        config: EngineConfig,
        resource_manager: ResourceManager,
        backend_router: BackendRouter,
    ):
        """Initialize orchestrator service.

        Args:
            config: Engine configuration
            resource_manager: Resource manager for GPU tracking
            backend_router: Backend router for inference
        """
        self.config = config
        self.resource_manager = resource_manager
        self.backend_router = backend_router

        # Access vLLM controller through backend router
        self._vllm = backend_router.vllm

        # Health monitoring
        self._health_task: Optional[asyncio.Task] = None
        self._running = False
        self._health_interval = config.health_interval_ms / 1000

        # GPU utilization cache (updated by health checks)
        self._gpu_utilization: dict[int, float] = {}
        self._last_health_check: Optional[datetime] = None

        # Auto-restart configuration
        self._auto_restart_enabled = getattr(
            config.startup, "auto_restart_failed", True
        )
        self._max_restart_attempts = getattr(
            config.startup, "max_restart_attempts", 3
        )
        # Track restart attempts per endpoint
        self._restart_attempts: dict[str, int] = {}

        logger.info("OrchestratorService initialized")

    async def start(self) -> None:
        """Start the orchestrator service."""
        if self._running:
            return

        self._running = True

        # Start health monitoring loop
        self._health_task = asyncio.create_task(self._health_loop())

        logger.info("OrchestratorService started")

    async def stop(self) -> None:
        """Stop the orchestrator service."""
        if not self._running:
            return

        self._running = False

        # Cancel health task
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        logger.info("OrchestratorService stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Endpoint Management
    # ─────────────────────────────────────────────────────────────────────────

    async def start_endpoint(self, agent_alias: str) -> EndpointStatus:
        """Start an inference endpoint for an agent.

        Args:
            agent_alias: Agent identifier

        Returns:
            EndpointStatus with startup state
        """
        if agent_alias not in self.config.agents:
            raise ValueError(f"Unknown agent: {agent_alias}")

        agent_config = self.config.agents[agent_alias]

        # Only vLLM agents need endpoint startup
        if agent_config.backend.lower() != "vllm":
            return EndpointStatus(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=None,
                gpu_ids=[],
                status="optillm",  # Uses optillm, no dedicated endpoint
            )

        # Start vLLM endpoint
        proc = await self._vllm.start_endpoint(agent_alias, agent_config)

        return EndpointStatus(
            agent_alias=agent_alias,
            model=proc.model,
            port=proc.port,
            gpu_ids=proc.gpu_ids,
            status=proc.status.value,
            pid=proc.pid,
            started_at=proc.started_at,
        )

    async def stop_endpoint(self, agent_alias: str) -> bool:
        """Stop an inference endpoint.

        Args:
            agent_alias: Agent identifier

        Returns:
            True if stopped successfully
        """
        return await self._vllm.stop_endpoint(agent_alias)

    async def restart_endpoint(self, agent_alias: str) -> EndpointStatus:
        """Restart an inference endpoint.

        Args:
            agent_alias: Agent identifier

        Returns:
            EndpointStatus after restart
        """
        await self.stop_endpoint(agent_alias)
        await asyncio.sleep(2)  # Brief cooldown
        return await self.start_endpoint(agent_alias)

    def get_endpoint_status(self, agent_alias: str) -> Optional[EndpointStatus]:
        """Get status of a specific endpoint.

        Args:
            agent_alias: Agent identifier

        Returns:
            EndpointStatus if exists
        """
        proc = self._vllm.get_process(agent_alias)
        if not proc:
            return None

        # Get startup progress
        message, progress = self._vllm.get_startup_progress(agent_alias)

        return EndpointStatus(
            agent_alias=agent_alias,
            model=proc.model,
            port=proc.port,
            gpu_ids=proc.gpu_ids,
            status=proc.status.value,
            pid=proc.pid,
            started_at=proc.started_at,
            requests_served=proc.requests_served,
            startup_progress=progress,
            startup_message=message,
        )

    def get_all_endpoint_status(self) -> dict[str, EndpointStatus]:
        """Get status of all endpoints.

        Returns:
            Dict mapping agent alias to status
        """
        result = {}
        for alias in self._vllm._processes:
            status = self.get_endpoint_status(alias)
            if status:
                result[alias] = status
        return result

    def get_endpoint_logs(self, agent_alias: str, lines: int = 50) -> list[str]:
        """Get recent logs from an endpoint.

        Args:
            agent_alias: Agent identifier
            lines: Number of lines to return

        Returns:
            List of log lines
        """
        return self._vllm.get_recent_logs(agent_alias, lines)

    # ─────────────────────────────────────────────────────────────────────────
    # Clean Start (BDD: '/evolve start' scenario)
    # ─────────────────────────────────────────────────────────────────────────

    async def clean_start(
        self, endpoints: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Clean start: kill stale processes and start fresh.

        This is the recommended way to start Gaius for overnight evolution runs.

        BDD: "Start evolution daemon with '/evolve start'"
        - Orphaned vLLM processes should be cleaned up
        - The specified endpoint should start on designated GPU

        Args:
            endpoints: Endpoints to start (default: ["reasoning"])

        Returns:
            Dict with cleanup and startup results
        """
        logger.info("Performing clean start...")

        results = {
            "cleanup": None,
            "startup": {},
            "success": False,
        }

        # Step 1: Cleanup stale processes
        results["cleanup"] = await self.cleanup_stale_processes()

        # Step 2: Start requested endpoints
        if endpoints is None:
            endpoints = ["reasoning"]  # Default for evolution

        for alias in endpoints:
            if alias in self.config.agents:
                try:
                    status = await self.start_endpoint(alias)
                    results["startup"][alias] = {
                        "success": status.status == "healthy",
                        "port": status.port,
                        "gpu_ids": status.gpu_ids,
                    }
                except Exception as e:
                    logger.error(f"Failed to start {alias}: {e}")
                    results["startup"][alias] = {
                        "success": False,
                        "error": str(e),
                    }

        # Determine overall success
        results["success"] = any(
            r.get("success", False) for r in results["startup"].values()
        )

        return results

    async def cleanup_stale_processes(self) -> CleanupResult:
        """Kill stale vLLM processes to free GPU memory.

        BDD: "Orphaned vLLM processes should be cleaned up"

        Returns:
            CleanupResult with details
        """
        result = CleanupResult()

        try:
            # Find all vLLM processes
            ps_result = subprocess.run(
                ["pgrep", "-f", "vllm|VLLM"],
                capture_output=True,
                text=True,
            )

            if ps_result.returncode == 0 and ps_result.stdout.strip():
                pids = ps_result.stdout.strip().split("\n")
                result.processes_found = len(pids)

                # Get tracked PIDs
                tracked_pids = {
                    p.pid
                    for p in self._vllm._processes.values()
                    if p.process is not None and p.pid is not None
                }

                for pid_str in pids:
                    pid = int(pid_str.strip())

                    if pid not in tracked_pids:
                        try:
                            os.kill(pid, 9)  # SIGKILL
                            result.processes_killed += 1
                            result.pids_killed.append(pid)
                            logger.info(f"Killed stale vLLM process: {pid}")
                        except ProcessLookupError:
                            pass
                        except PermissionError:
                            result.errors.append(f"Permission denied for PID {pid}")

            # Clear CUDA cache if available
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    result.cuda_cache_cleared = True
                    logger.info("Cleared CUDA cache")
            except ImportError:
                pass

            # Brief wait for GPU memory to be freed
            await asyncio.sleep(2)

            logger.info(
                f"Cleanup complete: found {result.processes_found}, "
                f"killed {result.processes_killed}"
            )

        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"Cleanup error: {e}")

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # GPU Health Monitoring (BDD: GPU idle state monitoring)
    # ─────────────────────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        """Background health monitoring loop."""
        while self._running:
            try:
                await self._update_gpu_health()
                await self._check_endpoint_health()
            except Exception as e:
                logger.error(f"Health check error: {e}")

            await asyncio.sleep(self._health_interval)

    async def _update_gpu_health(self) -> None:
        """Update GPU utilization metrics."""
        try:
            import pynvml

            pynvml.nvmlInit()

            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                self._gpu_utilization[i] = util.gpu / 100.0

                # Update resource manager
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                self.resource_manager.update_gpu_status(
                    i,
                    vram_used_gb=memory.used / (1024**3),
                    temperature_c=temp,
                    utilization_pct=util.gpu,
                )

            pynvml.nvmlShutdown()
            self._last_health_check = datetime.now()

        except ImportError:
            # pynvml not available, skip GPU metrics
            pass
        except Exception as e:
            logger.debug(f"GPU health update failed: {e}")

    async def _check_endpoint_health(self) -> None:
        """Check health of all running endpoints and auto-restart if configured."""
        for alias, proc in list(self._vllm._processes.items()):
            if proc.status not in (ProcessStatus.HEALTHY, ProcessStatus.UNHEALTHY, ProcessStatus.FAILED):
                continue

            # Check if process is still running
            if proc.process and proc.process.returncode is not None:
                logger.warning(
                    f"Process for {alias} exited with code {proc.process.returncode}"
                )
                proc.status = ProcessStatus.FAILED
                # Attempt auto-restart if enabled
                await self._maybe_restart_endpoint(alias)
                continue

            # HTTP health check
            healthy = await self._vllm._check_health(proc)
            if healthy:
                proc.status = ProcessStatus.HEALTHY
                proc.consecutive_failures = 0
                # Reset restart attempts on successful health check
                self._restart_attempts[alias] = 0
            else:
                proc.consecutive_failures += 1
                if proc.consecutive_failures >= 3:
                    proc.status = ProcessStatus.UNHEALTHY
                    # Attempt auto-restart if enabled
                    await self._maybe_restart_endpoint(alias)

    async def _maybe_restart_endpoint(self, alias: str) -> None:
        """Attempt to restart a failed endpoint if auto-restart is enabled.

        Args:
            alias: Endpoint alias to restart
        """
        if not self._auto_restart_enabled:
            return

        # Check restart attempts
        attempts = self._restart_attempts.get(alias, 0)
        if attempts >= self._max_restart_attempts:
            logger.warning(
                f"Endpoint {alias} exceeded max restart attempts ({self._max_restart_attempts}), "
                "giving up. Manual intervention required."
            )
            return

        # Increment attempts before trying
        self._restart_attempts[alias] = attempts + 1

        logger.info(
            f"Auto-restarting endpoint {alias} (attempt {attempts + 1}/{self._max_restart_attempts})"
        )

        try:
            # Brief cooldown before restart
            await asyncio.sleep(5)

            # Restart the endpoint
            status = await self.restart_endpoint(alias)

            if status.status == "healthy":
                logger.info(f"Successfully restarted endpoint {alias}")
                self._restart_attempts[alias] = 0  # Reset on success
            else:
                logger.warning(
                    f"Restart of {alias} returned status: {status.status}"
                )

        except Exception as e:
            logger.error(f"Failed to restart endpoint {alias}: {e}")

    def get_gpu_utilization(self) -> dict[int, float]:
        """Get current GPU utilization.

        BDD: "Evolution daemon monitors GPU idle state"
        - GPU utilization drops below 20% → trigger evolution

        Returns:
            Dict mapping GPU ID to utilization (0-1)
        """
        return self._gpu_utilization.copy()

    def is_gpu_idle(self, threshold: float = 0.2) -> bool:
        """Check if GPUs are idle (for evolution triggering).

        Args:
            threshold: Utilization threshold (default 20%)

        Returns:
            True if average utilization below threshold
        """
        if not self._gpu_utilization:
            return True  # No data, assume idle

        avg_util = sum(self._gpu_utilization.values()) / len(self._gpu_utilization)
        return avg_util < threshold

    def get_idle_gpus(self, threshold: float = 0.2) -> list[int]:
        """Get list of idle GPU IDs.

        Args:
            threshold: Utilization threshold (default 20%)

        Returns:
            List of GPU IDs below threshold
        """
        return [
            gpu_id
            for gpu_id, util in self._gpu_utilization.items()
            if util < threshold
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get comprehensive orchestrator status.

        Returns:
            Status dict with endpoints, GPUs, and health
        """
        endpoints = {}
        for alias, proc in self._vllm._processes.items():
            message, progress = self._vllm.get_startup_progress(alias)
            endpoints[alias] = {
                "model": proc.model,
                "port": proc.port,
                "gpu_ids": proc.gpu_ids,
                "status": proc.status.value,
                "pid": proc.pid,
                "startup_progress": progress,
                "startup_message": message,
                "requests_served": proc.requests_served,
            }

        return {
            "running": self._running,
            "endpoints": endpoints,
            "total_running": sum(
                1
                for p in self._vllm._processes.values()
                if p.status == ProcessStatus.HEALTHY
            ),
            "gpu_utilization": self._gpu_utilization,
            "is_idle": self.is_gpu_idle(),
            "last_health_check": (
                self._last_health_check.isoformat()
                if self._last_health_check
                else None
            ),
            "resources": self.resource_manager.get_summary(),
        }
