"""vLLM backend controller.

Manages vLLM subprocess lifecycle with GPU allocation integration.
Handles process startup, health monitoring, and graceful shutdown.
"""

import asyncio
import json
import logging
import os
import re
from collections import deque
from pathlib import Path
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

_NIX_GCC_MARKERS = ("gcc-wrapper", "/gcc-", "gcc-15")
_REAL_CUDA_HOME = Path("/usr/local/cuda")
_HOST_GCC = Path("/usr/bin/gcc-11")
_HOST_GXX = Path("/usr/bin/g++-11")
_REPO_ROOT = Path(__file__).resolve().parents[4]
_TINYBOX_CUDA_HOME = _REPO_ROOT / ".devenv" / "tinybox-cuda"
_TINYBOX_NVCC_SRC = _REPO_ROOT / "scripts" / "lib" / "tinybox-nvcc.sh"
_TINYBOX_NINJA_SRC = _REPO_ROOT / "scripts" / "lib" / "tinybox-ninja.sh"

# Health checks pass timeout=5 on the same client. Complete must outlast
# Qwen3.8-27B thinking (prefLabel JSON after <think>). 180s ReadTimeout
# aborted clt_skos_label while the model was still generating.
VLLM_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=420.0, write=30.0, pool=30.0)
GURU_VLLM_TIMEOUT = "#EP.00000006.VLLMTIMEOUT"


def format_vllm_http_error(exc: BaseException) -> str:
    """Non-empty vLLM HTTP error. Empty ``str(httpx.ReadTimeout)`` is falsy
    and used to leak a successful Complete with no tokens.
    """
    name = type(exc).__name__
    detail = str(exc).strip()
    if isinstance(exc, httpx.TimeoutException):
        msg = f"{name}: {detail}" if detail else f"{name}: vLLM HTTP timed out"
        return (
            f"{msg}\n"
            f"  Guru: {GURU_VLLM_TIMEOUT}\n"
            f"  Try: /health fix endpoints"
        )
    if detail:
        return f"{name}: {detail}"
    return name


def _host_ninja() -> Path | None:
    home = Path(os.environ.get("HOME", "") or "") / ".local" / "bin" / "ninja"
    for candidate in (home, Path("/usr/bin/ninja"), Path("/usr/local/bin/ninja")):
        if candidate.is_file():
            return candidate
    return None


def _ensure_tinybox_cuda_home() -> Path | None:
    """Shadow CUDA_HOME so torch hits a host-LD nvcc wrapper, not /usr/local/cuda/bin/nvcc.

    Real nvcc then execs cicc from the toolkit tree; the wrapper's LD_LIBRARY_PATH
    is what cicc inherits. Nix python/ninja keep the parent LD (they need Nix glibc).
    """
    if not (_REAL_CUDA_HOME / "bin" / "nvcc").is_file():
        return None
    if not _TINYBOX_NVCC_SRC.is_file():
        raise RuntimeError(
            "Tinybox nvcc wrapper missing.\n"
            f"  Expected: {_TINYBOX_NVCC_SRC}\n"
            "  #EP.00000005.TINYBOXCUDA"
        )
    root = _TINYBOX_CUDA_HOME
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for src, name in ((_TINYBOX_NVCC_SRC, "nvcc"), (_TINYBOX_NINJA_SRC, "ninja")):
        if not src.is_file():
            raise RuntimeError(
                f"Tinybox {name} wrapper missing.\n"
                f"  Expected: {src}\n"
                "  #EP.00000005.TINYBOXCUDA"
            )
        dest = bin_dir / name
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        dest.symlink_to(src)
        if not os.access(dest, os.X_OK):
            raise RuntimeError(
                f"Tinybox {name} wrapper is not executable: {src}\n"
                "  #EP.00000005.TINYBOXCUDA"
            )
    for name in ("include", "lib64", "nvvm", "extras", "targets", "version.json"):
        src = _REAL_CUDA_HOME / name
        dst = root / name
        if src.exists() and not dst.exists():
            dst.symlink_to(src)
    for item in (_REAL_CUDA_HOME / "bin").iterdir():
        if item.name == "nvcc":
            continue
        dest = bin_dir / item.name
        if not dest.exists() and not dest.is_symlink():
            dest.symlink_to(item)
    return root


def _tinybox_cuda_compile_env(env: dict[str, str]) -> dict[str, str]:
    """Host gcc-11 + CUDA 12.4; Nix libstdc++ must not reach cicc.

    The vLLM child is Nix python (needs Nix glibc via PT_INTERP/RUNPATH).
    cicc is a host ELF. Isolate the CUDA 12.4 frontend with a CUDA_HOME
    whose bin/nvcc rewrites LD_LIBRARY_PATH to host libs only.
    """
    cleaned = dict(env)
    if _HOST_GXX.is_file() and _HOST_GCC.is_file():
        cleaned["CC"] = str(_HOST_GCC)
        cleaned["CXX"] = str(_HOST_GXX)
        cleaned["CUDAHOSTCXX"] = str(_HOST_GXX)
        cleaned["NVCC_PREPEND_FLAGS"] = "-ccbin=/usr/bin/g++-11"
    for key in list(cleaned):
        if key.startswith("NIX_"):
            cleaned.pop(key, None)
    for key in ("LIBRARY_PATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "CPATH"):
        cleaned.pop(key, None)

    original_ld = [p for p in cleaned.get("LD_LIBRARY_PATH", "").split(":") if p]
    nvidia_libs = next((p for p in original_ld if p.endswith("nvidia-libs")), None)
    # Nix python (PT_INTERP → Nix glibc). Host /usr/lib on LD_LIBRARY_PATH
    # makes it load Ubuntu libc 2.35 and abort (stack smash, exit -6).
    # cicc/as get host libs from scripts/lib/tinybox-nvcc.sh, not from here.
    keep_ld: list[str] = []
    if nvidia_libs:
        keep_ld.append(nvidia_libs)
    for p in ("/usr/local/cuda/lib64", "/usr/local/cuda/extras/CUPTI/lib64"):
        if p not in keep_ld and (p in original_ld or Path(p).is_dir()):
            keep_ld.append(p)
    cleaned["LD_LIBRARY_PATH"] = ":".join(keep_ld)

    shadow = _ensure_tinybox_cuda_home()
    if shadow is not None:
        cleaned["CUDA_HOME"] = str(shadow)
        cleaned["CUDA_PATH"] = str(shadow)
        cleaned["CUDACXX"] = str(shadow / "bin" / "nvcc")
        cleaned["NINJA"] = str(shadow / "bin" / "ninja")
        cleaned["CMAKE_MAKE_PROGRAM"] = str(shadow / "bin" / "ninja")
    else:
        cleaned["CUDA_HOME"] = cleaned.get("CUDA_HOME") or "/usr/local/cuda"
        host_ninja = _host_ninja()
        if host_ninja is not None:
            cleaned["NINJA"] = str(host_ninja)
            cleaned["CMAKE_MAKE_PROGRAM"] = str(host_ninja)

    original_path = [p for p in cleaned.get("PATH", "").split(":") if p]
    venv_bins = [
        p
        for p in original_path
        if p.endswith("/.devenv/state/venv/bin") or p.endswith("/venv/bin")
    ]
    front: list[str] = []
    if shadow is not None:
        front.append(str(shadow / "bin"))
    front.extend(["/usr/local/cuda/bin", "/usr/bin", "/bin"])
    rest = [
        p
        for p in original_path
        if p not in front
        and p not in venv_bins
        and not p.startswith("/nix/store/")
        and not any(m in p for m in _NIX_GCC_MARKERS)
    ]
    seen: list[str] = []
    for p in venv_bins + front + rest:
        if p and p not in seen:
            seen.append(p)
    cleaned["PATH"] = ":".join(seen)
    cleaned.setdefault("TORCH_CUDA_ARCH_LIST", "8.9")
    cleaned.setdefault("MAX_JOBS", "4")
    return cleaned

logger = logging.getLogger(__name__)


class ProcessStatus(Enum):
    """vLLM process status."""

    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    FAILED = "failed"
    PENDING = "pending"  # Queued for startup, waiting for another endpoint


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

    # True when the serve argv carried --enable-auto-tool-choice. vLLM rejects
    # a tools[] request on an endpoint without it, and its engine-level tool
    # parser silently eats <tool_call> markup when tools[] is absent.
    supports_tool_calls: bool = False

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

    messages: list[dict[str, Any]]
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048
    agent_alias: Optional[str] = None
    enable_thinking: bool = True
    reasoning_effort: str = "xhigh"
    preserve_thinking: bool = True
    extra_body: dict[str, Any] = field(default_factory=dict)


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
        reasoning_content: Thinking trace when the model emits one
    """

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None
    reasoning_content: str = ""
    finish_reason: str = ""
    # Structured tool calls the engine parsed: [{"id","name","arguments_json"}].
    # Populated from the backend's native tool_calls or by parsing <tool_call>
    # markup — so clients consume structure, not markup (Engine-First).
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


def qwen_tool_call_markup(tool_calls: Any) -> str:
    """Encode OpenAI-shaped vLLM tool_calls as ``<tool_call>`` JSON.

    Engine/Complete is text-in/text-out. The gaius-ui façade parses
    ``<tool_call>{"name":…,"arguments":{…}}</tool_call>`` into Grok
    ``tool_calls``. Native vLLM parsers empty ``content`` when they
    extract structured calls, so Complete must put that markup back
    in the body or the web terminal ends the turn after reasoning.
    """
    if not tool_calls:
        return ""
    if not isinstance(tool_calls, list):
        return ""
    blocks: list[str] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = (fn.get("name") or tc.get("name") or "").strip()
        if not name:
            continue
        raw_args = fn.get("arguments", tc.get("arguments", {}))
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}
        payload = json.dumps(
            {"name": name, "arguments": args},
            separators=(",", ":"),
        )
        blocks.append(f"<tool_call>{payload}</tool_call>")
    return "\n".join(blocks)


def parse_qwen_tool_call_markup(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Inverse of :func:`qwen_tool_call_markup`.

    Returns the text with every ``<tool_call>`` block removed and the calls
    it carried. The gaius-ui façade has its own Rust implementation of this;
    this one backs the CLI so ``/engine toolcall`` verifies the same wire
    format the Web Terminal consumes.
    """
    calls: list[dict[str, Any]] = []
    out: list[str] = []
    rest = text or ""
    open_tag, close_tag = "<tool_call>", "</tool_call>"
    while True:
        start = rest.find(open_tag)
        if start == -1:
            break
        out.append(rest[:start])
        after = rest[start + len(open_tag) :]
        end = after.find(close_tag)
        if end == -1:
            # Unterminated block: keep it visible rather than eat the tail.
            out.append(rest[start:])
            rest = ""
            break
        body = after[:end].strip()
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("name"):
            calls.append(
                {
                    "name": parsed["name"],
                    "arguments": parsed.get("arguments") or {},
                }
            )
        else:
            out.append(rest[start : start + len(open_tag) + end + len(close_tag)])
        rest = after[end + len(close_tag) :]
    out.append(rest)
    return "".join(out).strip(), calls


def structured_tool_calls(native: Any, content: str) -> list[dict[str, Any]]:
    """Structured calls for VLLMResponse.tool_calls, from either source.

    Prefer the backend's native OpenAI tool_calls (a native parser routed
    ``<tool_call>`` into them). With none — the parser is off, or the model
    emitted raw markup — parse the ``<tool_call>`` blocks out of ``content``.
    Result is ``[{"id","name","arguments_json"}]`` with JSON-string arguments,
    so the engine returns structure and no client parses markup (Engine-First).
    """
    out: list[dict[str, Any]] = []
    if isinstance(native, list) and native:
        for tc in native:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = (fn.get("name") or tc.get("name") or "").strip()
            if not name:
                continue
            raw = fn.get("arguments", tc.get("arguments", {}))
            args_json = raw if isinstance(raw, str) else json.dumps(raw, separators=(",", ":"))
            out.append({"id": str(tc.get("id") or ""), "name": name, "arguments_json": args_json})
        return out
    _, parsed = parse_qwen_tool_call_markup(content)
    for c in parsed:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "id": "",
            "name": name,
            "arguments_json": json.dumps(c.get("arguments") or {}, separators=(",", ":")),
        })
    return out


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
        # One vLLM serve at a time — concurrent thinking+orchestrator
        # start fights over port 8081 and TP ranks.
        self._start_gate = asyncio.Lock()

        # Port allocation - tracks ports we've allocated (system check on allocation)
        self._allocated_ports: set[int] = set()

        # Health check settings
        # Qwen3.8-27B TP=4 BF16 + 262k KV regularly exceeds 3 minutes.
        self._startup_timeout = 900
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
        self._client = httpx.AsyncClient(timeout=VLLM_HTTP_TIMEOUT)
        logger.info("VLLMController started (http read timeout=420s)")

    async def stop(self) -> None:
        """Stop the controller and all managed processes."""
        # Stop all processes
        for alias in list(self._processes.keys()):
            await self.stop_endpoint(alias)

        if self._client:
            await self._client.aclose()
            self._client = None

        logger.info("VLLMController stopped")

    def _is_port_free_on_system(self, port: int) -> bool:
        """Check if a port is free on the system (not just in our tracking).

        This prevents conflicts with external processes (kubectl port-forwards,
        other services, etc.) that may occupy ports in our allocation range.
        """
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                return True
        except OSError:
            return False

    def _allocate_port(self, start: int = 8080, end: int = 8095) -> int:
        """Allocate next available port.

        Checks both internal tracking AND system availability to prevent
        conflicts with external processes.

        Args:
            start: Start of port range (default 8080)
            end: End of port range (default 8095)

        Returns:
            Available port number

        Raises:
            RuntimeError: If no ports available in range
        """
        # Try to re-use freed ports first (scan from start)
        for port in range(start, end + 1):
            if port not in self._allocated_ports and self._is_port_free_on_system(port):
                self._allocated_ports.add(port)
                logger.debug(f"Allocated port {port} (system-verified)")
                return port

        raise RuntimeError(
            f"No available ports in range {start}-{end}. "
            f"Allocated: {sorted(self._allocated_ports)}"
        )

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
            RuntimeError: If /dev/shm cannot hold KV offload (#EP.00000007)
        """
        from ..resources.shm import require_shm_for_offload

        peek = agent_config or self.config.agents.get(agent_alias)
        swap = peek.endpoint.swap_space if peek and peek.endpoint else None
        require_shm_for_offload(swap)
        async with self._start_gate:
            async with self._lock:
                # Get agent config
                if agent_config is None:
                    from ..config import require_agent

                    agent_alias, agent_config = require_agent(self.config, agent_alias)

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
                if agent_alias == "thinking":
                    os.environ["GAIUS_THINKING_PORT"] = str(port)
                    os.environ["GAIUS_VLLM_METRICS_URL"] = (
                        f"http://127.0.0.1:{port}/metrics"
                    )

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

            # Start outside the allocation lock, still exclusive vs other serves
            success = await self._start_vllm_process(proc, endpoint_config=agent_config.endpoint)

        if success:
            # Update allocation state with PID for orphan detection
            allocation.mark_active(port, pid=proc.pid)
            proc.status = ProcessStatus.HEALTHY
        elif proc.process is not None and proc.process.returncode is None:
            # Still loading (large TP). Do not FAILED/release — HealthObserver
            # must not evict a live STARTING process.
            allocation.mark_active(port, pid=proc.pid)
            proc.status = ProcessStatus.STARTING
            logger.warning(
                "Endpoint %s still STARTING after %ss (pid=%s); leaving it up",
                agent_alias,
                self._startup_timeout,
                proc.pid,
            )
        else:
            # Release resources on failure
            proc.status = ProcessStatus.FAILED
            self.resource_manager.release(agent_alias)
            self._release_port(port)
            buf = "\n".join(list(proc.stderr_buffer)[-30:] + list(proc.stdout_buffer)[-30:])
            if "out of memory" in buf.lower() or "cuda out of memory" in buf.lower():
                raise RuntimeError(
                    f"#EP.00000003.CTXFIT {agent_alias} {proc.model} "
                    f"max-model-len={proc.context_length} did not fit. "
                    "Set resources.context-length in agents.conf to the largest "
                    "value that fits 4x4090 BF16. Do not silently cap.\n"
                    f"{buf[-800:]}"
                )
            if "validation error" in buf.lower() or "unrecognized arguments" in buf.lower():
                raise RuntimeError(
                    f"#EP.00000004.VLLMARGS {agent_alias} {proc.model} "
                    f"vLLM refused to start:\n{buf[-800:]}"
                )

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
        endpoint_config: "EndpointConfig | None" = None,
    ) -> bool:
        """Start the actual vLLM subprocess.

        Args:
            proc: VLLMProcess state object
            serve_command: Optional custom command (uses default vLLM command if None)
            extra_env: Optional extra environment variables to merge
            endpoint_config: Per-endpoint settings (enforce_eager, swap_space, etc.)
        """
        from gaius.engine.config import EndpointConfig as _EndpointConfig  # noqa: F811

        # Build environment
        gpu_str = ",".join(str(g) for g in proc.gpu_ids)
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu_str

        # Merge extra environment variables if provided
        if extra_env:
            env.update(extra_env)

        # Tinybox multi-GPU: nvcc is CUDA 12.4. devenv injects Nix gcc 15
        # and its libstdc++ (needs glibc 2.38). Host Ubuntu 22.04 is 2.35.
        # JIT kernels must use host gcc-11 and must not see Nix libstdc++.
        env = _tinybox_cuda_compile_env(env)

        # Use custom serve_command if provided, otherwise build default
        if serve_command:
            cmd = serve_command
        else:
            ep = endpoint_config or _EndpointConfig()

            # Per-endpoint gpu-memory-utilization overrides global default
            gpu_mem_util = ep.gpu_memory_utilization if ep.gpu_memory_utilization else self._gpu_memory_util
            # Per-endpoint dtype overrides global default
            dtype = ep.dtype if ep.dtype else self._dtype

            # Build default vLLM command
            cmd = [
                self._binary,
                "serve",
                proc.model,
                "--port",
                str(proc.port),
                "--gpu-memory-utilization",
                str(gpu_mem_util),
                "--max-model-len",
                str(proc.context_length),
                "--max-num-seqs",
                str(proc.max_num_seqs),
                "--dtype",
                dtype,
            ]

            # Add task if not default (generate)
            if proc.task and proc.task != "generate":
                cmd.extend(["--task", proc.task])
                # Embedding models often need trust-remote-code for custom tokenizers
                cmd.append("--trust-remote-code")

            # Add tensor parallelism if needed
            if proc.tensor_parallel > 1:
                cmd.extend(["--tensor-parallel-size", str(proc.tensor_parallel)])

            # Per-endpoint flags from agents.conf
            if ep.enforce_eager:
                cmd.append("--enforce-eager")
            if ep.swap_space is not None:
                # vLLM 0.27: --swap-space removed; CPU KV overflow is
                # --kv-offloading-size (GiB).
                cmd.extend(["--kv-offloading-size", str(ep.swap_space)])
            if ep.extra_args:
                cmd.extend(ep.extra_args)

            # Add extra args from config
            cmd.extend(self._extra_args)

        proc.supports_tool_calls = "--enable-auto-tool-choice" in cmd

        logger.info(
            f"Starting vLLM for {proc.agent_alias}: "
            f"CUDA_VISIBLE_DEVICES={gpu_str} {' '.join(cmd)}"
        )
        logger.info(
            "tinybox CUDA JIT %s: CUDA_HOME=%s CC=%s NINJA=%s LD_LIBRARY_PATH=%s",
            proc.agent_alias,
            env.get("CUDA_HOME"),
            env.get("CC"),
            env.get("NINJA"),
            env.get("LD_LIBRARY_PATH"),
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
                elif "unrecognized arguments" in lower or "validation error" in lower:
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
                tail = "\n".join(list(proc.stderr_buffer)[-20:] + list(proc.stdout_buffer)[-10:])
                logger.error(
                    f"vLLM process for {proc.agent_alias} exited with code "
                    f"{proc.process.returncode}\n{tail[-1200:]}"
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

        # Debug logging for process lookup
        available_keys = list(self._processes.keys())
        logger.info(
            f"VLLMController.complete: agent_alias={request.agent_alias}, "
            f"model={request.model}, available_processes={available_keys}"
        )

        # Find endpoint for this agent/model
        proc = None
        if request.agent_alias:
            proc = self._processes.get(request.agent_alias)
            if not proc:
                logger.warning(
                    f"Process lookup failed: '{request.agent_alias}' not in {available_keys}"
                )

        if not proc:
            # Find any endpoint with this model
            for p in self._processes.values():
                if p.model == request.model and p.status == ProcessStatus.HEALTHY:
                    proc = p
                    break

        if not proc or proc.status != ProcessStatus.HEALTHY:
            # Include available processes in error for debugging
            available_info = [
                f"{k}:{p.status.value}" for k, p in self._processes.items()
            ]
            error_msg = (
                f"No healthy endpoint for agent={request.agent_alias}, model={request.model}. "
                f"Available: {available_info}. "
                f"Guru: #VLLM.00000003.NOENDPOINT"
            )
            logger.error(error_msg)
            return VLLMResponse(
                content="",
                model=request.model,
                error=error_msg,
            )

        # tools[] on an endpoint launched without --enable-auto-tool-choice is
        # a 400 from vLLM. Say so here, naming the endpoint and the flag.
        if request.extra_body.get("tools") and not proc.supports_tool_calls:
            error_msg = (
                f"Endpoint {proc.agent_alias} ({proc.model} :{proc.port}) was launched "
                "without --enable-auto-tool-choice, so it cannot serve tools[].\n"
                f"  Add --enable-auto-tool-choice and --tool-call-parser to the "
                f"{proc.agent_alias} extra-args in config/agents.conf, then restart.\n"
                "  Try: /health fix engine\n"
                "  Guru: #VLLM.00000004.NOTOOLCALL"
            )
            logger.error(error_msg)
            return VLLMResponse(content="", model=request.model, error=error_msg)

        # Build OpenAI-compatible request
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "chat_template_kwargs": {
                "enable_thinking": request.enable_thinking,
                "preserve_thinking": request.preserve_thinking,
            },
            "reasoning_effort": request.reasoning_effort,
        }
        if request.extra_body:
            payload.update(request.extra_body)

        start_time = datetime.now()

        try:
            from gaius.engine.services.cognition_buffer import thinking_read_timeout_s

            read_s = thinking_read_timeout_s(int(request.max_tokens or 0))
            response = await self._client.post(
                f"http://localhost:{proc.port}/v1/chat/completions",
                json=payload,
                timeout=httpx.Timeout(
                    connect=10.0, read=read_s, write=30.0, pool=30.0
                ),
            )
            response.raise_for_status()

            data = response.json()
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Debug log raw response structure
            logger.info(
                f"VLLMController.complete: raw response keys={list(data.keys())}, "
                f"choices_count={len(data.get('choices', []))}"
            )

            # Parse response
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            usage = data.get("usage", {})

            content = message.get("content", "") or ""
            reasoning = (
                message.get("reasoning_content")
                or message.get("reasoning")
                or ""
            )
            if not reasoning and "<think>" in content:
                # Split default Qwen think block from the answer
                end = content.find("</think>")
                if end != -1:
                    reasoning = content[: end + len("</think>")]
                    content = content[end + len("</think>") :].lstrip()
            markup = qwen_tool_call_markup(message.get("tool_calls"))
            if markup and "<tool_call>" not in content:
                content = f"{content}\n{markup}".strip() if content else markup
            # Engine-First: carry the calls STRUCTURED. Prefer the backend's
            # native tool_calls; else parse the <tool_call> markup out of content
            # (also covers the parser-off future). Markup stays in content above
            # for not-yet-migrated clients during the cutover.
            tool_calls = structured_tool_calls(message.get("tool_calls"), content)
            finish_reason = choice.get("finish_reason") or ""
            logger.info(
                f"VLLMController.complete: content_length={len(content)}, "
                f"reasoning_length={len(reasoning)}, "
                f"tool_calls={markup.count('<tool_call>')}, "
                f"finish_reason={finish_reason}, "
                f"output_tokens={usage.get('completion_tokens', 0)}, "
                f"latency_ms={latency_ms}"
            )

            proc.requests_served += 1

            return VLLMResponse(
                content=content,
                model=data.get("model", request.model),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
                reasoning_content=reasoning if isinstance(reasoning, str) else "",
                finish_reason=finish_reason,
                tool_calls=tool_calls,
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
            error_msg = format_vllm_http_error(e)
            logger.error("vLLM request error: %s", error_msg)

            return VLLMResponse(
                content="",
                model=request.model,
                latency_ms=latency_ms,
                error=error_msg,
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

    def healthy_generate_base_urls(self) -> list[tuple[str, str]]:
        """OpenAI ``/v1`` URLs of healthy generate vLLMs (not embed).

        Prefer thinking, then any other generate replica. optillm binds
        one of these instead of minting a second GPU claim.
        """
        prefer = ("thinking", "reasoning", "instruct")
        found: list[tuple[str, str]] = []
        for alias, proc in self._processes.items():
            if proc.status != ProcessStatus.HEALTHY:
                continue
            if proc.task == "embed":
                continue
            found.append((alias, proc.base_url))
        ordered: list[tuple[str, str]] = []
        for name in prefer:
            ordered.extend((a, u) for a, u in found if a == name)
        ordered.extend((a, u) for a, u in found if a not in prefer)
        return ordered

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
