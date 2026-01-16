"""Bytez external inference backend.

Uses the Bytez SDK for subscription-based inference with:
- Unlimited tokens (subscription model)
- Limited to 2 concurrent requests
- GPU seat-aware model selection (1 seat = 0.5B models)
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from .base import ExternalBackend, ExternalResponse

logger = logging.getLogger(__name__)


class BytezBackend(ExternalBackend):
    """Bytez inference backend.

    Features:
    - Subscription pricing (unlimited tokens)
    - Concurrency limited to 2 active requests
    - Smaller models (7B-24B range)
    - Vendor whitelist for model selection

    Environment:
        BYTEZ_API_KEY: API key for Bytez
    """

    # Mistral-7B-Instruct for quality analysis
    # (requires 4 GPU seats - upgrade Bytez credits if needed)
    DEFAULT_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"

    # Allowed vendors for model selection
    ALLOWED_VENDORS = {"mistralai", "allenai", "Qwen"}

    # Maximum concurrent requests
    MAX_CONCURRENT = 2

    def __init__(
        self,
        model: Optional[str] = None,
        max_concurrent: int = MAX_CONCURRENT,
    ):
        """Initialize Bytez backend.

        Args:
            model: Model to use (default: mistralai/Mistral-7B-Instruct-v0.2)
            max_concurrent: Maximum concurrent requests (default: 2)
        """
        self._api_key = os.environ.get("BYTEZ_API_KEY")
        self._model = model or self.DEFAULT_MODEL
        self._max_concurrent = max_concurrent
        self._active_requests = 0
        self._lock = asyncio.Lock()
        self._sdk = None

    @property
    def name(self) -> str:
        return "bytez"

    @property
    def pricing_model(self) -> str:
        return "subscription"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    @property
    def active_requests(self) -> int:
        """Current number of active requests."""
        return self._active_requests

    @property
    def can_accept_request(self) -> bool:
        """Whether a new request can be accepted."""
        return self._active_requests < self._max_concurrent

    def _get_sdk(self):
        """Get or create Bytez SDK (lazy initialization)."""
        if self._sdk is None and self._api_key:
            try:
                from bytez import Bytez
                self._sdk = Bytez(self._api_key)
            except ImportError:
                logger.warning("bytez SDK not installed")
                return None
        return self._sdk

    def _validate_model(self, model: str) -> tuple[bool, str]:
        """Validate model against vendor whitelist.

        Args:
            model: Model identifier (vendor/model-name format)

        Returns:
            (is_valid, error_message)
        """
        if "/" not in model:
            return False, f"Invalid model format: {model} (expected vendor/model-name)"

        vendor = model.split("/")[0]
        if vendor not in self.ALLOWED_VENDORS:
            return False, f"Vendor '{vendor}' not in whitelist: {self.ALLOWED_VENDORS}"

        return True, ""

    @asynccontextmanager
    async def _acquire_slot(self):
        """Acquire a request slot (context manager for concurrency limiting)."""
        async with self._lock:
            if self._active_requests >= self._max_concurrent:
                raise RuntimeError(
                    f"Bytez concurrency limit reached ({self._max_concurrent} active requests)"
                )
            self._active_requests += 1

        try:
            yield
        finally:
            async with self._lock:
                self._active_requests = max(0, self._active_requests - 1)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ExternalResponse:
        """Execute completion via Bytez.

        Args:
            messages: Chat messages in OpenAI format
            model: Model to use (must be from allowed vendor)
            temperature: Sampling temperature (note: Bytez SDK may not support this)
            max_tokens: Maximum tokens (note: Bytez SDK may not support this)

        Returns:
            ExternalResponse with completion result
        """
        if not self.is_available:
            return ExternalResponse(
                content="",
                model=model or self._model,
                provider="bytez",
                error="BYTEZ_API_KEY not configured",
            )

        use_model = model or self._model

        # Validate model
        is_valid, error = self._validate_model(use_model)
        if not is_valid:
            return ExternalResponse(
                content="",
                model=use_model,
                provider="bytez",
                error=error,
            )

        # Check concurrency
        if not self.can_accept_request:
            return ExternalResponse(
                content="",
                model=use_model,
                provider="bytez",
                error=f"Concurrency limit reached ({self._active_requests}/{self._max_concurrent})",
            )

        sdk = self._get_sdk()
        if not sdk:
            return ExternalResponse(
                content="",
                model=use_model,
                provider="bytez",
                error="Bytez SDK not available (SDK not installed)",
            )

        start_time = time.time()

        try:
            async with self._acquire_slot():
                # Run sync SDK in thread pool
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self._sync_complete(sdk, messages, use_model),
                )

            latency_ms = int((time.time() - start_time) * 1000)

            if result.get("error"):
                return ExternalResponse(
                    content="",
                    model=use_model,
                    provider="bytez",
                    latency_ms=latency_ms,
                    error=str(result["error"]),
                )

            content = result.get("output", "")
            # Bytez SDK doesn't provide token counts directly
            # Estimate based on output length (rough approximation)
            estimated_output_tokens = len(content.split()) if content else 0

            return ExternalResponse(
                content=content,
                model=use_model,
                provider="bytez",
                output_tokens=estimated_output_tokens,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Bytez completion failed: {e}")
            return ExternalResponse(
                content="",
                model=use_model,
                provider="bytez",
                latency_ms=latency_ms,
                error=str(e),
            )

    def _sync_complete(
        self,
        sdk,
        messages: list[dict[str, str]],
        model_id: str,
    ) -> dict[str, Any]:
        """Synchronous completion wrapper for thread pool.

        Args:
            sdk: Bytez SDK instance
            messages: Chat messages
            model_id: Model identifier

        Returns:
            Dict with 'output' and 'error' keys
        """
        try:
            model = sdk.model(model_id)
            # Note: scaleUp parameter only works for models that need more seats
            # than available. We use Qwen2-0.5B which only needs 1 seat.
            result = model.run(messages)

            # Handle different output formats from Bytez SDK
            output = result.output
            if isinstance(output, dict):
                # Chat format: {'role': 'assistant', 'content': '...'}
                output = output.get("content", "")
            elif output is None:
                output = ""

            return {"output": output, "error": result.error}
        except Exception as e:
            return {"output": "", "error": str(e)}

    async def health_check(self) -> bool:
        """Check if Bytez is healthy.

        Returns:
            True if API is responsive
        """
        if not self.is_available:
            return False

        # Don't consume a slot for health check if at capacity
        if self._active_requests >= self._max_concurrent:
            # Still "healthy" but at capacity
            return True

        try:
            response = await self.complete(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return response.success
        except Exception as e:
            logger.debug(f"Bytez health check failed: {e}")
            return False

    async def list_models(self, task: str = "chat") -> list[dict[str, Any]]:
        """List available models from Bytez.

        Args:
            task: Task type filter (default: chat)

        Returns:
            List of model info dicts
        """
        if not self.is_available:
            return []

        try:
            import aiohttp
            url = f"https://api.bytez.com/models/v2/list/models?task={task}"
            headers = {"Authorization": self._api_key}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Filter by allowed vendors
                        return [
                            m for m in data
                            if m.get("id", "").split("/")[0] in self.ALLOWED_VENDORS
                        ]
                    return []
        except Exception as e:
            logger.debug(f"Failed to list Bytez models: {e}")
            return []

    def get_status(self) -> dict[str, Any]:
        """Get Bytez backend status."""
        return {
            "name": self.name,
            "available": self.is_available,
            "pricing_model": self.pricing_model,
            "model": self._model,
            "has_api_key": bool(self._api_key),
            "active_requests": self._active_requests,
            "max_concurrent": self._max_concurrent,
            "can_accept_request": self.can_accept_request,
            "allowed_vendors": list(self.ALLOWED_VENDORS),
        }
