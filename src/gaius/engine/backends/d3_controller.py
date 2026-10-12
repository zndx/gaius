"""Supervisor for ``vllm-sr/d3-flash`` replicas.

Each replica is one process of the checkpoint's ``d3_server.py`` on one
GPU (``CUDA_VISIBLE_DEVICES`` plus ``--device cuda:0``). The product vLLM
wheel is not involved. Both replicas share one Hugging Face snapshot and
load it onto their own GPU.

The side interpreter is ``GAIUS_D3_PYTHON`` or
``.devenv/d3-runtime/bin/python``. A missing interpreter is
``#EP.00000025.D3RUNTIME``. This module does not install that venv and
does not download weights until a replica is actually started.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from ..config import AgentConfig, EngineConfig
from ..resources import ResourceManager, ResourceUnavailable
from .decisions import DECISIONS_MODEL_ID
from .vllm_controller import ProcessStatus

logger = logging.getLogger(__name__)

GURU_D3RUNTIME = "#EP.00000025.D3RUNTIME"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_VENV_PYTHON = _REPO_ROOT / ".devenv" / "d3-runtime" / "bin" / "python"
_STARTUP_TIMEOUT_S = int(os.environ.get("GAIUS_D3_STARTUP_TIMEOUT", "900"))


def resolve_d3_python() -> str:
    """Path to the d3 side interpreter, or raise ``#EP.00000025.D3RUNTIME``."""
    env = (os.environ.get("GAIUS_D3_PYTHON") or "").strip()
    candidate = Path(env) if env else _DEFAULT_VENV_PYTHON
    if candidate.is_file():
        return str(candidate)
    where = env or str(_DEFAULT_VENV_PYTHON)
    raise RuntimeError(
        f"{GURU_D3RUNTIME} d3 side interpreter is missing ({where}).\n"
        "  d3-flash runs d3_server.py outside the product venv so its pins "
        "(torch 2.13, transformers 5.17) do not clobber vLLM 0.27.\n"
        "  Try: scripts/d3_runtime_venv.sh\n"
        "  Or:  export GAIUS_D3_PYTHON=/path/to/that/python"
    )


@dataclass
class D3Process:
    """One d3_server process."""

    agent_alias: str
    model: str
    port: int
    gpu_ids: list[int]
    process: Optional[asyncio.subprocess.Process] = None
    pid: Optional[int] = None
    status: ProcessStatus = ProcessStatus.STOPPED
    started_at: Optional[datetime] = None
    stdout_buffer: deque = field(default_factory=lambda: deque(maxlen=500))
    stderr_buffer: deque = field(default_factory=lambda: deque(maxlen=500))
    requests_served: int = 0
    startup_message: str = ""
    drain_tasks: list = field(default_factory=list)


class D3Controller:
    """Start and stop d3-flash replicas. One GPU, one port, one process."""

    def __init__(self, config: EngineConfig, resource_manager: ResourceManager):
        self.config = config
        self.resource_manager = resource_manager
        self._processes: dict[str, D3Process] = {}
        self._lock = asyncio.Lock()

    def processes(self) -> dict[str, D3Process]:
        return self._processes

    def get_process(self, alias: str) -> Optional[D3Process]:
        return self._processes.get(alias)

    def get_recent_logs(self, alias: str, lines: int = 50) -> list[str]:
        proc = self._processes.get(alias)
        if proc is None:
            return []
        buf = list(proc.stderr_buffer) + list(proc.stdout_buffer)
        return buf[-lines:]

    def get_startup_progress(self, alias: str) -> tuple[str, float]:
        proc = self._processes.get(alias)
        if proc is None:
            return "", 0.0
        if proc.status == ProcessStatus.HEALTHY:
            return "d3_server ready", 1.0
        if proc.status == ProcessStatus.STARTING:
            return proc.startup_message or "loading d3-flash", 0.4
        return proc.startup_message, 0.0

    async def start_endpoint(
        self,
        agent_alias: str,
        agent_config: AgentConfig,
        gpu_ids: list[int] | None = None,
    ) -> D3Process:
        """Load one replica. Raises ``ResourceUnavailable`` when the GPU is taken.

        A missing interpreter or a load that does not reach ``GET /v1/models``
        returns a ``FAILED`` process after killing the child. The caller
        surfaces ``startup_message``.
        """
        async with self._lock:
            existing = self._processes.get(agent_alias)
            if existing and existing.status in (
                ProcessStatus.HEALTHY,
                ProcessStatus.STARTING,
            ):
                logger.info("d3 replica %s already %s", agent_alias, existing.status.value)
                return existing

            wanted = [int(g) for g in (gpu_ids or [])]
            if gpu_ids is not None and len(wanted) != 1:
                proc = self._failed(
                    agent_alias,
                    agent_config,
                    wanted,
                    f"{agent_alias} needs exactly one GPU (got {wanted}). "
                    "d3_server is single-device.",
                )
                self._processes[agent_alias] = proc
                return proc
            try:
                python = resolve_d3_python()
            except RuntimeError as e:
                proc = self._failed(agent_alias, agent_config, wanted, str(e))
                self._processes[agent_alias] = proc
                return proc

            try:
                if wanted:
                    allocation = self.resource_manager.allocate_fixed(
                        agent_alias,
                        agent_config.model or DECISIONS_MODEL_ID,
                        wanted,
                        agent_config.resources.vram_gb,
                    )
                else:
                    allocation = self.resource_manager.allocate(agent_alias, agent_config)
            except ResourceUnavailable as e:
                proc = self._failed(agent_alias, agent_config, wanted, str(e))
                self._processes[agent_alias] = proc
                return proc

            if len(allocation.gpu_ids) != 1:
                self.resource_manager.release(agent_alias)
                proc = self._failed(
                    agent_alias,
                    agent_config,
                    list(allocation.gpu_ids),
                    f"{agent_alias} was given GPUs {allocation.gpu_ids}; "
                    "d3_server loads one device.",
                )
                self._processes[agent_alias] = proc
                return proc

            port = self._replica_port(agent_config)
            if not self._port_free(port):
                self.resource_manager.release(agent_alias)
                proc = self._failed(
                    agent_alias,
                    agent_config,
                    list(allocation.gpu_ids),
                    f"port {port} is not free for {agent_alias}. "
                    "d3-flash ports are 8096 and 8097, outside the vLLM scan.",
                )
                self._processes[agent_alias] = proc
                return proc

            proc = D3Process(
                agent_alias=agent_alias,
                model=agent_config.model or DECISIONS_MODEL_ID,
                port=port,
                gpu_ids=list(allocation.gpu_ids),
                status=ProcessStatus.STARTING,
                started_at=datetime.now(),
                startup_message="resolving vllm-sr/d3-flash snapshot",
            )
            self._processes[agent_alias] = proc
            gpu = allocation.gpu_ids[0]

        try:
            from ..resources.gpu_occupancy import GpuStillShared, prepare_exclusive_gpu

            # The admitted replica owns this card. The model already on
            # it comes down first. A shared card is a failed start.
            try:
                await asyncio.to_thread(
                    prepare_exclusive_gpu, int(gpu), owner=agent_alias
                )
            except GpuStillShared as e:
                self.resource_manager.release(agent_alias)
                proc.status = ProcessStatus.FAILED
                proc.startup_message = str(e)
                return proc

            snapshot = await asyncio.to_thread(_snapshot_dir)
            server = Path(snapshot) / "d3_server.py"
            if not server.is_file():
                raise RuntimeError(
                    f"{snapshot} has no d3_server.py. "
                    "The decisions runtime is the checkpoint's own server."
                )
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = str(gpu)
            prior = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = snapshot if not prior else snapshot + os.pathsep + prior
            argv = [
                python,
                str(server),
                "--model",
                snapshot,
                "--name",
                DECISIONS_MODEL_ID,
                "--device",
                "cuda:0",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
            logger.info("starting %s: %s CUDA_VISIBLE_DEVICES=%s", agent_alias, argv, gpu)
            child = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=snapshot,
            )
            proc.process = child
            proc.pid = child.pid
            proc.startup_message = "loading d3-flash"
            # Stay ALLOCATED until GET /v1/models. mark_active means HEALTHY,
            # and reconciliation restarts an unhealthy endpoint after three
            # probes. A 16 GB load is still silent then, so the restart killed
            # the replica and the retry shared the card with whoever was left.
            allocation.process_pid = child.pid
            allocation.endpoint_port = port
            proc.drain_tasks = [
                asyncio.create_task(self._drain(child.stdout, proc.stdout_buffer)),
                asyncio.create_task(self._drain(child.stderr, proc.stderr_buffer)),
            ]
            await self._wait_ready(proc)
        except Exception as e:
            logger.error("d3 replica %s failed: %s", agent_alias, e)
            await self._kill(proc)
            self.resource_manager.release(agent_alias)
            proc.status = ProcessStatus.FAILED
            proc.startup_message = str(e)
            proc.process = None
        return proc

    async def stop_endpoint(self, agent_alias: str, timeout: float = 30.0) -> bool:
        async with self._lock:
            proc = self._processes.get(agent_alias)
            if proc is None:
                return True
            proc.status = ProcessStatus.STOPPING
        await self._kill(proc, timeout=timeout)
        self.resource_manager.release(agent_alias)
        proc.status = ProcessStatus.STOPPED
        proc.process = None
        proc.pid = None
        self._processes.pop(agent_alias, None)
        logger.info("d3 replica %s stopped", agent_alias)
        return True

    def _replica_port(self, agent_config: AgentConfig) -> int:
        if agent_config.endpoint and agent_config.endpoint.port:
            return int(agent_config.endpoint.port)
        raise RuntimeError(
            f"{agent_config.alias} has no endpoint.port. "
            "d3-flash-0 uses 8096 and d3-flash-1 uses 8097."
        )

    @staticmethod
    def _port_free(port: int) -> bool:
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
                return True
        except OSError:
            return False

    @staticmethod
    def _failed(
        alias: str,
        agent_config: AgentConfig,
        gpu_ids: list[int],
        message: str,
    ) -> D3Process:
        return D3Process(
            agent_alias=alias,
            model=getattr(agent_config, "model", "") or DECISIONS_MODEL_ID,
            port=0,
            gpu_ids=gpu_ids,
            status=ProcessStatus.FAILED,
            startup_message=message,
        )

    async def _wait_ready(self, proc: D3Process) -> None:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        url = f"http://127.0.0.1:{proc.port}/v1/models"
        while time.monotonic() < deadline:
            if proc.status == ProcessStatus.STOPPING:
                raise RuntimeError(f"{proc.agent_alias} stopped while loading")
            if proc.process is not None and proc.process.returncode is not None:
                tail = "\n".join(list(proc.stderr_buffer)[-20:])
                raise RuntimeError(
                    f"{proc.agent_alias} exited {proc.process.returncode} "
                    f"before /v1/models.\n{tail}"
                )
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(url)
                if response.status_code == 200:
                    proc.status = ProcessStatus.HEALTHY
                    proc.startup_message = "d3_server ready"
                    alloc = self.resource_manager.allocations.get(proc.agent_alias)
                    if alloc is not None:
                        alloc.mark_active(proc.port, pid=proc.pid)
                    logger.info("%s healthy on :%s", proc.agent_alias, proc.port)
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
        raise RuntimeError(
            f"{proc.agent_alias} did not serve /v1/models within "
            f"{_STARTUP_TIMEOUT_S}s (GAIUS_D3_STARTUP_TIMEOUT). "
            "The process was killed."
        )

    async def _kill(self, proc: D3Process, timeout: float = 20.0) -> None:
        child = proc.process
        if child is None or child.returncode is not None:
            return
        child.terminate()
        try:
            await asyncio.wait_for(child.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            child.kill()
            await child.wait()

    @staticmethod
    async def _drain(stream: asyncio.StreamReader | None, buf: deque) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            buf.append(line.decode(errors="replace").rstrip())


def _snapshot_dir() -> str:
    from huggingface_hub import snapshot_download

    path = snapshot_download(DECISIONS_MODEL_ID)
    if not path:
        raise RuntimeError(f"snapshot_download returned nothing for {DECISIONS_MODEL_ID}")
    return path


