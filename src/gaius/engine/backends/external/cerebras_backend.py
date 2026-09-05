"""Cerebras external inference backend.

Uses the Cerebras Cloud SDK for fast inference.
Per-token pricing model with separate budget tracking.

Cerebras models:
- llama-3.3-70b: Standard chat model
- zai-glm-4.7: Reasoning model (outputs chain-of-thought in 'reasoning' field)
- qwen-3-32b: Efficient mid-size model

GLM 4.7 notes:
- Reasoning is enabled by default (chain-of-thought in 'reasoning' field)
- Supports structured outputs and tool calling with strict: true
- Use clear_thinking=false for agentic workflows where past reasoning informs
  future tool calls (defaults to true, which excludes previous thinking)

GLM 4.7 quirks (from migration guide):
- REQUIRES a non-trivial system message for structured outputs to populate 'content'
- Without system message, 'content' is None and only 'reasoning' is populated
- Set disable_reasoning=true for simple tasks to reduce latency
- May switch languages - always specify "Respond in English" in system prompt
- Adjust either temperature OR top_p, not both simultaneously
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

    # Cerebras model IDs use their own format (no slash like HuggingFace).
    # 2026-09-05: the account's live catalogue (GET /v1/models) is exactly
    # gpt-oss-120b, qwen-3.8-27b, gemma-4-31b — zai-glm-4.7, qwen-3-32b and
    # llama-3.3-70b were all archived upstream, so every "cerebras" card
    # summary 404'd (#COL.00000013.CARDSUMFAIL x26 per curate). gpt-oss-120b
    # is the reasoning model of a different family from the local Qwen lane.
    DEFAULT_MODEL = "gpt-oss-120b"
    # If the preferred reasoning model is archived, keep the panel alive
    # with another Cerebras model rather than dropping the feature.
    FALLBACK_MODELS = ("qwen-3.8-27b", "gemma-4-31b")

    # Recommended max_tokens for reasoning models to complete their chain-of-thought
    # GLM uses ~300-500 tokens for reasoning before producing final answer
    # GLM-4.7 supports up to 200K context, but 16K output is practical for most tasks
    RECOMMENDED_MAX_TOKENS = 16384

    def __init__(self, model: Optional[str] = None):
        """Initialize Cerebras backend.

        Args:
            model: Model to use (default: DEFAULT_MODEL, gpt-oss-120b)
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
        response_format: Optional[dict[str, Any]] = None,
        disable_reasoning: bool = False,
        clear_thinking: bool = True,
        **kwargs: Any,
    ) -> ExternalResponse:
        """Execute completion via Cerebras Cloud.

        Args:
            messages: Chat messages in OpenAI format
            model: Model to use (default: zai-glm-4.7)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate (default: 2048 for reasoning models)
            response_format: Optional structured output format. Use:
                {"type": "json_schema", "json_schema": {"name": "schema_name", "strict": True, "schema": {...}}}
                to enforce JSON schema compliance.
            disable_reasoning: GLM 4.7 only - disable chain-of-thought reasoning for faster
                simple responses. Default False (reasoning enabled).
            clear_thinking: GLM 4.7 only - whether to exclude thinking from previous turns.
                Default True. Set to False for agentic/coding workflows where reasoning
                should persist across turns (improves prompt cache hit rate).

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

        requested = model or self._model
        models_to_try = (requested,) if model else (requested, *self.FALLBACK_MODELS)
        start_time = time.time()
        last_error = ""
        use_model = requested

        for use_model in models_to_try:
            try:
                api_params: dict[str, Any] = {
                    "messages": messages,
                    "model": use_model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format is not None:
                    api_params["response_format"] = response_format
                if "glm" in use_model.lower():
                    if disable_reasoning:
                        api_params["disable_reasoning"] = True
                    if not clear_thinking:
                        api_params["clear_thinking"] = False

                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda params=api_params: client.chat.completions.create(**params),
                )

                latency_ms = int((time.time() - start_time) * 1000)

                content = ""
                reasoning = None
                finish_reason = None
                if response.choices:
                    choice = response.choices[0]
                    message = choice.message
                    finish_reason = getattr(choice, "finish_reason", None)
                    content = message.content or ""
                    if hasattr(message, "reasoning") and message.reasoning:
                        reasoning = message.reasoning
                        if not content:
                            content = reasoning
                usage = response.usage if hasattr(response, "usage") else None
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0

                is_truncated = finish_reason == "length"
                if is_truncated:
                    logger.warning(
                        f"Cerebras response truncated: model={use_model}, "
                        f"output_tokens={output_tokens}, finish_reason={finish_reason}"
                    )

                try:
                    from ...metrics import record_inference, EngineMetrics
                    record_inference(
                        model=use_model,
                        latency_ms=latency_ms,
                        tokens_in=input_tokens,
                        tokens_out=output_tokens,
                        success=True,
                        provider="cerebras",
                    )
                    if is_truncated:
                        EngineMetrics.get_instance().record_error("llm_truncated")
                        EngineMetrics.get_instance()._inference_errors.add(
                            1, {"model": use_model, "provider": "cerebras", "reason": "truncated"}
                        )
                except Exception as e:
                    logger.debug(f"Failed to record telemetry: {e}")

                if use_model != requested:
                    logger.info("Cerebras fell back from %s to %s", requested, use_model)
                return ExternalResponse(
                    content=content,
                    model=use_model,
                    provider="cerebras",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    reasoning=reasoning,
                    finish_reason=finish_reason,
                )
            except Exception as e:
                last_error = str(e)
                logger.warning("Cerebras %s failed: %s", use_model, e)
                try:
                    from ...metrics import record_inference
                    record_inference(
                        model=use_model,
                        latency_ms=int((time.time() - start_time) * 1000),
                        success=False,
                        provider="cerebras",
                    )
                except Exception:
                    pass

        return ExternalResponse(
            content="",
            model=use_model,
            provider="cerebras",
            latency_ms=int((time.time() - start_time) * 1000),
            error=last_error or "Cerebras models unavailable",
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
