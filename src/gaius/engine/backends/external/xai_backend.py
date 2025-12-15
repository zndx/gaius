"""XAI (Grok) external inference backend.

Uses the XAI API for Grok-2 inference.
Per-token pricing model with separate budget tracking.
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional

from .base import ExternalBackend, ExternalResponse

logger = logging.getLogger(__name__)


class XAIBackend(ExternalBackend):
    """XAI Grok inference backend.

    Features:
    - Grok-2 frontier model
    - Per-token pricing (budget tier)
    - OpenAI-compatible API

    Environment:
        XAI_API_KEY: API key for XAI
    """

    DEFAULT_MODEL = "grok-3"
    API_BASE = "https://api.x.ai/v1"

    def __init__(self, model: Optional[str] = None):
        """Initialize XAI backend.

        Args:
            model: Model to use (default: grok-2-latest)
        """
        self._api_key = os.environ.get("XAI_API_KEY")
        self._model = model or self.DEFAULT_MODEL
        self._client = None

    @property
    def name(self) -> str:
        return "xai"

    @property
    def pricing_model(self) -> str:
        return "per_token"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ExternalResponse:
        """Execute completion via XAI API.

        Args:
            messages: Chat messages in OpenAI format
            model: Model to use (default: grok-2-latest)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            ExternalResponse with completion result
        """
        if not self.is_available:
            return ExternalResponse(
                content="",
                model=model or self._model,
                provider="xai",
                error="XAI_API_KEY not configured",
            )

        use_model = model or self._model
        start_time = time.time()

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.API_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": use_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=60.0,
                )

                response.raise_for_status()
                data = response.json()

            latency_ms = int((time.time() - start_time) * 1000)

            # Extract response
            content = data["choices"][0]["message"]["content"] if data.get("choices") else ""
            usage = data.get("usage", {})

            return ExternalResponse(
                content=content,
                model=use_model,
                provider="xai",
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"XAI completion failed: {e}")
            return ExternalResponse(
                content="",
                model=use_model,
                provider="xai",
                latency_ms=latency_ms,
                error=str(e),
            )

    async def health_check(self) -> bool:
        """Check if XAI is healthy.

        Returns:
            True if API is responsive
        """
        if not self.is_available:
            return False

        try:
            # Simple health check with minimal tokens
            response = await self.complete(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return response.success
        except Exception as e:
            logger.debug(f"XAI health check failed: {e}")
            return False

    def get_status(self) -> dict[str, Any]:
        """Get XAI backend status."""
        return {
            "name": self.name,
            "available": self.is_available,
            "pricing_model": self.pricing_model,
            "model": self._model,
            "has_api_key": bool(self._api_key),
            "api_base": self.API_BASE,
        }
