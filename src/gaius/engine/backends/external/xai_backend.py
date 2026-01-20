"""XAI (Grok) external inference backend.

Uses the XAI API for Grok-2 inference.
Per-token pricing model with separate budget tracking.
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional

from .base import ExternalBackend, ExternalResponse, ToolCall

logger = logging.getLogger(__name__)


class XAIBackend(ExternalBackend):
    """XAI Grok inference backend.

    Features:
    - Grok 4.1 Fast: 2M context window, optimized for agentic workflows
    - Per-token pricing ($0.20/M input, $0.50/M output)
    - OpenAI-compatible API

    Model variants:
    - grok-4-1-fast: Default, 2M context, reasoning disabled
    - grok-4-1-fast-reasoning: With chain-of-thought reasoning enabled
    - grok-3: Legacy 131K context model

    Environment:
        XAI_API_KEY: API key for XAI
    """

    # Grok 4.1 Fast: 2M context, 16K max output, 25x cheaper than Grok-3
    DEFAULT_MODEL = "grok-4-1-fast"
    API_BASE = "https://api.x.ai/v1"

    # Recommended max_tokens for synthesis (Grok 4.1 supports up to 16K output)
    RECOMMENDED_MAX_TOKENS = 16384

    def __init__(self, model: Optional[str] = None):
        """Initialize XAI backend.

        Args:
            model: Model to use (default: grok-4-1-fast)
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
            **kwargs: Additional parameters including:
                - tools: List of tool definitions for function calling
                - tool_choice: How to select tools ("auto", "none", or specific)

        Returns:
            ExternalResponse with completion result (may include tool_calls)
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

        # Extract tool calling parameters from kwargs
        tools = kwargs.get("tools")
        tool_choice = kwargs.get("tool_choice", "auto")

        # Retry configuration for transient errors (502, 503, 429)
        max_retries = 3
        retry_delay = 2.0  # Initial delay in seconds

        try:
            import httpx

            last_error: Exception | None = None
            for attempt in range(max_retries):
                try:
                    # Build request payload
                    request_json: dict[str, Any] = {
                        "model": use_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }

                    # Add tools if provided (OpenAI-compatible function calling)
                    if tools:
                        request_json["tools"] = tools
                        request_json["tool_choice"] = tool_choice

                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            f"{self.API_BASE}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self._api_key}",
                                "Content-Type": "application/json",
                            },
                            json=request_json,
                            timeout=120.0,  # Increased for large context
                        )

                        # Check for retryable status codes
                        if response.status_code in (429, 502, 503, 504):
                            last_error = httpx.HTTPStatusError(
                                f"Server error '{response.status_code}'",
                                request=response.request,
                                response=response,
                            )
                            if attempt < max_retries - 1:
                                delay = retry_delay * (2 ** attempt)  # Exponential backoff
                                logger.warning(
                                    f"XAI transient error {response.status_code}, "
                                    f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})"
                                )
                                await asyncio.sleep(delay)
                                continue

                        response.raise_for_status()
                        data = response.json()
                        break  # Success - exit retry loop

                except httpx.HTTPStatusError as e:
                    last_error = e
                    if e.response.status_code in (429, 502, 503, 504) and attempt < max_retries - 1:
                        delay = retry_delay * (2 ** attempt)
                        logger.warning(
                            f"XAI transient error {e.response.status_code}, "
                            f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise
            else:
                # All retries exhausted
                if last_error:
                    raise last_error

            latency_ms = int((time.time() - start_time) * 1000)

            # Extract response
            content = ""
            finish_reason = None
            tool_calls_list: list[ToolCall] | None = None

            if data.get("choices"):
                choice = data["choices"][0]
                message = choice.get("message", {})
                content = message.get("content") or ""
                finish_reason = choice.get("finish_reason")

                # Extract tool calls if present (OpenAI function calling format)
                raw_tool_calls = message.get("tool_calls")
                if raw_tool_calls:
                    tool_calls_list = []
                    for tc in raw_tool_calls:
                        tool_calls_list.append(
                            ToolCall(
                                id=tc.get("id", ""),
                                name=tc.get("function", {}).get("name", ""),
                                arguments=tc.get("function", {}).get("arguments", "{}"),
                            )
                        )
                    logger.debug(
                        f"XAI returned {len(tool_calls_list)} tool calls: "
                        f"{[tc.name for tc in tool_calls_list]}"
                    )

            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            # Check for truncation (finish_reason == "length")
            is_truncated = finish_reason == "length"
            if is_truncated:
                logger.warning(
                    f"XAI response truncated: model={use_model}, "
                    f"output_tokens={output_tokens}, finish_reason={finish_reason}"
                )

            # Record telemetry for token tracking
            try:
                from ...metrics import record_inference, EngineMetrics
                record_inference(
                    model=use_model,
                    latency_ms=latency_ms,
                    tokens_in=input_tokens,
                    tokens_out=output_tokens,
                    success=True,
                    provider="xai",
                )
                # Record truncation as an LLM error for Observe panel visibility
                if is_truncated:
                    EngineMetrics.get_instance().record_error("llm_truncated")
                    # Also record with attributes for investigation
                    EngineMetrics.get_instance()._inference_errors.add(
                        1, {"model": use_model, "provider": "xai", "reason": "truncated"}
                    )
            except Exception as e:
                logger.debug(f"Failed to record telemetry: {e}")

            return ExternalResponse(
                content=content,
                model=use_model,
                provider="xai",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
                tool_calls=tool_calls_list,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"XAI completion failed: {e}")

            # Record failed request telemetry
            try:
                from ...metrics import record_inference
                record_inference(
                    model=use_model,
                    latency_ms=latency_ms,
                    success=False,
                    provider="xai",
                )
            except Exception:
                pass  # Don't fail on telemetry errors

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
