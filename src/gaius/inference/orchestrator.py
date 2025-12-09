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
import signal
import subprocess

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
    context_length: int = 32768  # Per-endpoint context length
    max_num_seqs: int = 256  # Per-endpoint max concurrent sequences


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
        """Load endpoint configuration from engine config (gaius.agents)."""
        try:
            from ..engine.config import load_config as load_engine_config

            engine_config = load_engine_config()

            # Load vLLM backend settings
            self._vllm_binary = engine_config.vllm.binary
            self._gpu_memory_util = engine_config.vllm.gpu_memory_utilization
            self._max_model_len = engine_config.vllm.max_model_len
            self._max_num_seqs = 256  # Default, overridden per-endpoint
            self._health_interval = 15
            self._startup_timeout = 180  # 3 min for large models
            self._max_failures = 3
            self._max_recovery = engine_config.startup.max_restart_attempts

            # Build endpoint configs from agents with vLLM backend
            gpu_offset = 0  # Track GPU allocation
            for name, agent in engine_config.agents.items():
                if agent.backend != "vllm":
                    continue  # Skip optillm-only agents

                if agent.endpoint is None:
                    continue  # Skip agents without endpoint config

                # Calculate GPU assignment based on requirements
                num_gpus = agent.resources.gpus
                gpus = list(range(gpu_offset, gpu_offset + num_gpus))
                # Don't advance offset for now - let dynamic allocation handle it

                self._endpoints_config[name] = EndpointConfig(
                    name=name,
                    url=f"http://localhost:{agent.endpoint.port}/v1",
                    models=[agent.model],
                    gpus=gpus,
                    tensor_parallel=agent.endpoint.tensor_parallel,
                    context_length=agent.resources.context_length,
                    max_num_seqs=agent.endpoint.max_num_seqs,
                )

            # Store preload endpoints for reference
            self._preload_endpoints = engine_config.startup.preload_endpoints

            logger.info(f"Loaded {len(self._endpoints_config)} endpoint configs from agents")

        except Exception as e:
            logger.warning(f"Failed to load orchestrator config: {e}")
            import traceback
            traceback.print_exc()
            # Create default endpoint
            self._endpoints_config["fast"] = EndpointConfig(
                name="fast",
                url="http://localhost:8083/v1",
                models=["mistralai/Mistral-7B-Instruct-v0.3"],
                gpus=[0],
            )
            self._vllm_binary = "vllm"
            self._gpu_memory_util = 0.90
            self._max_model_len = 65536
            self._max_num_seqs = 256
            self._health_interval = 15
            self._startup_timeout = 180
            self._max_failures = 3
            self._max_recovery = 3
            self._preload_endpoints = ["fast"]

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

        # Ensure HF_HOME is set for model cache
        if "HF_HOME" not in env:
            # Common model cache locations
            for hf_path in ["/raid/cache/huggingface", os.path.expanduser("~/.cache/huggingface")]:
                if os.path.exists(hf_path):
                    env["HF_HOME"] = hf_path
                    break

        # Build vLLM command - use per-endpoint context and sequence limits
        cmd = [
            self._vllm_binary, "serve", proc.model,
            "--port", str(proc.port),
            "--gpu-memory-utilization", str(self._gpu_memory_util),
            "--max-model-len", str(config.context_length),
            "--max-num-seqs", str(config.max_num_seqs),
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
        """Gracefully stop a vLLM instance and all its child processes.

        Uses process group killing to ensure tensor-parallel workers are
        also terminated, preventing GPU memory leaks from orphaned processes.

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

        pid = proc.pid
        pgid = None

        # Try to get process group ID for killing child processes (tensor-parallel workers)
        try:
            if pid:
                pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError):
            pass

        # Send SIGTERM to process group if available, otherwise just parent
        if pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
                logger.debug(f"Sent SIGTERM to process group {pgid}")
            except (ProcessLookupError, PermissionError):
                proc.process.terminate()
        else:
            proc.process.terminate()

        try:
            await asyncio.wait_for(proc.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Force kill the entire process group
            logger.warning(f"Force killing endpoint {endpoint}")
            if pgid:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                    logger.debug(f"Sent SIGKILL to process group {pgid}")
                except (ProcessLookupError, PermissionError):
                    proc.process.kill()
            else:
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

    # ─────────────────────────────────────────────────────────────────────────
    # Endpoint Discovery API
    # ─────────────────────────────────────────────────────────────────────────

    def get_configured_endpoints(self) -> list[str]:
        """Return all endpoint names from config.

        Returns:
            List of endpoint names that are configured (may not be running)
        """
        return list(self._endpoints_config.keys())

    def get_preload_endpoints(self) -> list[str]:
        """Return endpoints that should be preloaded on startup.

        Returns:
            List of endpoint names from startup.preload-endpoints config
        """
        return getattr(self, "_preload_endpoints", ["fast"])

    def get_endpoint_config(self, endpoint: str) -> EndpointConfig | None:
        """Get configuration for a specific endpoint.

        Args:
            endpoint: Endpoint name

        Returns:
            EndpointConfig if found, None otherwise
        """
        return self._endpoints_config.get(endpoint)

    def get_running_endpoints(self) -> list[str]:
        """Return currently running (healthy) endpoints.

        Returns:
            List of endpoint names that are currently healthy
        """
        return [
            name for name, proc in self._processes.items()
            if proc.status == ProcessStatus.HEALTHY
        ]

    async def discover_running_endpoints(self) -> list[dict[str, Any]]:
        """Probe ports to find actually running endpoints.

        Checks all configured endpoints by attempting HTTP health checks.
        This can discover endpoints started by external processes (e.g., MCP).

        Returns:
            List of dicts with endpoint info for each responding endpoint
        """
        import httpx

        discovered = []

        for name, config in self._endpoints_config.items():
            base_url = config.url.rstrip("/v1")
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(f"{base_url}/v1/models", timeout=3)
                    if r.status_code == 200:
                        # Try to parse model info
                        try:
                            data = r.json()
                            models = [m.get("id", "unknown") for m in data.get("data", [])]
                        except Exception:
                            models = config.models

                        discovered.append({
                            "name": name,
                            "url": config.url,
                            "port": self._extract_port(config.url),
                            "models": models,
                            "status": "healthy",
                            "tensor_parallel": config.tensor_parallel,
                            "gpus": config.gpus,
                        })
            except Exception:
                pass  # Endpoint not responding

        return discovered

    def get_default_endpoint(self) -> str | None:
        """Get the best available endpoint for general inference.

        Priority order:
        1. orchestrator (if healthy) - meta-cognitive routing
        2. fast (if healthy) - quick responses
        3. Any healthy endpoint

        Returns:
            Endpoint name or None if none available
        """
        # Priority order
        priority = ["orchestrator", "fast", "fast-2", "coding"]

        for name in priority:
            proc = self._processes.get(name)
            if proc and proc.status == ProcessStatus.HEALTHY:
                return name

        # Fall back to any healthy endpoint
        for name, proc in self._processes.items():
            if proc.status == ProcessStatus.HEALTHY:
                return name

        return None

    async def wait_for_gpu_free(
        self, gpus: list[int] | None = None, timeout: float = 30.0, threshold_mb: int = 500
    ) -> bool:
        """Wait until specified GPUs have minimal memory usage.

        This is critical for tier-4 tests where tensor-parallel vLLM instances
        require all assigned GPUs to be free before starting.

        Args:
            gpus: List of GPU indices to check (None = all GPUs)
            timeout: Maximum time to wait in seconds
            threshold_mb: Consider GPU free if using less than this many MB

        Returns:
            True if all GPUs are free within timeout
        """
        import time

        start = time.time()
        while time.time() - start < timeout:
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=index,memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if result.returncode != 0:
                    logger.warning("nvidia-smi failed, assuming GPUs busy")
                    await asyncio.sleep(1.0)
                    continue

                all_free = True
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split(",")
                    if len(parts) < 2:
                        continue
                    try:
                        gpu_idx = int(parts[0].strip())
                        mem_used = float(parts[1].strip())

                        # Check if this GPU is in our target list
                        if gpus is None or gpu_idx in gpus:
                            if mem_used > threshold_mb:
                                logger.debug(
                                    f"GPU {gpu_idx} still has {mem_used:.0f} MiB in use"
                                )
                                all_free = False
                                break
                    except (ValueError, IndexError):
                        continue

                if all_free:
                    logger.info("All target GPUs are free")
                    return True

            except subprocess.TimeoutExpired:
                logger.warning("nvidia-smi timed out")
            except Exception as e:
                logger.warning(f"GPU check error: {e}")

            await asyncio.sleep(1.0)

        logger.warning(f"GPUs not free after {timeout}s timeout")
        return False

    async def cleanup_stale_processes(self) -> dict[str, Any]:
        """Kill stale vLLM processes to free GPU memory.

        Uses comprehensive process detection including tensor-parallel workers
        (VLLM::Worker, VLLM::EngineCore) and process group killing to ensure
        complete cleanup.

        Returns:
            Dict with cleanup results
        """
        results = {
            "processes_found": 0,
            "processes_killed": 0,
            "pids_killed": [],
            "process_groups_killed": [],
            "errors": [],
        }

        # Comprehensive patterns for vLLM processes
        # vLLM spawns various worker types for tensor-parallel execution
        patterns = [
            r"python.*vllm",         # Main vLLM server
            r"vllm\.entrypoints",    # Entry point modules
            r"VLLM::Worker",         # Tensor-parallel workers
            r"VLLM::EngineCore",     # Engine core processes
            r"ray::IDLE",            # Ray workers (used by some vLLM configs)
        ]

        try:
            pids_found = set()

            # Collect all matching PIDs
            for pattern in patterns:
                try:
                    ps_result = subprocess.run(
                        ["pgrep", "-f", pattern],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if ps_result.returncode == 0 and ps_result.stdout.strip():
                        for pid_str in ps_result.stdout.strip().split("\n"):
                            if pid_str.strip():
                                pids_found.add(int(pid_str.strip()))
                except subprocess.TimeoutExpired:
                    pass

            results["processes_found"] = len(pids_found)

            # Kill each process (try process group first)
            for pid in pids_found:
                # Check if this is a tracked process we manage
                tracked = any(
                    p.pid == pid
                    for p in self._processes.values()
                    if p.process is not None
                )

                if not tracked:
                    try:
                        # Try to kill process group
                        try:
                            pgid = os.getpgid(pid)
                            os.killpg(pgid, signal.SIGKILL)
                            results["process_groups_killed"].append(pgid)
                            logger.info(f"Killed process group {pgid} (from pid {pid})")
                        except (ProcessLookupError, PermissionError):
                            # Fallback to killing just the process
                            os.kill(pid, signal.SIGKILL)
                            logger.info(f"Killed stale vLLM process: {pid}")

                        results["processes_killed"] += 1
                        results["pids_killed"].append(pid)

                    except ProcessLookupError:
                        pass  # Already dead
                    except PermissionError:
                        results["errors"].append(f"Permission denied for PID {pid}")

            # Clear CUDA memory caches
            try:
                import torch
                if torch.cuda.is_available():
                    for i in range(torch.cuda.device_count()):
                        with torch.cuda.device(i):
                            torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    logger.info("Cleared CUDA cache on all devices")
            except ImportError:
                logger.debug("torch not available for CUDA cache clearing")
            except Exception as e:
                logger.debug(f"CUDA cache clear error: {e}")

            # Clear our internal state for failed/stopped processes
            for endpoint, proc in list(self._processes.items()):
                if proc.status in (ProcessStatus.FAILED, ProcessStatus.STOPPED):
                    del self._processes[endpoint]

            # Wait for GPU memory to be freed
            await asyncio.sleep(2)

            logger.info(
                f"Cleanup complete: found {results['processes_found']}, "
                f"killed {results['processes_killed']}, "
                f"groups killed {len(results['process_groups_killed'])}"
            )

        except Exception as e:
            results["errors"].append(str(e))
            logger.error(f"Cleanup error: {e}")

        return results

    async def clean_start(
        self,
        endpoints: list[str] | None = None,
        verify_gpu_free: bool = True,
        gpu_wait_timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Perform cleanup and start endpoints from clean slate.

        This is the recommended way to start Gaius for overnight runs or
        tier-4+ tests that require guaranteed GPU availability.

        Args:
            endpoints: Specific endpoints to start (None = reasoning)
            verify_gpu_free: Wait for GPUs to be free before starting
            gpu_wait_timeout: Max seconds to wait for GPUs to free

        Returns:
            Dict with cleanup and startup results
        """
        results = {
            "cleanup": {},
            "gpu_verification": {},
            "startup": {},
            "success": False,
        }

        # Step 1: Cleanup stale processes
        results["cleanup"] = await self.cleanup_stale_processes()

        # Step 2: Verify GPU memory is actually free
        if verify_gpu_free:
            # Determine which GPUs we need
            target_gpus = set()
            target_endpoints = endpoints or ["reasoning"]
            for ep in target_endpoints:
                if ep in self._endpoints_config:
                    target_gpus.update(self._endpoints_config[ep].gpus)

            if target_gpus:
                gpu_free = await self.wait_for_gpu_free(
                    list(target_gpus), timeout=gpu_wait_timeout
                )
                results["gpu_verification"] = {
                    "gpus_checked": list(target_gpus),
                    "all_free": gpu_free,
                }

                if not gpu_free:
                    # Last resort: try nvidia-smi reset (may require root)
                    logger.warning(
                        "GPUs not free after timeout, attempting nvidia-smi reset"
                    )
                    try:
                        reset_result = subprocess.run(
                            ["nvidia-smi", "--gpu-reset"],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        results["gpu_verification"]["reset_attempted"] = True
                        results["gpu_verification"]["reset_success"] = (
                            reset_result.returncode == 0
                        )
                        if reset_result.returncode == 0:
                            await asyncio.sleep(5)  # Wait for reset
                    except Exception as e:
                        results["gpu_verification"]["reset_error"] = str(e)
                        logger.warning(f"GPU reset failed: {e}")

        # Step 3: Start orchestrator
        await self.start()

        # Step 4: Start requested endpoints
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
