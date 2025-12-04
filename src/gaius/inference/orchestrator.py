"""GPU Orchestrator - vLLM subprocess lifecycle management.

Manages vLLM instances across GPU endpoints with:
- On-demand model loading
- Subprocess lifecycle management
- Health monitoring integration
- Auto-recovery support

Usage:
    from gaius.inference.orchestrator import get_orchestrator

    orch = get_orchestrator()
    await orch.start_endpoint("reasoning")
    status = orch.get_status()
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from collections import deque
import asyncio
import logging
import os
import re

logger = logging.getLogger(__name__)


class ProcessStatus(Enum):
    """vLLM process status."""
    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    FAILED = "failed"


# vLLM startup progress patterns - ordered by typical appearance sequence
# Each tuple: (regex pattern, human-readable status message, progress weight 0-1)
VLLM_PROGRESS_PATTERNS: list[tuple[str, str, float]] = [
    (r"Initializing .* engine", "Initializing engine", 0.05),
    (r"Starting engine", "Starting engine", 0.05),
    (r"Loading model weights", "Loading model weights", 0.10),
    (r"Loading checkpoint shards.*?(\d+)%", "Loading checkpoint: {0}%", 0.15),
    (r"Loading checkpoint shards", "Loading checkpoint shards", 0.15),
    (r"loading weights.*safetensors", "Loading safetensors", 0.20),
    (r"Loading model.*VRAM", "Loading into VRAM", 0.25),
    (r"Model.*loaded", "Model loaded", 0.50),
    (r"CUDA graphs", "Building CUDA graphs", 0.60),
    (r"CUDAGraph.*captured", "CUDA graphs captured", 0.70),
    (r"Warming up model", "Warming up model", 0.75),
    (r"Starting.*server", "Starting API server", 0.85),
    (r"Uvicorn running", "Server running", 0.95),
    (r"Application startup complete", "Startup complete", 0.98),
    # Error patterns (negative progress indicates error)
    (r"OutOfMemoryError|OOM", "Out of memory error", -1.0),
    (r"CUDA error", "CUDA error", -1.0),
    (r"Free memory.*less than", "Insufficient GPU memory", -1.0),
]


@dataclass
class EndpointConfig:
    """Configuration for a GPU endpoint."""
    name: str
    url: str
    models: list[str] = field(default_factory=list)
    gpus: list[int] = field(default_factory=list)
    tensor_parallel: int = 1


@dataclass
class VLLMProcess:
    """State of a running vLLM instance."""
    endpoint_name: str
    model: str
    port: int
    gpus: list[int]
    tensor_parallel: int = 1

    # Process state
    process: asyncio.subprocess.Process | None = None
    pid: int | None = None
    status: ProcessStatus = ProcessStatus.STOPPED
    started_at: datetime | None = None
    last_health_check: datetime | None = None
    consecutive_failures: int = 0
    recovery_attempts: int = 0

    # Log buffer (circular)
    stdout_buffer: deque = field(default_factory=lambda: deque(maxlen=500))
    stderr_buffer: deque = field(default_factory=lambda: deque(maxlen=500))

    # Performance metrics
    requests_served: int = 0


class GPUOrchestrator:
    """Manages vLLM subprocess lifecycle across GPU endpoints.

    Features:
    - On-demand model loading (starts vLLM when jobs need it)
    - CUDA_VISIBLE_DEVICES isolation for GPU assignment
    - Background health monitoring
    - Graceful shutdown with drain support
    """

    def __init__(self):
        self._processes: dict[str, VLLMProcess] = {}
        self._endpoints_config: dict[str, EndpointConfig] = {}
        self._lock = asyncio.Lock()
        self._health_task: asyncio.Task | None = None
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Load configuration
        self._load_config()

    def _load_config(self) -> None:
        """Load endpoint configuration from HOCON."""
        try:
            from ..core.config import get_config

            config = get_config()
            inference = config._raw.get("gaius", {}).get("inference", {})
            endpoints_raw = inference.get("endpoints", {})
            orchestrator_cfg = inference.get("orchestrator", {})

            # Load orchestrator settings
            self._vllm_binary = orchestrator_cfg.get("vllm", {}).get("binary", "vllm")
            self._gpu_memory_util = orchestrator_cfg.get("vllm", {}).get(
                "gpu_memory_utilization", 0.9
            )
            self._health_interval = orchestrator_cfg.get("health_check_interval", 15)
            self._startup_timeout = orchestrator_cfg.get("startup_timeout", 120)
            self._max_failures = orchestrator_cfg.get("max_consecutive_failures", 3)
            self._max_recovery = orchestrator_cfg.get("max_recovery_attempts", 3)

            # Load endpoint configs
            for name, ep in endpoints_raw.items():
                if isinstance(ep, dict):
                    self._endpoints_config[name] = EndpointConfig(
                        name=name,
                        url=ep.get("url", ""),
                        models=ep.get("models", []),
                        gpus=ep.get("gpus", []),
                        tensor_parallel=ep.get("tensor_parallel", 1),
                    )

            logger.info(f"Loaded {len(self._endpoints_config)} endpoint configs")

        except Exception as e:
            logger.warning(f"Failed to load orchestrator config: {e}")
            # Create default endpoint
            self._endpoints_config["default"] = EndpointConfig(
                name="default",
                url="http://localhost:8088/v1",
                gpus=[0],
            )
            self._vllm_binary = "vllm"
            self._gpu_memory_util = 0.9
            self._health_interval = 15
            self._startup_timeout = 120
            self._max_failures = 3
            self._max_recovery = 3

    def _extract_port(self, url: str) -> int:
        """Extract port from URL."""
        match = re.search(r":(\d+)", url)
        if match:
            return int(match.group(1))
        return 8000

    def get_startup_progress(self, endpoint: str) -> tuple[str, float]:
        """Get startup progress from vLLM output buffers.

        Parses stdout/stderr buffers for meaningful progress indicators.

        Args:
            endpoint: Endpoint name

        Returns:
            Tuple of (status_message, progress_0_to_1)
            Progress of -1.0 indicates an error condition.
        """
        proc = self._processes.get(endpoint)
        if not proc:
            return ("Not started", 0.0)

        # Combine buffers and check recent lines (last 50)
        all_output = list(proc.stdout_buffer)[-50:] + list(proc.stderr_buffer)[-50:]

        best_progress = 0.0
        best_message = "Starting"

        for line in all_output:
            for pattern, message_template, progress in VLLM_PROGRESS_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    # Handle templates with captured groups
                    if "{0}" in message_template and match.groups():
                        message = message_template.format(*match.groups())
                    else:
                        message = message_template

                    # Error conditions
                    if progress < 0:
                        return (message, progress)

                    # Track highest progress
                    if progress > best_progress:
                        best_progress = progress
                        best_message = message

        return (best_message, best_progress)

    def get_recent_output(self, endpoint: str, lines: int = 20) -> list[str]:
        """Get recent output from endpoint.

        Args:
            endpoint: Endpoint name
            lines: Number of lines to return

        Returns:
            List of recent output lines (combined stdout/stderr)
        """
        proc = self._processes.get(endpoint)
        if not proc:
            return []

        combined = list(proc.stdout_buffer) + list(proc.stderr_buffer)
        return combined[-lines:] if combined else []

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle Management
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the orchestrator (not endpoints - they start on-demand)."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()

        # Start health monitoring loop
        self._health_task = asyncio.create_task(self._health_loop())

        logger.info("GPU Orchestrator started (on-demand mode)")

    async def stop(self) -> None:
        """Stop the orchestrator and all managed endpoints."""
        if not self._running:
            return

        logger.info("Stopping GPU Orchestrator...")
        self._running = False
        self._shutdown_event.set()

        # Cancel health task
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Stop all endpoints
        await self.stop_all()

        logger.info("GPU Orchestrator stopped")

    async def _check_port_in_use(self, url: str) -> bool:
        """Check if an endpoint is already responding at the given URL.

        This detects existing vLLM processes (e.g., from previous sessions or MCP).

        Args:
            url: Base URL to check (e.g., "http://localhost:8084/v1")

        Returns:
            True if endpoint is responding
        """
        import httpx

        base_url = url.rstrip("/v1")
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{base_url}/v1/models", timeout=3)
                return r.status_code == 200
        except Exception:
            return False

    async def start_endpoint(self, endpoint: str) -> bool:
        """Start a vLLM instance for the specified endpoint.

        Args:
            endpoint: Endpoint name from config

        Returns:
            True if started successfully
        """
        async with self._lock:
            if endpoint not in self._endpoints_config:
                raise ValueError(f"Unknown endpoint: {endpoint}")

            config = self._endpoints_config[endpoint]
            if not config.models:
                logger.warning(f"Endpoint {endpoint} has no configured models")
                return False

            # Check if endpoint is already responding (from previous session or MCP)
            if await self._check_port_in_use(config.url):
                logger.info(
                    f"Endpoint {endpoint} already responding at {config.url}, "
                    f"assuming healthy"
                )
                # Create process state to track it (without subprocess handle)
                proc = VLLMProcess(
                    endpoint_name=endpoint,
                    model=config.models[0],
                    port=self._extract_port(config.url),
                    gpus=config.gpus,
                    tensor_parallel=config.tensor_parallel,
                    status=ProcessStatus.HEALTHY,
                )
                self._processes[endpoint] = proc
                return True

            # Check if already running
            proc = self._processes.get(endpoint)
            if proc and proc.status in (ProcessStatus.HEALTHY, ProcessStatus.STARTING):
                logger.info(f"Endpoint {endpoint} already running")
                return True

            # Create process state
            proc = VLLMProcess(
                endpoint_name=endpoint,
                model=config.models[0],
                port=self._extract_port(config.url),
                gpus=config.gpus,
                tensor_parallel=config.tensor_parallel,
                status=ProcessStatus.STARTING,
            )
            self._processes[endpoint] = proc

        # Start outside lock to avoid blocking
        return await self._start_vllm_process(endpoint)

    async def _start_vllm_process(self, endpoint: str) -> bool:
        """Actually start the vLLM subprocess."""
        proc = self._processes[endpoint]
        config = self._endpoints_config[endpoint]

        # Build CUDA_VISIBLE_DEVICES
        gpu_str = ",".join(str(g) for g in proc.gpus)
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu_str

        # Build vLLM command
        cmd = [
            self._vllm_binary, "serve", proc.model,
            "--port", str(proc.port),
            "--gpu-memory-utilization", str(self._gpu_memory_util),
        ]

        # Add tensor parallelism if needed
        if proc.tensor_parallel > 1:
            cmd.extend(["--tensor-parallel-size", str(proc.tensor_parallel)])

        logger.info(
            f"Starting vLLM for {endpoint}: CUDA_VISIBLE_DEVICES={gpu_str} "
            f"{' '.join(cmd)}"
        )

        try:
            # Start subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            proc.process = process
            proc.pid = process.pid
            proc.started_at = datetime.now()

            # Start output readers
            asyncio.create_task(self._read_stdout(endpoint))
            asyncio.create_task(self._read_stderr(endpoint))

            # Wait for healthy
            healthy = await self._wait_for_healthy(endpoint, self._startup_timeout)

            if healthy:
                proc.status = ProcessStatus.HEALTHY
                proc.consecutive_failures = 0
                logger.info(f"Endpoint {endpoint} is healthy (PID: {proc.pid})")
                return True
            else:
                proc.status = ProcessStatus.FAILED
                logger.error(f"Endpoint {endpoint} failed to become healthy")
                return False

        except FileNotFoundError as e:
            error_msg = f"vLLM binary not found: {self._vllm_binary}"
            logger.error(f"Failed to start vLLM for {endpoint}: {error_msg}")
            logger.error("Install vLLM with: pip install vllm")
            logger.error("Or set GAIUS_VLLM_BINARY env var to vLLM path")
            proc.status = ProcessStatus.FAILED
            proc.recovery_attempts = 999  # Don't retry if binary missing
            return False
        except Exception as e:
            logger.error(f"Failed to start vLLM for {endpoint}: {e}")
            proc.status = ProcessStatus.FAILED
            return False

    async def _read_stdout(self, endpoint: str) -> None:
        """Read stdout from vLLM process."""
        proc = self._processes.get(endpoint)
        if not proc or not proc.process or not proc.process.stdout:
            return

        try:
            while True:
                line = await proc.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                proc.stdout_buffer.append(decoded)
                if "error" in decoded.lower():
                    logger.warning(f"[{endpoint}] {decoded}")
        except Exception:
            pass

    async def _read_stderr(self, endpoint: str) -> None:
        """Read stderr from vLLM process."""
        proc = self._processes.get(endpoint)
        if not proc or not proc.process or not proc.process.stderr:
            return

        try:
            while True:
                line = await proc.process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                proc.stderr_buffer.append(decoded)
                # Log errors
                if "error" in decoded.lower() or "exception" in decoded.lower():
                    logger.warning(f"[{endpoint}] {decoded}")
        except Exception:
            pass

    async def _wait_for_healthy(self, endpoint: str, timeout: float) -> bool:
        """Wait for endpoint to become healthy."""
        import httpx

        proc = self._processes.get(endpoint)
        if not proc:
            return False

        config = self._endpoints_config[endpoint]
        base_url = config.url.rstrip("/v1")

        start = datetime.now()
        while (datetime.now() - start).total_seconds() < timeout:
            # Check if process crashed
            if proc.process and proc.process.returncode is not None:
                logger.error(
                    f"vLLM process for {endpoint} exited with code "
                    f"{proc.process.returncode}"
                )
                return False

            # Try HTTP health check
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(f"{base_url}/v1/models", timeout=5)
                    if r.status_code == 200:
                        return True
            except Exception:
                pass

            await asyncio.sleep(2)

        return False

    async def stop_endpoint(self, endpoint: str, timeout: float = 30.0) -> bool:
        """Gracefully stop a vLLM instance.

        Args:
            endpoint: Endpoint name
            timeout: Max seconds to wait for graceful shutdown

        Returns:
            True if stopped successfully
        """
        async with self._lock:
            proc = self._processes.get(endpoint)
            if not proc or not proc.process:
                return True

            proc.status = ProcessStatus.STOPPING
            logger.info(f"Stopping endpoint {endpoint} (PID: {proc.pid})")

        # Send SIGTERM
        proc.process.terminate()

        try:
            await asyncio.wait_for(proc.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Force kill
            logger.warning(f"Force killing endpoint {endpoint}")
            proc.process.kill()
            await proc.process.wait()

        async with self._lock:
            proc.status = ProcessStatus.STOPPED
            proc.process = None
            proc.pid = None
            logger.info(f"Endpoint {endpoint} stopped")

        return True

    async def restart_endpoint(self, endpoint: str) -> bool:
        """Restart a vLLM endpoint.

        Args:
            endpoint: Endpoint name

        Returns:
            True if restarted successfully
        """
        proc = self._processes.get(endpoint)
        if proc:
            proc.recovery_attempts += 1
            if proc.recovery_attempts > self._max_recovery:
                logger.error(
                    f"Endpoint {endpoint} exceeded max recovery attempts "
                    f"({self._max_recovery})"
                )
                proc.status = ProcessStatus.FAILED
                return False

        await self.stop_endpoint(endpoint)
        await asyncio.sleep(2)  # Brief cooldown
        return await self.start_endpoint(endpoint)

    async def start_all(self) -> dict[str, bool]:
        """Start all configured endpoints.

        Returns:
            Dict mapping endpoint name to success status
        """
        results = {}
        for endpoint in self._endpoints_config:
            try:
                results[endpoint] = await self.start_endpoint(endpoint)
            except Exception as e:
                logger.error(f"Failed to start {endpoint}: {e}")
                results[endpoint] = False
        return results

    async def stop_all(self) -> dict[str, bool]:
        """Stop all running endpoints.

        Returns:
            Dict mapping endpoint name to success status
        """
        results = {}
        for endpoint in list(self._processes.keys()):
            try:
                results[endpoint] = await self.stop_endpoint(endpoint)
            except Exception as e:
                logger.error(f"Failed to stop {endpoint}: {e}")
                results[endpoint] = False
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # On-Demand Loading
    # ─────────────────────────────────────────────────────────────────────────

    async def ensure_model_loaded(self, model: str) -> str | None:
        """Ensure a model is loaded, starting endpoint if needed.

        Args:
            model: Model ID to load

        Returns:
            Endpoint name where model is available, or None if failed
        """
        # First, check if model is already loaded
        for name, proc in self._processes.items():
            if proc.status == ProcessStatus.HEALTHY and proc.model == model:
                return name

        # Find an endpoint configured for this model
        for name, config in self._endpoints_config.items():
            if model in config.models:
                proc = self._processes.get(name)
                if proc and proc.status == ProcessStatus.HEALTHY:
                    return name
                # Start this endpoint
                if await self.start_endpoint(name):
                    return name

        # Try model routing from config
        try:
            from ..core.config import get_config
            config = get_config()
            routing = config._raw.get("gaius", {}).get("inference", {}).get(
                "model_routing", {}
            )
            endpoint = routing.get(model) or routing.get("default")
            if endpoint and endpoint in self._endpoints_config:
                if await self.start_endpoint(endpoint):
                    return endpoint
        except Exception:
            pass

        # Fallback: try any endpoint with available GPUs
        for name, config in self._endpoints_config.items():
            proc = self._processes.get(name)
            if not proc or proc.status == ProcessStatus.STOPPED:
                # Try to start with this model
                # Note: This would require model switching support
                logger.warning(
                    f"Model {model} not found in config, trying endpoint {name}"
                )
                if await self.start_endpoint(name):
                    return name

        logger.error(f"No endpoint available for model: {model}")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Health Monitoring
    # ─────────────────────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        """Background health check loop."""
        while self._running:
            try:
                await self._check_all_health()
            except Exception as e:
                logger.error(f"Health check error: {e}")

            # Wait for next interval or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._health_interval,
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue loop

    async def _check_all_health(self) -> None:
        """Check health of all running endpoints."""
        import httpx

        for endpoint, proc in list(self._processes.items()):
            if proc.status not in (ProcessStatus.HEALTHY, ProcessStatus.UNHEALTHY):
                continue

            # Check if process is still running
            if proc.process and proc.process.returncode is not None:
                logger.warning(
                    f"Process for {endpoint} exited with code "
                    f"{proc.process.returncode}"
                )
                proc.status = ProcessStatus.FAILED
                proc.consecutive_failures += 1

                # Attempt auto-recovery
                if proc.recovery_attempts < self._max_recovery:
                    logger.info(f"Attempting auto-recovery for {endpoint}")
                    asyncio.create_task(self.restart_endpoint(endpoint))
                continue

            # HTTP health check
            config = self._endpoints_config[endpoint]
            base_url = config.url.rstrip("/v1")

            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(f"{base_url}/v1/models", timeout=5)
                    if r.status_code == 200:
                        proc.status = ProcessStatus.HEALTHY
                        proc.consecutive_failures = 0
                        proc.last_health_check = datetime.now()
                    else:
                        proc.consecutive_failures += 1
            except Exception:
                proc.consecutive_failures += 1

            # Mark unhealthy after consecutive failures
            if proc.consecutive_failures >= self._max_failures:
                if proc.status == ProcessStatus.HEALTHY:
                    logger.warning(
                        f"Endpoint {endpoint} marked unhealthy after "
                        f"{proc.consecutive_failures} failures"
                    )
                    proc.status = ProcessStatus.UNHEALTHY

    async def health_check(self, endpoint: str) -> bool:
        """Check health of a specific endpoint.

        Args:
            endpoint: Endpoint name

        Returns:
            True if healthy
        """
        import httpx

        proc = self._processes.get(endpoint)
        if not proc or proc.status == ProcessStatus.STOPPED:
            return False

        config = self._endpoints_config.get(endpoint)
        if not config:
            return False

        base_url = config.url.rstrip("/v1")

        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{base_url}/v1/models", timeout=5)
                return r.status_code == 200
        except Exception:
            return False

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all configured endpoints.

        Returns:
            Dict mapping endpoint name to health status
        """
        results = {}
        for endpoint in self._endpoints_config:
            results[endpoint] = await self.health_check(endpoint)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Status & Logs
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get comprehensive orchestrator status."""
        endpoints = {}
        for name, config in self._endpoints_config.items():
            proc = self._processes.get(name)
            endpoints[name] = {
                "configured": True,
                "models": config.models,
                "gpus": config.gpus,
                "tensor_parallel": config.tensor_parallel,
                "status": proc.status.value if proc else "stopped",
                "pid": proc.pid if proc else None,
                "started_at": proc.started_at.isoformat() if proc and proc.started_at else None,
                "consecutive_failures": proc.consecutive_failures if proc else 0,
                "recovery_attempts": proc.recovery_attempts if proc else 0,
            }

        return {
            "running": self._running,
            "endpoints": endpoints,
            "total_configured": len(self._endpoints_config),
            "total_running": sum(
                1 for p in self._processes.values()
                if p.status == ProcessStatus.HEALTHY
            ),
        }

    def get_endpoint_status(self, endpoint: str) -> VLLMProcess | None:
        """Get status for a specific endpoint."""
        return self._processes.get(endpoint)

    def get_logs(self, endpoint: str, lines: int = 50) -> list[str]:
        """Get recent logs from an endpoint.

        Args:
            endpoint: Endpoint name
            lines: Number of lines to return

        Returns:
            List of log lines (combined stdout/stderr)
        """
        proc = self._processes.get(endpoint)
        if not proc:
            return []

        # Combine and sort by recency (simplified: just combine)
        combined = list(proc.stdout_buffer)[-lines//2:] + \
                   list(proc.stderr_buffer)[-lines//2:]
        return combined[-lines:]

    async def cleanup_stale_processes(self) -> dict[str, Any]:
        """Kill stale vLLM processes to free GPU memory.

        Finds and terminates any orphaned vLLM processes from previous
        sessions that may be holding GPU memory without being tracked.

        Returns:
            Dict with cleanup results
        """
        import subprocess

        results = {
            "processes_found": 0,
            "processes_killed": 0,
            "pids_killed": [],
            "errors": [],
        }

        try:
            # Find all vLLM processes
            ps_result = subprocess.run(
                ["pgrep", "-f", "vllm.entrypoints|vllm serve"],
                capture_output=True,
                text=True,
            )

            if ps_result.returncode == 0 and ps_result.stdout.strip():
                pids = ps_result.stdout.strip().split("\n")
                results["processes_found"] = len(pids)

                for pid_str in pids:
                    pid = int(pid_str.strip())

                    # Check if this is a tracked process
                    tracked = any(
                        p.pid == pid
                        for p in self._processes.values()
                        if p.process is not None
                    )

                    if not tracked:
                        try:
                            # Kill the orphaned process
                            os.kill(pid, 9)  # SIGKILL
                            results["processes_killed"] += 1
                            results["pids_killed"].append(pid)
                            logger.info(f"Killed stale vLLM process: {pid}")
                        except ProcessLookupError:
                            pass  # Already dead
                        except PermissionError as e:
                            results["errors"].append(f"Permission denied for PID {pid}")

            # Also clear any CUDA memory caches
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("Cleared CUDA cache")
            except ImportError:
                pass

            # Clear our internal state for failed processes
            for endpoint, proc in list(self._processes.items()):
                if proc.status in (ProcessStatus.FAILED, ProcessStatus.STOPPED):
                    del self._processes[endpoint]

            # Brief wait for GPU memory to be freed
            await asyncio.sleep(2)

            logger.info(
                f"Cleanup complete: found {results['processes_found']}, "
                f"killed {results['processes_killed']}"
            )

        except Exception as e:
            results["errors"].append(str(e))
            logger.error(f"Cleanup error: {e}")

        return results

    async def clean_start(self, endpoints: list[str] | None = None) -> dict[str, Any]:
        """Perform cleanup and start endpoints from clean slate.

        This is the recommended way to start Gaius for overnight runs.

        Args:
            endpoints: Specific endpoints to start (None = all)

        Returns:
            Dict with cleanup and startup results
        """
        results = {
            "cleanup": {},
            "startup": {},
            "success": False,
        }

        # Step 1: Cleanup stale processes
        results["cleanup"] = await self.cleanup_stale_processes()

        # Step 2: Start orchestrator
        await self.start()

        # Step 3: Start requested endpoints
        if endpoints is None:
            # Default to reasoning (for evolution) if none specified
            endpoints = ["reasoning"]

        for endpoint in endpoints:
            if endpoint in self._endpoints_config:
                try:
                    success = await self.start_endpoint(endpoint)
                    results["startup"][endpoint] = success
                except Exception as e:
                    results["startup"][endpoint] = False
                    logger.error(f"Failed to start {endpoint}: {e}")

        # Determine overall success
        results["success"] = any(results["startup"].values())

        return results


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_orchestrator: GPUOrchestrator | None = None


def get_orchestrator() -> GPUOrchestrator:
    """Get or create the GPU orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = GPUOrchestrator()
    return _orchestrator
