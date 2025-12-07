"""optillm backend controller.

Manages the optillm proxy server for prompt optimization techniques.
optillm provides various optimization strategies (COT, MOA, BON, etc.)
and routes requests to underlying vLLM endpoints.

The engine manages the optillm subprocess lifecycle, starting it on demand
and monitoring health.
"""

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import httpx

from ..config import EngineConfig, OptillmConfig

logger = logging.getLogger(__name__)


class OptillmStatus(Enum):
    """optillm process status."""

    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    FAILED = "failed"


class OptillmTechnique(Enum):
    """Available optillm optimization techniques."""

    NONE = ""  # Pass-through, no optimization
    COT_REFLECTION = "cot_reflection"  # Chain-of-thought with reflection
    BON = "bon"  # Best-of-N sampling
    MOA = "moa"  # Mixture of Agents
    PV = "pv"  # Parallel voting
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
    max_tokens: int = 2048
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
    """

    content: str
    model: str
    technique: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


class OptillmController:
    """Controller for optillm prompt optimization backend.

    Manages the optillm subprocess lifecycle, health checking, request routing,
    and technique configuration. The engine starts optillm on demand.
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

        logger.info(
            f"OptillmController initialized: {self._base_url}, "
            f"default technique: {self._default_technique.value}"
        )

    async def start(self) -> None:
        """Start the controller and optillm subprocess."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        # Check if optillm is already running externally
        if await self.health_check():
            logger.info("optillm already running externally")
            return

        # Start optillm subprocess
        await self._start_optillm_process()
        logger.info("OptillmController started")

    async def _start_optillm_process(self) -> bool:
        """Start the optillm subprocess.

        Returns:
            True if started successfully
        """
        self._status = OptillmStatus.STARTING

        # Build environment
        env = os.environ.copy()
        env["OPTILLM_API_KEY"] = self._api_key
        env["OPENAI_API_KEY"] = self._api_key
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
            logger.error(f"Python not found: {python}")
            self._status = OptillmStatus.FAILED
            return False
        except Exception as e:
            logger.error(f"Failed to start optillm: {e}")
            self._status = OptillmStatus.FAILED
            return False

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

    async def stop(self) -> None:
        """Stop the controller and optillm subprocess."""
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

        if self._client:
            await self._client.aclose()
            self._client = None

        self._healthy = False
        logger.info("OptillmController stopped")

    async def restart(self) -> bool:
        """Restart optillm subprocess.

        Returns:
            True if restart successful
        """
        if self._recovery_attempts >= self._max_recovery_attempts:
            logger.error("Max recovery attempts reached for optillm")
            return False

        self._recovery_attempts += 1
        logger.info(f"Restarting optillm (attempt {self._recovery_attempts})")

        await self.stop()
        return await self._start_optillm_process()

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
        """Complete a request through optillm.

        Args:
            request: The completion request

        Returns:
            OptillmResponse with generated content
        """
        if not self._client:
            return OptillmResponse(
                content="",
                model=request.model,
                technique=request.technique.value,
                error="Controller not started",
            )

        if not self._healthy:
            # Try health check before failing
            await self.health_check()
            if not self._healthy:
                return OptillmResponse(
                    content="",
                    model=request.model,
                    technique=request.technique.value,
                    error="optillm not healthy",
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

        start_time = datetime.now()

        try:
            response = await self._client.post(
                "/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Parse OpenAI response format
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            usage = data.get("usage", {})

            return OptillmResponse(
                content=message.get("content", ""),
                model=data.get("model", model_name),
                technique=request.technique.value,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
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

    async def complete_simple(
        self,
        prompt: str,
        model: str,
        technique: OptillmTechnique | str | None = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
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
        return {
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

    @property
    def is_healthy(self) -> bool:
        """Whether optillm is healthy."""
        return self._healthy

    @property
    def is_enabled(self) -> bool:
        """Whether optillm is enabled in config."""
        return self.optillm_config.enabled
