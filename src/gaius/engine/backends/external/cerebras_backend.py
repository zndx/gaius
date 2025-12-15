"""Cerebras external inference backend.

Uses the Cerebras Cloud SDK for fast inference.
Per-token pricing model with separate budget tracking.

Cerebras models:
- llama-3.3-70b: Standard chat model
- zai-glm-4.6: Reasoning model (outputs chain-of-thought in 'reasoning' field)
- qwen-3-32b: Efficient mid-size model

Reasoning models (like GLM) need sufficient max_tokens to complete their
chain-of-thought before producing the final answer in 'content'.
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional

from .base import ExternalBackend, ExternalResponse

logger = logging.getLogger(__name__)


class CerebrasBackend(ExternalBackend):
    """Cerebras Cloud inference backend.

    Features:
    - Extremely fast inference (~1500 tok/s on llama-3.3-70b)
    - Per-token pricing (budget tier)
    - OpenAI-compatible API

    Environment:
        CEREBRAS_API_KEY: API key for Cerebras Cloud
    """

    # Cerebras model IDs use their own format (no slash like HuggingFace)
    # Examples: llama-3.3-70b, zai-glm-4.6, qwen-3-32b
    DEFAULT_MODEL = "zai-glm-4.6"

    # Recommended max_tokens for reasoning models to complete their chain-of-thought
    # GLM uses ~300-500 tokens for reasoning before producing final answer
    RECOMMENDED_MAX_TOKENS = 2048

    def __init__(self, model: Optional[str] = None):
        """Initialize Cerebras backend.

        Args:
            model: Model to use (default: llama-3.3-70b)
        """
        self._api_key = os.environ.get("CEREBRAS_API_KEY")
        self._model = model or self.DEFAULT_MODEL
        self._client = None

    @property
    def name(self) -> str:
        return "cerebras"

    @property
    def pricing_model(self) -> str:
        return "per_token"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self):
        """Get or create Cerebras client (lazy initialization)."""
        if self._client is None and self._api_key:
            try:
                from cerebras.cloud.sdk import Cerebras
                self._client = Cerebras(api_key=self._api_key)
            except ImportError:
                logger.warning("cerebras-cloud-sdk not installed")
                return None
        return self._client

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> ExternalResponse:
        """Execute completion via Cerebras Cloud.

        Args:
            messages: Chat messages in OpenAI format
            model: Model to use (default: zai-glm-4.6)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate (default: 2048 for reasoning models)

        Returns:
            ExternalResponse with completion result
        """
        # Use recommended default for reasoning models
        if max_tokens is None:
            max_tokens = self.RECOMMENDED_MAX_TOKENS
        if not self.is_available:
            return ExternalResponse(
                content="",
                model=model or self._model,
                provider="cerebras",
                error="CEREBRAS_API_KEY not configured",
            )

        client = self._get_client()
        if not client:
            return ExternalResponse(
                content="",
                model=model or self._model,
                provider="cerebras",
                error="Cerebras client not available (SDK not installed)",
            )

        use_model = model or self._model
        start_time = time.time()

        try:
            # Run sync client in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    messages=messages,
                    model=use_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Extract response - handle both standard content and reasoning models
            content = ""
            if response.choices:
                message = response.choices[0].message
                # Standard models use 'content', reasoning models (like GLM) use 'reasoning'
                content = message.content or ""
                if not content and hasattr(message, "reasoning") and message.reasoning:
                    content = message.reasoning
            usage = response.usage if hasattr(response, "usage") else None

            return ExternalResponse(
                content=content,
                model=use_model,
                provider="cerebras",
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Cerebras completion failed: {e}")
            return ExternalResponse(
                content="",
                model=use_model,
                provider="cerebras",
                latency_ms=latency_ms,
                error=str(e),
            )

    async def health_check(self) -> bool:
        """Check if Cerebras is healthy.

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
            logger.debug(f"Cerebras health check failed: {e}")
            return False

    def get_status(self) -> dict[str, Any]:
        """Get Cerebras backend status."""
        return {
            "name": self.name,
            "available": self.is_available,
            "pricing_model": self.pricing_model,
            "model": self._model,
            "has_api_key": bool(self._api_key),
        }
