"""Exo/MLX backend controller for Apple Silicon inference.

Manages inference requests to the exo OpenAI-compatible API for MLX models.
Exo process itself is managed by devenv (not by this controller).

Key differences from VLLMController:
- Process lifecycle managed externally (devenv)
- Uses unified memory instead of discrete GPUs
- TINYBOX_PASSTHROUGH: Routes to vLLM on Linux for testing MLX code paths

Guru Meditation Codes:
- #EXO.00000001.UNREACHABLE - Exo API not reachable
- #EXO.00000002.TIMEOUT - Request timeout
- #EXO.00000003.MODELNOTFOUND - Requested model not available
- #EXO.00000004.PASSTHROUGH - Using TINYBOX_PASSTHROUGH to vLLM
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import httpx

from ..config import AgentConfig, EngineConfig, MLXConfig
from ..metrics import EngineMetrics

logger = logging.getLogger(__name__)


class ExoStatus(Enum):
    """Exo endpoint status."""

    UNKNOWN = "unknown"  # Not yet checked
    HEALTHY = "healthy"  # API responding
    UNHEALTHY = "unhealthy"  # API not responding
    PASSTHROUGH = "passthrough"  # Using vLLM passthrough on Tinybox


@dataclass
class ExoEndpointInfo:
    """Information about the exo endpoint."""

    base_url: str
    status: ExoStatus = ExoStatus.UNKNOWN
    last_health_check: Optional[datetime] = None
    available_models: list[str] = field(default_factory=list)
    consecutive_failures: int = 0
    requests_served: int = 0

    @property
    def is_healthy(self) -> bool:
        """Check if endpoint is healthy or in passthrough mode."""
        return self.status in (ExoStatus.HEALTHY, ExoStatus.PASSTHROUGH)


@dataclass
class ExoRequest:
    """Request to exo backend.

    Attributes:
        messages: Chat messages in OpenAI format
        model: Model identifier (mlx-community format)
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
class ExoResponse:
    """Response from exo backend.

    Attributes:
        content: Generated text content
        model: Model that generated response
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Request latency in milliseconds
        error: Error message if request failed
        passthrough: Whether vLLM passthrough was used
    """

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None
    passthrough: bool = False

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


class ExoController:
    """Controller for exo/MLX inference backend.

    Communicates with exo's OpenAI-compatible API for Apple Silicon inference.
    Supports TINYBOX_PASSTHROUGH for testing MLX routing on CUDA hardware.

    Architecture:
    - Exo process managed by devenv (not this controller)
    - Controller handles HTTP requests to exo API
    - Health checks via /v1/models endpoint
    - Optional passthrough to vLLM for Tinybox testing
    """

    # Health check settings
    HEALTH_CHECK_INTERVAL = 30  # seconds
    HEALTH_CHECK_TIMEOUT = 5  # seconds
    MAX_CONSECUTIVE_FAILURES = 3
    REQUEST_TIMEOUT = 120  # seconds

    def __init__(
        self,
        config: EngineConfig,
        vllm_controller: Optional[Any] = None,  # Avoid circular import
    ):
        """Initialize exo controller.

        Args:
            config: Engine configuration with MLX settings
            vllm_controller: Optional VLLMController for passthrough mode
        """
        self.config = config
        self.mlx_config = config.mlx
        self._vllm = vllm_controller

        # Determine base URL
        self.base_url = self.mlx_config.base_url

        # Check for passthrough mode
        self.passthrough_enabled = config.platform.tinybox_passthrough
        if self.passthrough_enabled:
            logger.warning(
                "TINYBOX_PASSTHROUGH enabled: MLX requests will route to vLLM. "
                "Guru: #EXO.00000004.PASSTHROUGH"
            )

        # Endpoint state
        self.endpoint = ExoEndpointInfo(base_url=self.base_url)
        if self.passthrough_enabled:
            self.endpoint.status = ExoStatus.PASSTHROUGH

        # HTTP client (lazy init)
        self._client: Optional[httpx.AsyncClient] = None

        # Health check task
        self._health_task: Optional[asyncio.Task] = None
        self._running = False

        logger.info(
            f"ExoController initialized: base_url={self.base_url}, "
            f"passthrough={self.passthrough_enabled}"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.REQUEST_TIMEOUT),
                limits=httpx.Limits(max_connections=10),
            )
        return self._client

    async def start(self) -> None:
        """Start the controller and begin health monitoring."""
        if self._running:
            return

        self._running = True

        # Initial health check
        if not self.passthrough_enabled:
            await self._check_health()

        # Start background health monitoring
        self._health_task = asyncio.create_task(self._health_monitor())

        logger.info("ExoController started")

    async def stop(self) -> None:
        """Stop the controller and clean up resources."""
        self._running = False

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.aclose()
            self._client = None

        logger.info("ExoController stopped")

    async def _health_monitor(self) -> None:
        """Background task to monitor exo health."""
        while self._running:
            try:
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                if not self.passthrough_enabled:
                    await self._check_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Health monitor error: {e}")

    async def _check_health(self) -> bool:
        """Check if exo endpoint is healthy.

        Returns:
            True if healthy, False otherwise
        """
        if self.passthrough_enabled:
            self.endpoint.status = ExoStatus.PASSTHROUGH
            return True

        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/models",
                timeout=self.HEALTH_CHECK_TIMEOUT,
            )

            self.endpoint.last_health_check = datetime.now()

            if response.status_code == 200:
                data = response.json()
                # Extract model IDs from OpenAI format response
                models = data.get("data", [])
                self.endpoint.available_models = [
                    m.get("id", "") for m in models if isinstance(m, dict)
                ]
                self.endpoint.status = ExoStatus.HEALTHY
                self.endpoint.consecutive_failures = 0
                logger.debug(
                    f"Exo health check passed: {len(self.endpoint.available_models)} models"
                )
                return True
            else:
                self.endpoint.consecutive_failures += 1
                if self.endpoint.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                    self.endpoint.status = ExoStatus.UNHEALTHY
                    logger.warning(
                        f"Exo unhealthy after {self.endpoint.consecutive_failures} failures. "
                        "Guru: #EXO.00000001.UNREACHABLE"
                    )
                return False

        except httpx.TimeoutException:
            self.endpoint.consecutive_failures += 1
            if self.endpoint.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                self.endpoint.status = ExoStatus.UNHEALTHY
            logger.warning("Exo health check timeout. Guru: #EXO.00000002.TIMEOUT")
            return False

        except Exception as e:
            self.endpoint.consecutive_failures += 1
            if self.endpoint.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                self.endpoint.status = ExoStatus.UNHEALTHY
            logger.warning(f"Exo health check failed: {e}. Guru: #EXO.00000001.UNREACHABLE")
            return False

    async def complete(self, request: ExoRequest) -> ExoResponse:
        """Execute a completion request.

        Routes to exo API or vLLM passthrough depending on configuration.

        Args:
            request: The completion request

        Returns:
            ExoResponse with completion result
        """
        start_time = time.time()

        # Passthrough mode: route to vLLM
        if self.passthrough_enabled:
            return await self._passthrough_to_vllm(request)

        # Check endpoint health
        if self.endpoint.status == ExoStatus.UNHEALTHY:
            # Try one more health check
            if not await self._check_health():
                return ExoResponse(
                    content="",
                    model=request.model,
                    error="Exo endpoint unhealthy. Guru: #EXO.00000001.UNREACHABLE",
                )

        try:
            client = await self._get_client()

            # Build request payload (OpenAI format)
            payload = {
                "model": request.model,
                "messages": request.messages,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            }

            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                data = response.json()

                # Parse OpenAI format response
                choices = data.get("choices", [])
                content = ""
                if choices:
                    message = choices[0].get("message", {})
                    content = message.get("content", "")

                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)

                self.endpoint.requests_served += 1

                # Record metrics
                self._record_metrics(
                    request.model,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    success=True,
                )

                return ExoResponse(
                    content=content,
                    model=data.get("model", request.model),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                )

            elif response.status_code == 404:
                return ExoResponse(
                    content="",
                    model=request.model,
                    latency_ms=latency_ms,
                    error=f"Model not found: {request.model}. Guru: #EXO.00000003.MODELNOTFOUND",
                )
            else:
                error_text = response.text[:200] if response.text else "Unknown error"
                return ExoResponse(
                    content="",
                    model=request.model,
                    latency_ms=latency_ms,
                    error=f"Exo API error ({response.status_code}): {error_text}",
                )

        except httpx.TimeoutException:
            latency_ms = int((time.time() - start_time) * 1000)
            self._record_metrics(request.model, latency_ms, 0, 0, success=False)
            return ExoResponse(
                content="",
                model=request.model,
                latency_ms=latency_ms,
                error="Request timeout. Guru: #EXO.00000002.TIMEOUT",
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._record_metrics(request.model, latency_ms, 0, 0, success=False)
            logger.error(f"Exo completion error: {e}")
            return ExoResponse(
                content="",
                model=request.model,
                latency_ms=latency_ms,
                error=f"Completion failed: {str(e)}",
            )

    async def _passthrough_to_vllm(self, request: ExoRequest) -> ExoResponse:
        """Route request to vLLM when in passthrough mode.

        Used on Tinybox to test MLX code paths without Apple Silicon.

        Args:
            request: The exo request to pass through

        Returns:
            ExoResponse (converted from vLLM response)
        """
        if not self._vllm:
            return ExoResponse(
                content="",
                model=request.model,
                error="TINYBOX_PASSTHROUGH enabled but VLLMController not available",
                passthrough=True,
            )

        start_time = time.time()

        try:
            # Import here to avoid circular dependency
            from .vllm_controller import VLLMRequest

            # Map MLX model to vLLM model
            # For passthrough, we use a mapping or default model
            vllm_model = self._map_mlx_to_vllm_model(request.model)

            vllm_request = VLLMRequest(
                messages=request.messages,
                model=vllm_model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                agent_alias=request.agent_alias,
            )

            # Find a healthy vLLM endpoint for the mapped model
            # Default to "fast" agent if available
            target_agent = request.agent_alias or "fast"
            vllm_response = await self._vllm.complete(vllm_request, target_agent)

            latency_ms = int((time.time() - start_time) * 1000)

            return ExoResponse(
                content=vllm_response.content,
                model=request.model,  # Report original MLX model
                input_tokens=vllm_response.input_tokens,
                output_tokens=vllm_response.output_tokens,
                latency_ms=latency_ms,
                error=vllm_response.error,
                passthrough=True,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Passthrough to vLLM failed: {e}")
            return ExoResponse(
                content="",
                model=request.model,
                latency_ms=latency_ms,
                error=f"Passthrough failed: {str(e)}",
                passthrough=True,
            )

    def _map_mlx_to_vllm_model(self, mlx_model: str) -> str:
        """Map MLX model name to equivalent vLLM model.

        For passthrough testing, we map MLX community models to
        their HuggingFace equivalents that vLLM can run.

        Args:
            mlx_model: MLX model name (e.g., "mlx-community/Qwen2.5-7B-Instruct-4bit")

        Returns:
            Equivalent model name for vLLM
        """
        # Model mapping for passthrough
        model_map = {
            "mlx-community/Qwen2.5-7B-Instruct-4bit": "Qwen/Qwen2.5-7B-Instruct",
            "mlx-community/Qwen2.5-3B-Instruct-4bit": "Qwen/Qwen2.5-3B-Instruct",
            "mlx-community/Mistral-Small-3.1-24B-Instruct-2503-4bit": "mistralai/Mistral-7B-Instruct-v0.3",
            "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit": "Qwen/Qwen2.5-7B-Instruct",
        }

        return model_map.get(mlx_model, "mistralai/Mistral-7B-Instruct-v0.3")

    def _record_metrics(
        self,
        model: str,
        latency_ms: int,
        input_tokens: int,
        output_tokens: int,
        success: bool,
    ) -> None:
        """Record inference metrics."""
        try:
            metrics = EngineMetrics.get_instance()
            metrics.record_inference(
                model=model,
                latency_ms=latency_ms,
                tokens=input_tokens + output_tokens,
                success=success,
            )
        except Exception as e:
            logger.debug(f"Failed to record metrics: {e}")

    def get_status(self) -> dict[str, Any]:
        """Get controller status for health reporting.

        Returns:
            Status dictionary
        """
        return {
            "status": self.endpoint.status.value,
            "base_url": self.base_url,
            "passthrough_enabled": self.passthrough_enabled,
            "available_models": self.endpoint.available_models,
            "requests_served": self.endpoint.requests_served,
            "consecutive_failures": self.endpoint.consecutive_failures,
            "last_health_check": (
                self.endpoint.last_health_check.isoformat()
                if self.endpoint.last_health_check
                else None
            ),
        }

    async def health_check(self) -> bool:
        """Public health check method.

        Returns:
            True if healthy, False otherwise
        """
        return await self._check_health()

    def is_model_available(self, model: str) -> bool:
        """Check if a specific model is available.

        Args:
            model: Model identifier to check

        Returns:
            True if model is available
        """
        if self.passthrough_enabled:
            return True  # Passthrough always "has" models

        return model in self.endpoint.available_models
