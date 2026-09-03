"""optillm backend controller.

Manages the optillm proxy server for prompt optimization techniques.
optillm provides various optimization strategies (COT, MOA, BON, etc.)
and routes requests to underlying vLLM endpoints.

The engine manages the optillm subprocess lifecycle via gunicorn WSGI server,
providing production-ready features:
- Graceful worker reload via SIGHUP
- Dynamic worker scaling for GPU reclamation
- Runtime technique reconfiguration
"""

import asyncio
import logging
import os
import re
import signal
import subprocess
import sys
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx

from ..config import EngineConfig, OptillmConfig
from .gunicorn_config import GunicornConfigGenerator, GunicornSettings
from gaius.core.budgets import REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)

GURU_NOVLLM = "#OPT.00000004.NOVLLM"
OPTILLM_KIND = "optillm"


def pids_listening_on_port(port: int) -> set[int]:
    """PIDs with a listening TCP socket on ``port`` (IPv4/IPv6)."""
    r = subprocess.run(
        ["ss", "-ltnp"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    pids: set[int] = set()
    needle = f":{port} "
    for line in (r.stdout or "").splitlines():
        if needle not in line and not line.rstrip().endswith(f":{port}"):
            continue
        for m in re.finditer(r"pid=(\d+)", line):
            pids.add(int(m.group(1)))
    return pids


class OptillmStatus(Enum):
    """optillm process status."""

    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    RELOADING = "reloading"  # During SIGHUP reload
    SCALING = "scaling"  # During worker count change
    FAILED = "failed"


class OptillmTechnique(Enum):
    """Available optillm optimization techniques."""

    NONE = ""  # Pass-through, no optimization
    COT_REFLECTION = "cot_reflection"  # Chain-of-thought with reflection
    BON = "bon"  # Best-of-N sampling
    MOA = "moa"  # Mixture of Agents
    PV = "pvg"  # Prover-Verifier Game (upstream name; the old "pv" value was
    # unservable — optillm's known_approaches has only "pvg", and the unknown
    # prefix silently degraded to a plain pass-through)
    RE2 = "re2"  # Re-reading
    SELF_CONSISTENCY = "self_consistency"
    RSTAR = "rstar"  # R* search
    COT = "cot"  # Simple chain-of-thought
    PLANSEARCH = "plansearch"  # Plan search


@dataclass
class OptillmRequest:
    """Request to optillm backend.

    Attributes:
        messages: Chat messages in OpenAI format
        model: Base model to use (technique is prefixed)
        technique: Optimization technique to apply
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        agent_alias: Optional agent identifier for tracking
    """

    messages: list[dict[str, str]]
    model: str
    technique: OptillmTechnique = OptillmTechnique.COT_REFLECTION
    temperature: float = 0.7
    max_tokens: int = REASONING_MAX_TOKENS
    agent_alias: Optional[str] = None


@dataclass
class OptillmResponse:
    """Response from optillm backend.

    Attributes:
        content: Generated text content
        model: Model that generated response
        technique: Technique that was applied
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Request latency in milliseconds
        error: Error message if request failed
        reasoning_content: Separated model chain-of-thought when the backend
            forwards it (upstream optillm currently drops it — honest empty)
        finish_reason: "stop" | "length" from the underlying completion —
            forwarded so truncation stays visible through the proxy hop
    """

    content: str
    model: str
    technique: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None
    reasoning_content: str = ""
    finish_reason: str = ""

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


class OptillmController:
    """Controller for optillm prompt optimization backend.

    Manages the optillm subprocess lifecycle via gunicorn WSGI server,
    providing production-ready features:
    - Graceful worker reload via SIGHUP
    - Dynamic worker scaling for GPU reclamation
    - Runtime technique reconfiguration

    The engine starts optillm on demand using gunicorn as the WSGI server.
    """

    def __init__(self, config: EngineConfig):
        """Initialize optillm controller.

        Args:
            config: Engine configuration with optillm settings
        """
        self.config = config
        self.optillm_config = config.optillm

        self._base_url = self.optillm_config.base_url.rstrip("/")
        self._api_key = self.optillm_config.api_key or "gaius-local-key"
        self._timeout = self.optillm_config.timeout
        self._default_technique = OptillmTechnique(
            self.optillm_config.default_technique
        )

        # Process management
        self._process: Optional[asyncio.subprocess.Process] = None
        self._status = OptillmStatus.STOPPED
        self._pid: Optional[int] = None
        self._started_at: Optional[datetime] = None
        self._port = 8000  # Default optillm port

        self._healthy = False
        self._last_health_check: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None

        # Startup settings
        self._startup_timeout = 60  # 60 seconds to start
        self._max_recovery_attempts = 3
        self._recovery_attempts = 0

        # Gunicorn-specific settings
        self._use_gunicorn = getattr(self.optillm_config, "use_gunicorn", True)
        self._gunicorn_config: Optional[GunicornConfigGenerator] = None
        self._configured_workers = getattr(
            getattr(self.optillm_config, "gunicorn", None), "workers", 4
        )
        self._last_reload: Optional[datetime] = None
        self._reload_count = 0

        # Log buffers for progress detection
        self._stdout_buffer: deque = deque(maxlen=500)
        self._stderr_buffer: deque = deque(maxlen=500)
        self._log_reader_task: Optional[asyncio.Task] = None

        # Watchdog for crash detection and auto-restart
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_interval = 10  # seconds between liveness checks

        # vLLM heartbeat client for progress-aware idle timeout
        self._vllm_metrics_url = self.optillm_config.backend_url.rsplit("/v1", 1)[0]
        self._idle_timeout = getattr(self.optillm_config, "idle_timeout", 120)
        self._heartbeat_poll_interval = 10  # seconds between vLLM metrics polls
        self._vllm_metrics_client: Optional[httpx.AsyncClient] = None
        self._ensure_vllm: Callable[[], Awaitable[str]] | None = None
        self._bound_vllm_url = self.optillm_config.backend_url

        logger.info(
            f"OptillmController initialized: {self._base_url}, "
            f"default technique: {self._default_technique.value}, "
            f"gunicorn: {self._use_gunicorn}"
        )

    def set_vllm_ensure(self, fn: Callable[[], Awaitable[str]]) -> None:
        """Resolver: provided vLLM URL, or demand thinking via Engine."""
        self._ensure_vllm = fn

    def _admit_sentinel(self) -> None:
        from gaius.engine.sentinel_claim import (
            OPTILLM_WORKLOAD_ID,
            YkAdmitError,
            apply_and_admit,
        )

        try:
            apply_and_admit(OPTILLM_WORKLOAD_ID, OPTILLM_KIND)
        except YkAdmitError as e:
            logger.error("optillm YK admit failed: %s", e)
            raise

    def _stz_sentinel(self) -> None:
        from gaius.engine.sentinel_claim import OPTILLM_WORKLOAD_ID, delete_flow_sentinel

        delete_flow_sentinel(OPTILLM_WORKLOAD_ID)

    def _reap_foreign_listeners(self) -> None:
        """Kill gunicorn/optillm holding :8000 that this controller did not start."""
        ours = {p for p in (self._pid,) if p}
        if self._process and self._process.pid:
            ours.add(self._process.pid)
        foreign = pids_listening_on_port(self._port) - ours
        for pid in foreign:
            logger.warning(
                "reaping foreign optillm listener pid=%s on :%s", pid, self._port
            )
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
        if foreign:
            time_mod = __import__("time")
            time_mod.sleep(1.0)
            still = pids_listening_on_port(self._port) - ours
            for pid in still:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def _apply_vllm_url(self, url: str) -> None:
        self._bound_vllm_url = url
        self._vllm_metrics_url = url.rsplit("/v1", 1)[0]
        self.optillm_config.backend_url = url

    async def bind_provided_vllm(self, url: str) -> None:
        """Point gunicorn at a vLLM that is already provided (no extra GPU)."""
        if url.rstrip("/") == self._bound_vllm_url.rstrip("/"):
            return
        logger.info("optillm binding provided vLLM %s (was %s)", url, self._bound_vllm_url)
        self._apply_vllm_url(url)
        if self._vllm_metrics_client:
            await self._vllm_metrics_client.aclose()
        self._vllm_metrics_client = httpx.AsyncClient(
            base_url=self._vllm_metrics_url, timeout=5.0
        )
        if self._process is not None:
            self._recovery_attempts = 0
            await self.restart(retire_sentinel=False)

    async def start(self) -> None:
        """Admit the YK sentinel, reap orphans, start gunicorn."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        self._reap_foreign_listeners()
        await asyncio.to_thread(self._admit_sentinel)  # off-loop: admit wait must not block the engine

        if self._ensure_vllm is not None:
            try:
                url = await self._ensure_vllm()
                self._apply_vllm_url(url)
            except Exception as e:
                logger.warning(
                    "optillm: no vLLM provided yet (%s); gunicorn starts, "
                    "demand on first Complete",
                    e,
                )

        self._vllm_metrics_client = httpx.AsyncClient(
            base_url=self._vllm_metrics_url,
            timeout=5.0,
        )

        if await self.health_check() and self._pid in pids_listening_on_port(self._port):
            logger.info("optillm already running as this controller's process")
            return

        if self._use_gunicorn:
            await self._start_gunicorn_process()
        else:
            await self._start_optillm_process()
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            logger.info("optillm watchdog started")

        logger.info("OptillmController started backend=%s", self._bound_vllm_url)

    async def _start_optillm_process(self) -> bool:
        """Start the optillm subprocess.

        Returns:
            True if started successfully
        """
        self._status = OptillmStatus.STARTING

        # Build environment
        env = os.environ.copy()
        # NOTE: Do NOT set OPTILLM_API_KEY - that triggers local inference mode
        # which tries to load model tokenizers. Only set OPENAI_API_KEY for proxy mode.
        env.pop("OPTILLM_API_KEY", None)  # Remove if inherited from parent
        # Remove CEREBRAS_API_KEY - optillm checks this BEFORE OPENAI_API_KEY
        # and would create a Cerebras client instead of OpenAI client
        env.pop("CEREBRAS_API_KEY", None)
        env["OPENAI_API_KEY"] = self._api_key
        # Set backend URL for optillm to forward requests to vLLM
        # Remove conflicting OPENAI_API_BASE if set in parent environment
        env.pop("OPENAI_API_BASE", None)
        backend_url = self._bound_vllm_url
        env["OPTILLM_BASE_URL"] = backend_url
        # Keep cot_reflection's <thinking>/<reflection> scaffold in the response —
        # the reasoning trace is the product (HX hx.cot_reasoning), and optillm's
        # default returns ONLY <output>.
        env["OPTILLM_RETURN_FULL_RESPONSE"] = "true"
        # Clear PYTHONPATH to avoid Nix store conflicts
        env["PYTHONPATH"] = ""

        # Find optillm executable in same directory as Python interpreter
        python_dir = os.path.dirname(sys.executable)
        optillm_bin = os.path.join(python_dir, "optillm")

        # Fall back to direct function call if binary not found
        # Note: optillm doesn't accept --host, it binds to 0.0.0.0 by default
        if os.path.exists(optillm_bin):
            cmd = [
                optillm_bin,
                "--port",
                str(self._port),
            ]
        else:
            # Use -c with sys.argv injection for argument handling
            cmd = [
                sys.executable,
                "-c",
                f"import sys; sys.argv = ['optillm', '--port', '{self._port}']; from optillm import main; main()",
            ]

        logger.info(f"Starting optillm: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._pid = self._process.pid
            self._started_at = datetime.now()

            # Wait for healthy
            healthy = await self._wait_for_healthy()

            if healthy:
                self._status = OptillmStatus.HEALTHY
                self._recovery_attempts = 0
                logger.info(f"optillm started successfully (PID: {self._pid})")
                return True
            else:
                self._status = OptillmStatus.FAILED
                logger.error("optillm failed to become healthy")
                return False

        except FileNotFoundError:
            logger.error(f"Python not found: {sys.executable}")
            self._status = OptillmStatus.FAILED
            return False
        except Exception as e:
            logger.error(f"Failed to start optillm: {e}")
            self._status = OptillmStatus.FAILED
            return False

    async def _start_gunicorn_process(self) -> bool:
        """Start optillm via gunicorn WSGI server.

        Returns:
            True if started successfully
        """
        self._status = OptillmStatus.STARTING

        # Build environment
        env = os.environ.copy()
        # NOTE: Do NOT set OPTILLM_API_KEY - that triggers local inference mode
        # which tries to load model tokenizers. Only set OPENAI_API_KEY for proxy mode.
        env.pop("OPTILLM_API_KEY", None)  # Remove if inherited from parent
        # Remove CEREBRAS_API_KEY - optillm checks this BEFORE OPENAI_API_KEY
        # and would create a Cerebras client instead of OpenAI client
        env.pop("CEREBRAS_API_KEY", None)
        env["OPENAI_API_KEY"] = self._api_key
        # Set backend URL for optillm to forward requests to vLLM
        # Remove conflicting OPENAI_API_BASE if set in parent environment
        env.pop("OPENAI_API_BASE", None)
        backend_url = self._bound_vllm_url
        env["OPTILLM_BASE_URL"] = backend_url
        # Keep cot_reflection's <thinking>/<reflection> scaffold in the response —
        # the reasoning trace is the product (HX hx.cot_reasoning), and optillm's
        # default returns ONLY <output>.
        env["OPTILLM_RETURN_FULL_RESPONSE"] = "true"
        # Clear PYTHONPATH to avoid Nix store conflicts
        env["PYTHONPATH"] = ""

        # Get gunicorn settings from config
        gunicorn_cfg = getattr(self.optillm_config, "gunicorn", None)
        workers = getattr(gunicorn_cfg, "workers", 4) if gunicorn_cfg else 4
        threads = getattr(gunicorn_cfg, "threads", 2) if gunicorn_cfg else 2
        timeout = getattr(gunicorn_cfg, "timeout", 120) if gunicorn_cfg else 120
        config_dir = getattr(gunicorn_cfg, "config_dir", "/tmp/gaius") if gunicorn_cfg else "/tmp/gaius"

        # Create gunicorn config generator
        # Get backend URL from config (vLLM instruct endpoint)
        backend_url = self._bound_vllm_url
        settings = GunicornSettings(
            bind=f"127.0.0.1:{self._port}",
            workers=workers,
            threads=threads,
            timeout=timeout,
            graceful_timeout=30,
            optillm_api_key=self._api_key,
            optillm_approach=self._default_technique.value,
            optillm_base_url=backend_url,
            config_dir=config_dir,
        )
        self._gunicorn_config = GunicornConfigGenerator(settings, config_dir)
        self._configured_workers = workers

        # Generate config file
        config_path = self._gunicorn_config.generate()

        # Find gunicorn executable
        python_dir = os.path.dirname(sys.executable)
        gunicorn_bin = os.path.join(python_dir, "gunicorn")

        if not os.path.exists(gunicorn_bin):
            logger.error(f"gunicorn not found at {gunicorn_bin}")
            self._status = OptillmStatus.FAILED
            return False

        # Build command
        cmd = [gunicorn_bin] + self._gunicorn_config.get_command_args()

        logger.info(f"Starting optillm via gunicorn: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._pid = self._process.pid
            self._started_at = datetime.now()

            # Start log reader task
            self._log_reader_task = asyncio.create_task(self._read_logs())

            # Wait for healthy
            healthy = await self._wait_for_healthy()

            if healthy:
                self._status = OptillmStatus.HEALTHY
                self._recovery_attempts = 0
                logger.info(
                    f"optillm-gunicorn started successfully "
                    f"(PID: {self._pid}, workers: {workers})"
                )
                return True
            else:
                self._status = OptillmStatus.FAILED
                logger.error("optillm-gunicorn failed to become healthy")
                # Log last few stderr lines for debugging
                if self._stderr_buffer:
                    logger.error("Last stderr lines:")
                    for line in list(self._stderr_buffer)[-10:]:
                        logger.error(f"  {line}")
                return False

        except FileNotFoundError:
            logger.error(f"gunicorn not found: {gunicorn_bin}")
            self._status = OptillmStatus.FAILED
            return False
        except Exception as e:
            logger.error(f"Failed to start optillm-gunicorn: {e}")
            self._status = OptillmStatus.FAILED
            return False

    async def _read_logs(self) -> None:
        """Read stdout/stderr from process into buffers."""
        if not self._process:
            return

        async def read_stream(stream, buffer: deque, prefix: str):
            """Read from stream and store in buffer."""
            try:
                async for line in stream:
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    buffer.append(decoded)
                    logger.debug(f"[optillm-{prefix}] {decoded}")
            except Exception as e:
                logger.debug(f"Log reader {prefix} error: {e}")

        # Read both streams concurrently
        try:
            await asyncio.gather(
                read_stream(self._process.stdout, self._stdout_buffer, "stdout"),
                read_stream(self._process.stderr, self._stderr_buffer, "stderr"),
                return_exceptions=True,
            )
        except Exception as e:
            logger.debug(f"Log reader error: {e}")

    async def _wait_for_healthy(self) -> bool:
        """Wait for optillm to become healthy."""
        start = datetime.now()

        while (datetime.now() - start).total_seconds() < self._startup_timeout:
            # Check if process crashed
            if self._process and self._process.returncode is not None:
                logger.error(
                    f"optillm exited with code {self._process.returncode}"
                )
                return False

            # Try health check
            if await self.health_check():
                return True

            await asyncio.sleep(1)

        return False

    async def _watchdog_loop(self) -> None:
        """Monitor optillm subprocess and auto-restart on crash.

        Checks both subprocess liveness (PID returncode) and HTTP health.
        Uses existing restart() which tracks _recovery_attempts up to
        _max_recovery_attempts (3).
        """
        while self._status not in (OptillmStatus.STOPPED, OptillmStatus.STOPPING):
            try:
                if self._process and self._process.returncode is not None:
                    # Subprocess crashed — attempt auto-restart
                    logger.warning(
                        f"optillm subprocess exited (code={self._process.returncode}), "
                        f"attempting auto-restart "
                        f"(attempt {self._recovery_attempts + 1}/{self._max_recovery_attempts})"
                    )
                    self._healthy = False
                    self._status = OptillmStatus.FAILED
                    restarted = await self.restart()
                    if not restarted:
                        logger.error(
                            "optillm auto-restart failed after max attempts. "
                            "Guru Meditation: #OPT.00000001.WATCHDOG\n"
                            "  Try: /health fix optillm"
                        )
                        break  # Stop watchdog — manual intervention needed
                elif self._status == OptillmStatus.HEALTHY:
                    # Periodic HTTP liveness probe
                    if not await self.health_check():
                        logger.warning(
                            "optillm HTTP health check failed, attempting restart"
                        )
                        restarted = await self.restart()
                        if not restarted:
                            logger.error(
                                "optillm restart failed after health check failure. "
                                "Guru Meditation: #OPT.00000001.WATCHDOG\n"
                                "  Try: /health fix optillm"
                            )
                            break
            except Exception as e:
                logger.debug(f"Watchdog error: {e}")

            await asyncio.sleep(self._watchdog_interval)

        logger.info("optillm watchdog stopped")

    async def stop(self, *, retire_sentinel: bool = True) -> None:
        """Stop gunicorn. Yield / engine shutdown retires the YK Application."""
        # Cancel watchdog task
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None

        # Cancel log reader task
        if self._log_reader_task and not self._log_reader_task.done():
            self._log_reader_task.cancel()
            try:
                await self._log_reader_task
            except asyncio.CancelledError:
                pass
            self._log_reader_task = None

        if self._process:
            self._status = OptillmStatus.STOPPING
            logger.info(f"Stopping optillm (PID: {self._pid})")

            # Check if process is still running before terminating
            if self._process.returncode is None:
                try:
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        logger.warning("Force killing optillm")
                        self._process.kill()
                        await self._process.wait()
                except ProcessLookupError:
                    logger.debug("optillm process already exited")
            else:
                logger.debug(f"optillm already exited with code {self._process.returncode}")

            self._process = None
            self._pid = None
            self._status = OptillmStatus.STOPPED

        # Cleanup gunicorn config
        if self._gunicorn_config:
            self._gunicorn_config.cleanup()
            self._gunicorn_config = None

        if self._client:
            await self._client.aclose()
            self._client = None

        if self._vllm_metrics_client:
            await self._vllm_metrics_client.aclose()
            self._vllm_metrics_client = None

        self._healthy = False
        if retire_sentinel:
            await asyncio.to_thread(self._stz_sentinel)  # off-loop (kubectl delete)
        logger.info("OptillmController stopped")

    async def restart(self, *, retire_sentinel: bool = False) -> bool:
        """Restart optillm subprocess.

        Returns:
            True if restart successful
        """
        if self._recovery_attempts >= self._max_recovery_attempts:
            logger.error("Max recovery attempts reached for optillm")
            return False

        self._recovery_attempts += 1
        logger.info(f"Restarting optillm (attempt {self._recovery_attempts})")

        await self.stop(retire_sentinel=retire_sentinel)
        self._reap_foreign_listeners()
        await asyncio.to_thread(self._admit_sentinel)  # off-loop
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        self._vllm_metrics_client = httpx.AsyncClient(
            base_url=self._vllm_metrics_url,
            timeout=5.0,
        )

        if self._use_gunicorn:
            return await self._start_gunicorn_process()
        else:
            return await self._start_optillm_process()

    async def reload(self) -> bool:
        """Graceful reload via SIGHUP signal (gunicorn only).

        Reloads configuration and gracefully restarts workers.
        In-flight requests are allowed to complete.

        Returns:
            True if reload successful
        """
        if not self._use_gunicorn:
            logger.warning("reload() only works with gunicorn mode, using restart()")
            return await self.restart()

        if self._status != OptillmStatus.HEALTHY or not self._pid:
            logger.warning("Cannot reload: optillm not healthy")
            return False

        self._status = OptillmStatus.RELOADING
        logger.info(f"Sending SIGHUP to optillm-gunicorn (PID: {self._pid})")

        try:
            os.kill(self._pid, signal.SIGHUP)
            self._last_reload = datetime.now()
            self._reload_count += 1

            # Brief wait then verify health
            await asyncio.sleep(2)
            healthy = await self._wait_for_healthy()

            if healthy:
                self._status = OptillmStatus.HEALTHY
                logger.info("optillm-gunicorn reload successful")
                return True
            else:
                self._status = OptillmStatus.UNHEALTHY
                logger.error("optillm-gunicorn failed health check after reload")
                return False

        except ProcessLookupError:
            logger.error("optillm-gunicorn process not found for reload")
            self._status = OptillmStatus.FAILED
            return False
        except Exception as e:
            logger.error(f"Reload failed: {e}")
            self._status = OptillmStatus.UNHEALTHY
            return False

    async def scale_workers(self, count: int) -> bool:
        """Scale worker count (requires restart for gunicorn).

        Gunicorn SIGHUP does not change worker count - requires full restart.

        Args:
            count: New worker count

        Returns:
            True if scaling successful
        """
        if count < 1:
            logger.error(f"Invalid worker count: {count}")
            return False

        if not self._use_gunicorn:
            logger.warning("scale_workers() only works with gunicorn mode")
            return False

        if count == self._configured_workers:
            logger.info(f"Worker count already at {count}")
            return True

        self._status = OptillmStatus.SCALING
        logger.info(f"Scaling optillm-gunicorn workers: {self._configured_workers} -> {count}")

        # Update config and restart
        if self._gunicorn_config:
            self._gunicorn_config.update_workers(count)
            self._configured_workers = count

        # Full restart required for worker count change
        await self.stop()

        # Recreate client
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        success = await self._start_gunicorn_process()

        if success:
            logger.info(f"Scaled to {count} workers successfully")
        else:
            logger.error(f"Failed to scale to {count} workers")

        return success

    async def update_technique(self, technique: str) -> bool:
        """Update default technique and reload.

        Args:
            technique: New default technique (e.g., "cot_reflection", "bon")

        Returns:
            True if update successful
        """
        try:
            new_technique = OptillmTechnique(technique)
        except ValueError:
            logger.error(f"Unknown technique: {technique}")
            return False

        self._default_technique = new_technique
        logger.info(f"Updated default technique to: {technique}")

        if self._use_gunicorn and self._gunicorn_config:
            self._gunicorn_config.update_technique(technique)
            return await self.reload()

        return True

    def get_recent_logs(self, lines: int = 50) -> dict[str, list[str]]:
        """Get recent log lines from process.

        Args:
            lines: Number of lines to return

        Returns:
            Dict with stdout and stderr log lines
        """
        return {
            "stdout": list(self._stdout_buffer)[-lines:],
            "stderr": list(self._stderr_buffer)[-lines:],
        }

    async def health_check(self) -> bool:
        """Check if optillm is healthy.

        Returns:
            True if optillm is responding
        """
        if not self._client:
            self._healthy = False
            return False

        try:
            response = await self._client.get("/v1/models")
            self._healthy = response.status_code == 200
            self._last_health_check = datetime.now()

            if self._healthy:
                data = response.json()
                model_count = len(data.get("data", []))
                logger.debug(f"optillm healthy, {model_count} models available")

        except Exception as e:
            logger.warning(f"optillm health check failed: {e}")
            self._healthy = False

        return self._healthy

    async def _get_vllm_heartbeat(self) -> tuple[int, float]:
        """Poll vLLM metrics for forward progress indicators.

        Returns:
            (num_requests_running, generation_tokens_total)
            Returns (0, 0.0) if metrics unavailable.
        """
        if not self._vllm_metrics_client:
            return (0, 0.0)

        try:
            resp = await self._vllm_metrics_client.get("/metrics")
            running = 0
            tokens = 0.0

            for line in resp.text.split("\n"):
                if line.startswith("vllm:num_requests_running{"):
                    running = int(float(line.split()[-1]))
                elif line.startswith("vllm:generation_tokens_total{"):
                    tokens = float(line.split()[-1])

            return (running, tokens)
        except Exception:
            # Metrics endpoint unavailable — don't stall the request
            return (0, 0.0)

    async def _complete_with_heartbeat(
        self,
        payload: dict,
        model_name: str,
        request: OptillmRequest,
    ) -> OptillmResponse:
        """Execute completion with vLLM heartbeat monitoring.

        Runs the optillm HTTP POST concurrently with a vLLM metrics poller.
        The request is cancelled only when vLLM shows no forward progress
        (no running requests AND no new tokens) for idle_timeout seconds.

        Guru Meditation: #OPT.00000010.STALLED
        """
        import time

        start_time = datetime.now()
        start_mono = time.monotonic()
        idle_timeout = self._idle_timeout
        poll_interval = self._heartbeat_poll_interval

        # Snapshot vLLM baseline before request
        _, baseline_tokens = await self._get_vllm_heartbeat()
        last_progress_mono = start_mono
        last_token_count = baseline_tokens

        # Start the HTTP POST as a background task
        post_task = asyncio.create_task(
            self._client.post("/v1/chat/completions", json=payload)  # type: ignore[union-attr]
        )

        try:
            while not post_task.done():
                # Wait for either: task completion or next poll interval
                done, _ = await asyncio.wait({post_task}, timeout=poll_interval)

                if done:
                    break

                # Poll vLLM heartbeat
                now = time.monotonic()
                elapsed = now - start_mono
                running, current_tokens = await self._get_vllm_heartbeat()

                # vLLM RESTARTED / became unreachable mid-request: the cumulative
                # generation_tokens_total went BACKWARD (a reset), or metrics went
                # unavailable — _get_vllm_heartbeat then returns 0. This is NOT a
                # stall; the backend (thinking) died under us. Fail FAST and
                # accurately so the caller can re-ensure the vLLM and retry, instead
                # of waiting out idle_timeout and mislabeling it #OPT.STALLED with a
                # negative "tokens generated" (the -99289 artifact).
                if last_token_count > 0 and current_tokens < last_token_count:
                    logger.error(
                        f"optillm: vLLM restarted/unreachable mid-request "
                        f"(#OPT.00000011.VLLMRESTART): tokens "
                        f"{last_token_count:.0f} -> {current_tokens:.0f} after "
                        f"{elapsed:.0f}s"
                    )
                    post_task.cancel()
                    try:
                        await post_task
                    except asyncio.CancelledError:
                        pass
                    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    return OptillmResponse(
                        content="",
                        model=model_name,
                        technique=request.technique.value,
                        latency_ms=latency_ms,
                        error=(
                            "Guru Meditation: #OPT.00000011.VLLMRESTART — the vLLM "
                            "(thinking) restarted or became unreachable mid-request "
                            f"after {elapsed:.0f}s. Retry once it is HEALTHY.\n"
                            "  Try: /health fix endpoints"
                        ),
                    )

                if current_tokens > last_token_count:
                    # Token generation progressing
                    tokens_delta = current_tokens - last_token_count
                    tokens_total = current_tokens - baseline_tokens
                    logger.info(
                        f"optillm heartbeat: +{tokens_delta:.0f} tokens "
                        f"(total: {tokens_total:.0f}, elapsed: {elapsed:.0f}s)"
                    )
                    last_progress_mono = now
                    last_token_count = current_tokens
                elif running > 0:
                    # Request in vLLM pipeline (maybe prompt processing)
                    logger.debug(
                        f"optillm heartbeat: {running} running in vLLM, "
                        f"elapsed: {elapsed:.0f}s"
                    )
                    last_progress_mono = now  # Activity = progress
                else:
                    idle_seconds = now - last_progress_mono
                    if idle_seconds > idle_timeout:
                        # No running requests AND no token progress = stalled
                        tokens_total = current_tokens - baseline_tokens
                        logger.error(
                            f"optillm stalled (#OPT.00000010.STALLED): "
                            f"no vLLM progress for {idle_seconds:.0f}s "
                            f"(idle_timeout={idle_timeout}s, "
                            f"tokens_generated={tokens_total:.0f})"
                        )
                        post_task.cancel()
                        try:
                            await post_task
                        except asyncio.CancelledError:
                            pass

                        latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                        return OptillmResponse(
                            content="",
                            model=model_name,
                            technique=request.technique.value,
                            latency_ms=latency_ms,
                            error=(
                                f"Guru Meditation: #OPT.00000010.STALLED — "
                                f"vLLM generation stalled for {idle_seconds:.0f}s "
                                f"with {tokens_total:.0f} tokens generated. "
                                f"Try: /health fix optillm"
                            ),
                        )
                    elif idle_seconds > 30:
                        # Warn but don't kill yet
                        logger.warning(
                            f"optillm heartbeat: idle {idle_seconds:.0f}s, "
                            f"no vLLM activity (timeout at {idle_timeout}s)"
                        )

            # POST completed — parse response
            response = post_task.result()
            response.raise_for_status()

            data = response.json()
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            tokens_total = last_token_count - baseline_tokens

            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            usage = data.get("usage", {})

            logger.info(
                f"optillm complete: {latency_ms}ms, "
                f"vLLM tokens generated: {tokens_total:.0f}"
            )

            return OptillmResponse(
                content=message.get("content", ""),
                model=data.get("model", model_name),
                technique=request.technique.value,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
                # Forward what the backend gives (upstream optillm drops
                # reasoning_content today — empty is honest, never fabricated);
                # finish_reason keeps truncation visible through the proxy.
                reasoning_content=message.get("reasoning_content") or "",
                finish_reason=choice.get("finish_reason") or "",
            )

        except httpx.HTTPStatusError as e:
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"optillm request failed: {error_msg}")
            return OptillmResponse(
                content="",
                model=model_name,
                technique=request.technique.value,
                latency_ms=latency_ms,
                error=error_msg,
            )

        except asyncio.CancelledError:
            raise  # Don't swallow cancellation

        except Exception as e:
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.error(f"optillm request error: {e}")
            return OptillmResponse(
                content="",
                model=model_name,
                technique=request.technique.value,
                latency_ms=latency_ms,
                error=str(e),
            )

    def _build_model_name(
        self, base_model: str, technique: OptillmTechnique
    ) -> str:
        """Build optillm model name with technique prefix.

        optillm uses format: {technique}-{model}
        e.g., "cot_reflection-Qwen/Qwen3-Coder-30B-A3B-Instruct"
        """
        if technique == OptillmTechnique.NONE:
            return base_model
        return f"{technique.value}-{base_model}"

    async def complete(
        self, request: OptillmRequest
    ) -> OptillmResponse:
        """Complete a request through optillm with progress-aware idle timeout.

        Uses vLLM metrics heartbeat monitoring instead of a wall-clock timeout.
        The request is cancelled only if vLLM shows no forward progress
        (no running requests AND no new tokens) for idle_timeout seconds.

        Args:
            request: The completion request

        Returns:
            OptillmResponse with generated content
        """
        if not self._client:
            await self.start()
        if not self._client:
            return OptillmResponse(
                content="",
                model=request.model,
                technique=request.technique.value,
                error="Guru Meditation: #OPT.00000002.NOTSTARTED — optillm controller not started. Try: /health fix optillm",
            )

        if not self._healthy:
            await self.health_check()
            if not self._healthy:
                self._recovery_attempts = 0
                self._reap_foreign_listeners()
                if not await self.restart():
                    return OptillmResponse(
                        content="",
                        model=request.model,
                        technique=request.technique.value,
                        error="Guru Meditation: #OPT.00000003.UNHEALTHY — optillm not healthy. Try: /health fix optillm",
                    )

        if self._ensure_vllm is not None:
            try:
                url = await self._ensure_vllm()
                await self.bind_provided_vllm(url)
            except Exception as e:
                return OptillmResponse(
                    content="",
                    model=request.model,
                    technique=request.technique.value,
                    error=(
                        f"Guru Meditation: {GURU_NOVLLM} — no vLLM provided "
                        f"and demand failed: {e}\n"
                        "  Try: /health fix endpoints"
                    ),
                )

        # Build model name with technique prefix
        model_name = self._build_model_name(request.model, request.technique)

        # Build OpenAI-compatible request
        payload = {
            "model": model_name,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        return await self._complete_with_heartbeat(payload, model_name, request)

    async def complete_simple(
        self,
        prompt: str,
        model: str,
        technique: OptillmTechnique | str | None = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = REASONING_MAX_TOKENS,
    ) -> OptillmResponse:
        """Convenience method for simple completions.

        Args:
            prompt: User prompt
            model: Base model to use
            technique: Optimization technique (default from config)
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens

        Returns:
            OptillmResponse
        """
        # Resolve technique
        if technique is None:
            tech = self._default_technique
        elif isinstance(technique, str):
            try:
                tech = OptillmTechnique(technique)
            except ValueError:
                tech = OptillmTechnique.NONE
        else:
            tech = technique

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request = OptillmRequest(
            messages=messages,
            model=model,
            technique=tech,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return await self.complete(request)

    def get_status(self) -> dict[str, Any]:
        """Get controller status.

        Returns:
            Status dict with health and configuration
        """
        status = {
            "enabled": self.optillm_config.enabled,
            "healthy": self._healthy,
            "status": self._status.value,
            "pid": self._pid,
            "port": self._port,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "base_url": self._base_url,
            "default_technique": self._default_technique.value,
            "timeout": self._timeout,
            "last_health_check": (
                self._last_health_check.isoformat()
                if self._last_health_check
                else None
            ),
            "recovery_attempts": self._recovery_attempts,
            "max_recovery_attempts": self._max_recovery_attempts,
            "available_techniques": [t.value for t in OptillmTechnique if t.value],
        }

        # Add gunicorn-specific status
        status["gunicorn"] = {
            "enabled": self._use_gunicorn,
            "workers": self._configured_workers,
            "reload_count": self._reload_count,
            "last_reload": (
                self._last_reload.isoformat() if self._last_reload else None
            ),
        }

        if self._gunicorn_config:
            status["gunicorn"]["config"] = self._gunicorn_config.get_status()

        return status

    @property
    def is_healthy(self) -> bool:
        """Whether optillm is healthy."""
        return self._healthy

    @property
    def is_enabled(self) -> bool:
        """Whether optillm is enabled in config."""
        return self.optillm_config.enabled
