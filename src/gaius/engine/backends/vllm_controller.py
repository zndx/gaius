"""vLLM backend controller.

Manages vLLM subprocess lifecycle with GPU allocation integration.
Handles process startup, health monitoring, and graceful shutdown.
"""

import asyncio
import logging
import os
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import httpx

from ..config import AgentConfig, EngineConfig, VllmConfig
from ..resources import (
    AllocationState,
    GPUAllocation,
    ResourceManager,
    ResourceUnavailable,
)

logger = logging.getLogger(__name__)


class ProcessStatus(Enum):
    """vLLM process status."""

    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    FAILED = "failed"


# vLLM startup progress patterns
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
class VLLMProcess:
    """State of a running vLLM instance."""

    agent_alias: str
    model: str
    port: int
    gpu_ids: list[int]
    tensor_parallel: int = 1
    context_length: int = 32768  # Per-endpoint context length
    max_num_seqs: int = 256  # Max concurrent sequences
    task: str = "generate"  # vLLM task: generate | embed | classify | reward

    # Process state
    process: Optional[asyncio.subprocess.Process] = None
    pid: Optional[int] = None
    status: ProcessStatus = ProcessStatus.STOPPED
    started_at: Optional[datetime] = None
    last_health_check: Optional[datetime] = None
    consecutive_failures: int = 0
    recovery_attempts: int = 0

    # Log buffers (circular)
    stdout_buffer: deque = field(default_factory=lambda: deque(maxlen=500))
    stderr_buffer: deque = field(default_factory=lambda: deque(maxlen=500))

    # Metrics
    requests_served: int = 0

    @property
    def base_url(self) -> str:
        """Get base URL for this endpoint."""
        return f"http://localhost:{self.port}/v1"


@dataclass
class VLLMRequest:
    """Request to vLLM backend.

    Attributes:
        messages: Chat messages in OpenAI format
        model: Model identifier
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        agent_alias: Agent this request is for
    """

    messages: list[dict[str, str]]
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048
    agent_alias: Optional[str] = None


@dataclass
class VLLMResponse:
    """Response from vLLM backend.

    Attributes:
        content: Generated text content
        model: Model that generated response
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Request latency in milliseconds
        error: Error message if request failed
    """

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


class VLLMController:
    """Controller for vLLM inference backend.

    Manages vLLM subprocess lifecycle with GPU allocation tracking.
    Supports multi-GPU tensor-parallel configurations.
    """

    def __init__(
        self,
        config: EngineConfig,
        resource_manager: ResourceManager,
    ):
        """Initialize vLLM controller.

        Args:
            config: Engine configuration
            resource_manager: Resource manager for GPU allocation
        """
        self.config = config
        self.vllm_config = config.vllm
        self.resource_manager = resource_manager

        # vLLM binary and settings
        self._binary = self.vllm_config.binary
        self._gpu_memory_util = self.vllm_config.gpu_memory_utilization
        self._max_model_len = self.vllm_config.max_model_len
        self._dtype = self.vllm_config.dtype
        self._extra_args = self.vllm_config.extra_args

        # Process tracking
        self._processes: dict[str, VLLMProcess] = {}
        self._lock = asyncio.Lock()

        # Port allocation (starting port, incrementing)
        self._next_port = 8080
        self._allocated_ports: set[int] = set()

        # Health check settings
        self._startup_timeout = 180  # 3 minutes for large models
        self._max_failures = 3
        self._max_recovery = 3

        # HTTP client for health checks
        self._client: Optional[httpx.AsyncClient] = None

        logger.info(
            f"VLLMController initialized: binary={self._binary}, "
            f"gpu_mem_util={self._gpu_memory_util}"
        )

    async def start(self) -> None:
        """Start the controller."""
        self._client = httpx.AsyncClient(timeout=30)
        logger.info("VLLMController started")

    async def stop(self) -> None:
        """Stop the controller and all managed processes."""
        # Stop all processes
        for alias in list(self._processes.keys()):
            await self.stop_endpoint(alias)

        if self._client:
            await self._client.aclose()
            self._client = None

        logger.info("VLLMController stopped")

    def _allocate_port(self) -> int:
        """Allocate next available port."""
        while self._next_port in self._allocated_ports:
            self._next_port += 1
        port = self._next_port
        self._allocated_ports.add(port)
        self._next_port += 1
        return port

    def _release_port(self, port: int) -> None:
        """Release a port."""
        self._allocated_ports.discard(port)

    async def start_endpoint(
        self,
        agent_alias: str,
        agent_config: Optional[AgentConfig] = None,
    ) -> VLLMProcess:
        """Start a vLLM endpoint for an agent.

        Args:
            agent_alias: Agent identifier
            agent_config: Agent configuration (uses engine config if not provided)

        Returns:
            VLLMProcess with startup state

        Raises:
            ResourceUnavailable: If GPUs cannot be allocated
            ValueError: If agent not found in config
        """
        async with self._lock:
            # Get agent config
            if agent_config is None:
                if agent_alias not in self.config.agents:
                    raise ValueError(f"Unknown agent: {agent_alias}")
                agent_config = self.config.agents[agent_alias]

            # Check if already running
            if agent_alias in self._processes:
                proc = self._processes[agent_alias]
                if proc.status in (ProcessStatus.HEALTHY, ProcessStatus.STARTING):
                    logger.info(f"Endpoint {agent_alias} already running")
                    return proc

            # Allocate GPUs
            allocation = self.resource_manager.allocate(agent_alias, agent_config)

            # Allocate port
            port = self._allocate_port()

            # Create process state
            # Get max_num_seqs and task from endpoint config if available
            max_num_seqs = 256  # Default
            task = "generate"  # Default
            if agent_config.endpoint:
                if agent_config.endpoint.max_num_seqs:
                    max_num_seqs = agent_config.endpoint.max_num_seqs
                if agent_config.endpoint.task:
                    task = agent_config.endpoint.task

            proc = VLLMProcess(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=port,
                gpu_ids=allocation.gpu_ids,
                tensor_parallel=agent_config.resources.gpus,
                context_length=agent_config.resources.context_length,
                max_num_seqs=max_num_seqs,
                task=task,
                status=ProcessStatus.STARTING,
            )
            self._processes[agent_alias] = proc

        # Start outside lock
        success = await self._start_vllm_process(proc)

        if success:
            # Update allocation state with PID for orphan detection
            allocation.mark_active(port, pid=proc.pid)
            proc.status = ProcessStatus.HEALTHY
        else:
            # Release resources on failure
            proc.status = ProcessStatus.FAILED
            self.resource_manager.release(agent_alias)
            self._release_port(port)

        return proc

    async def start_model(
        self,
        endpoint_name: str,
        model_id: str,
        port: int,
        gpu_ids: list[int],
        serve_command: list[str] | None = None,
        env_vars: dict[str, str] | None = None,
        context_length: int = 32768,
        max_num_seqs: int = 256,
        tensor_parallel: int = 1,
    ) -> VLLMProcess:
        """Start a vLLM endpoint for a dynamic model (not from agent config).

        This method supports starting any model from the registry, not just
        pre-configured agents. Used by workload allocation for capabilities
        like reasoning that may require different models.

        Args:
            endpoint_name: Name for this endpoint
            model_id: HuggingFace model ID
            port: Port to serve on
            gpu_ids: GPU IDs to use
            serve_command: Optional custom vLLM command (uses default if None)
            env_vars: Optional environment variables to merge
            context_length: Max context length
            max_num_seqs: Max concurrent sequences
            tensor_parallel: Tensor parallel size

        Returns:
            VLLMProcess with startup state
        """
        async with self._lock:
            # Check if already running
            if endpoint_name in self._processes:
                proc = self._processes[endpoint_name]
                if proc.status in (ProcessStatus.HEALTHY, ProcessStatus.STARTING):
                    logger.info(f"Endpoint {endpoint_name} already running")
                    return proc

            # Create process state
            proc = VLLMProcess(
                agent_alias=endpoint_name,
                model=model_id,
                port=port,
                gpu_ids=gpu_ids,
                tensor_parallel=tensor_parallel,
                context_length=context_length,
                max_num_seqs=max_num_seqs,
                task="generate",
                status=ProcessStatus.STARTING,
            )
            self._processes[endpoint_name] = proc

        # Start outside lock
        success = await self._start_vllm_process(proc, serve_command, env_vars)

        if success:
            proc.status = ProcessStatus.HEALTHY
        else:
            proc.status = ProcessStatus.FAILED
            self._release_port(port)

        return proc

    async def _start_vllm_process(
        self,
        proc: VLLMProcess,
        serve_command: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> bool:
        """Start the actual vLLM subprocess.

        Args:
            proc: VLLMProcess state object
            serve_command: Optional custom command (uses default vLLM command if None)
            extra_env: Optional extra environment variables to merge
        """
        # Build environment
        gpu_str = ",".join(str(g) for g in proc.gpu_ids)
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu_str

        # Merge extra environment variables if provided
        if extra_env:
            env.update(extra_env)

        # Use custom serve_command if provided, otherwise build default
        if serve_command:
            cmd = serve_command
        else:
            # Build default vLLM command
            cmd = [
                self._binary,
                "serve",
                proc.model,
                "--port",
                str(proc.port),
                "--gpu-memory-utilization",
                str(self._gpu_memory_util),
                "--max-model-len",
                str(proc.context_length),
                "--max-num-seqs",
                str(proc.max_num_seqs),
                "--dtype",
                self._dtype,
            ]

            # Add task if not default (generate)
            if proc.task and proc.task != "generate":
                cmd.extend(["--task", proc.task])
                # Embedding models often need trust-remote-code for custom tokenizers
                cmd.append("--trust-remote-code")

            # Add tensor parallelism if needed
            if proc.tensor_parallel > 1:
                cmd.extend(["--tensor-parallel-size", str(proc.tensor_parallel)])

            # Add extra args from config
            cmd.extend(self._extra_args)

        logger.info(
            f"Starting vLLM for {proc.agent_alias}: "
            f"CUDA_VISIBLE_DEVICES={gpu_str} {' '.join(cmd)}"
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
            asyncio.create_task(self._read_stdout(proc))
            asyncio.create_task(self._read_stderr(proc))

            # Wait for healthy
            healthy = await self._wait_for_healthy(proc)

            if healthy:
                proc.consecutive_failures = 0
                logger.info(
                    f"Endpoint {proc.agent_alias} is healthy "
                    f"(PID: {proc.pid}, port: {proc.port})"
                )
                return True
            else:
                logger.error(f"Endpoint {proc.agent_alias} failed to become healthy")
                return False

        except FileNotFoundError:
            logger.error(f"vLLM binary not found: {self._binary}")
            proc.recovery_attempts = 999  # Don't retry if binary missing
            return False
        except Exception as e:
            logger.error(f"Failed to start vLLM for {proc.agent_alias}: {e}")
            return False

    async def _read_stdout(self, proc: VLLMProcess) -> None:
        """Read stdout from vLLM process."""
        if not proc.process or not proc.process.stdout:
            return

        try:
            while True:
                line = await proc.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                proc.stdout_buffer.append(decoded)
                # Only log at debug - vLLM is very verbose
                logger.debug(f"[{proc.agent_alias}] {decoded}")
        except Exception:
            pass

    async def _read_stderr(self, proc: VLLMProcess) -> None:
        """Read stderr from vLLM process."""
        if not proc.process or not proc.process.stderr:
            return

        try:
            while True:
                line = await proc.process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                proc.stderr_buffer.append(decoded)
                # Only log critical errors, not vLLM's verbose tracebacks
                lower = decoded.lower()
                if "cuda out of memory" in lower or "runtimeerror" in lower:
                    logger.error(f"[{proc.agent_alias}] {decoded}")
                elif "error" in lower and "error 12-" not in lower:
                    # Skip timestamped error lines (vLLM logging spam)
                    logger.debug(f"[{proc.agent_alias}] {decoded}")
        except Exception:
            pass

    async def _wait_for_healthy(self, proc: VLLMProcess) -> bool:
        """Wait for endpoint to become healthy."""
        start = datetime.now()

        while (datetime.now() - start).total_seconds() < self._startup_timeout:
            # Check if process crashed
            if proc.process and proc.process.returncode is not None:
                logger.error(
                    f"vLLM process for {proc.agent_alias} exited with code "
                    f"{proc.process.returncode}"
                )
                return False

            # Try HTTP health check
            if await self._check_health(proc):
                return True

            await asyncio.sleep(2)

        return False

    async def _check_health(self, proc: VLLMProcess) -> bool:
        """Check if endpoint is healthy."""
        if not self._client:
            return False

        try:
            url = f"http://localhost:{proc.port}/v1/models"
            response = await self._client.get(url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    async def stop_endpoint(
        self, agent_alias: str, timeout: float = 30.0
    ) -> bool:
        """Stop a vLLM endpoint.

        Args:
            agent_alias: Agent identifier
            timeout: Seconds to wait for graceful shutdown

        Returns:
            True if stopped successfully
        """
        async with self._lock:
            proc = self._processes.get(agent_alias)
            if not proc:
                return True

            proc.status = ProcessStatus.STOPPING
            logger.info(f"Stopping endpoint {agent_alias} (PID: {proc.pid})")

        # Stop process outside lock
        if proc.process:
            proc.process.terminate()

            try:
                await asyncio.wait_for(proc.process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Force killing endpoint {agent_alias}")
                proc.process.kill()
                await proc.process.wait()

        async with self._lock:
            proc.status = ProcessStatus.STOPPED
            proc.process = None
            proc.pid = None

            # Release resources
            self.resource_manager.release(agent_alias)
            self._release_port(proc.port)

            # Remove from tracking
            del self._processes[agent_alias]

        logger.info(f"Endpoint {agent_alias} stopped")
        return True

    async def complete(self, request: VLLMRequest) -> VLLMResponse:
        """Complete a request through vLLM.

        Args:
            request: The completion request

        Returns:
            VLLMResponse with generated content
        """
        if not self._client:
            return VLLMResponse(
                content="",
                model=request.model,
                error="Controller not started",
            )

        # Find endpoint for this agent/model
        proc = None
        if request.agent_alias:
            proc = self._processes.get(request.agent_alias)

        if not proc:
            # Find any endpoint with this model
            for p in self._processes.values():
                if p.model == request.model and p.status == ProcessStatus.HEALTHY:
                    proc = p
                    break

        if not proc or proc.status != ProcessStatus.HEALTHY:
            return VLLMResponse(
                content="",
                model=request.model,
                error=f"No healthy endpoint for model: {request.model}",
            )

        # Build OpenAI-compatible request
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        start_time = datetime.now()

        try:
            response = await self._client.post(
                f"http://localhost:{proc.port}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Parse response
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            usage = data.get("usage", {})

            proc.requests_served += 1

            return VLLMResponse(
                content=message.get("content", ""),
                model=data.get("model", request.model),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
            )

        except httpx.HTTPStatusError as e:
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"vLLM request failed: {error_msg}")

            return VLLMResponse(
                content="",
                model=request.model,
                latency_ms=latency_ms,
                error=error_msg,
            )

        except Exception as e:
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.error(f"vLLM request error: {e}")

            return VLLMResponse(
                content="",
                model=request.model,
                latency_ms=latency_ms,
                error=str(e),
            )

    def get_startup_progress(self, agent_alias: str) -> tuple[str, float]:
        """Get startup progress from vLLM output buffers.

        Args:
            agent_alias: Agent identifier

        Returns:
            Tuple of (status_message, progress_0_to_1)
        """
        proc = self._processes.get(agent_alias)
        if not proc:
            return ("Not started", 0.0)

        # Combine buffers and check recent lines
        all_output = list(proc.stdout_buffer)[-50:] + list(proc.stderr_buffer)[-50:]

        best_progress = 0.0
        best_message = "Starting"

        for line in all_output:
            for pattern, message_template, progress in VLLM_PROGRESS_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    if "{0}" in message_template and match.groups():
                        message = message_template.format(*match.groups())
                    else:
                        message = message_template

                    if progress < 0:
                        return (message, progress)

                    if progress > best_progress:
                        best_progress = progress
                        best_message = message

        return (best_message, best_progress)

    def get_recent_logs(self, agent_alias: str, lines: int = 50) -> list[str]:
        """Get recent logs from endpoint.

        Args:
            agent_alias: Agent identifier
            lines: Number of lines to return

        Returns:
            List of recent log lines
        """
        proc = self._processes.get(agent_alias)
        if not proc:
            return []

        combined = list(proc.stdout_buffer) + list(proc.stderr_buffer)
        return combined[-lines:]

    def get_process(self, agent_alias: str) -> Optional[VLLMProcess]:
        """Get process state for an agent."""
        return self._processes.get(agent_alias)

    def get_status(self) -> dict[str, Any]:
        """Get controller status.

        Returns:
            Status dict with all endpoints
        """
        endpoints = {}
        for alias, proc in self._processes.items():
            endpoints[alias] = {
                "model": proc.model,
                "port": proc.port,
                "gpu_ids": proc.gpu_ids,
                "status": proc.status.value,
                "pid": proc.pid,
                "started_at": proc.started_at.isoformat() if proc.started_at else None,
                "requests_served": proc.requests_served,
            }

        return {
            "binary": self._binary,
            "gpu_memory_utilization": self._gpu_memory_util,
            "endpoints": endpoints,
            "total_running": sum(
                1 for p in self._processes.values()
                if p.status == ProcessStatus.HEALTHY
            ),
        }

    @property
    def running_endpoints(self) -> list[str]:
        """Get list of running endpoint aliases."""
        return [
            alias
            for alias, proc in self._processes.items()
            if proc.status == ProcessStatus.HEALTHY
        ]
