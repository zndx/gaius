"""Unified inference client with offline-first fallback."""

from dataclasses import dataclass
from typing import AsyncIterator
import httpx
import os

from .config import InferenceConfig, InferenceBackend, OptillmTechnique

try:
    from openai import AsyncOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@dataclass
class Message:
    """Chat message."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class CompletionResult:
    """Result from a completion request."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    technique: str | None = None
    raw_response: dict | None = None


class InferenceClient:
    """Unified inference client with offline-first fallback.

    Usage:
        client = InferenceClient()
        result = await client.complete([Message(role="user", content="Hello")])
        print(result.content)

        # With technique
        result = await client.complete(
            [Message(role="user", content="Explain quantum computing")],
            technique="cot_reflection"
        )
    """

    def __init__(self, config: InferenceConfig | None = None):
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "openai package required. Install with: uv sync --extra inference"
            )

        self.config = config or InferenceConfig.from_env()
        self._primary_client: AsyncOpenAI | None = None
        self._fallback_client: AsyncOpenAI | None = None
        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize OpenAI-compatible clients for configured backends."""
        if self.config.backend == InferenceBackend.OPTILLM:
            # Use OPTILLM_API_KEY env var or default
            optillm_key = os.getenv("OPTILLM_API_KEY", "sk-optillm")
            self._primary_client = AsyncOpenAI(
                api_key=optillm_key,
                base_url=self.config.optillm_url,
                timeout=self.config.timeout,
            )
        elif self.config.backend == InferenceBackend.VLLM:
            self._primary_client = AsyncOpenAI(
                api_key="sk-vllm",
                base_url=self.config.vllm_url,
                timeout=self.config.timeout,
            )
        elif self.config.backend == InferenceBackend.OPENAI:
            if self.config.openai_api_key:
                self._primary_client = AsyncOpenAI(
                    api_key=self.config.openai_api_key,
                    timeout=self.config.timeout,
                )
            else:
                raise ValueError("OPENAI_API_KEY required for OpenAI backend")

        # Setup fallback (only if not offline)
        if not self.config.offline_mode and self.config.fallback_backend:
            if (
                self.config.fallback_backend == InferenceBackend.OPENAI
                and self.config.openai_api_key
            ):
                self._fallback_client = AsyncOpenAI(
                    api_key=self.config.openai_api_key,
                    timeout=self.config.timeout,
                )

    def _get_model_name(self, technique: OptillmTechnique | str | None = None) -> str:
        """Build model name with optional technique prefix.

        optillm uses the format: {technique}-{model}
        e.g., "cot_reflection-Qwen/Qwen2.5-Coder-32B-Instruct"
        """
        model = self.config.model

        # Resolve technique
        if technique is None:
            technique = self.config.optillm_technique
        elif isinstance(technique, str):
            try:
                technique = OptillmTechnique(technique)
            except ValueError:
                # Allow raw string for custom techniques
                pass

        # Add technique prefix for optillm backend
        if self.config.backend == InferenceBackend.OPTILLM:
            if isinstance(technique, OptillmTechnique):
                if technique != OptillmTechnique.NONE:
                    model = f"{technique.value}-{model}"
            elif isinstance(technique, str) and technique:
                model = f"{technique}-{model}"

        return model

    async def complete(
        self,
        messages: list[Message],
        technique: OptillmTechnique | str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> CompletionResult:
        """Complete a conversation.

        Args:
            messages: List of chat messages
            technique: optillm technique to use (overrides config)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            CompletionResult with response content and metadata
        """
        model = self._get_model_name(technique)
        max_tokens = max_tokens or self.config.max_tokens

        openai_messages = [{"role": m.role, "content": m.content} for m in messages]

        # Try primary client
        try:
            if self._primary_client:
                response = await self._primary_client.chat.completions.create(
                    model=model,
                    messages=openai_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return self._parse_response(response, technique)
        except Exception as e:
            if self._fallback_client:
                # Try fallback
                response = await self._fallback_client.chat.completions.create(
                    model=self.config.fallback_model,
                    messages=openai_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return self._parse_response(response, technique=None)
            raise RuntimeError(f"Inference failed: {e}") from e

        raise RuntimeError("No inference client available")

    async def stream(
        self,
        messages: list[Message],
        technique: OptillmTechnique | str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream a completion response.

        Yields chunks of text as they arrive.
        """
        model = self._get_model_name(technique)
        max_tokens = max_tokens or self.config.max_tokens

        openai_messages = [{"role": m.role, "content": m.content} for m in messages]

        if not self._primary_client:
            raise RuntimeError("No inference client available")

        stream = await self._primary_client.chat.completions.create(
            model=model,
            messages=openai_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _parse_response(
        self, response, technique: OptillmTechnique | str | None
    ) -> CompletionResult:
        """Parse OpenAI response into CompletionResult."""
        choice = response.choices[0]
        usage = response.usage

        technique_str = None
        if isinstance(technique, OptillmTechnique):
            technique_str = technique.value if technique != OptillmTechnique.NONE else None
        elif isinstance(technique, str):
            technique_str = technique or None

        return CompletionResult(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            technique=technique_str,
        )

    async def is_available(self) -> bool:
        """Check if the primary backend is available."""
        if not self._primary_client:
            return False

        try:
            # Use httpx for a quick health check
            base_url = str(self._primary_client.base_url).rstrip("/v1")
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{base_url}/v1/models", timeout=5)
                return r.status_code == 200
        except Exception:
            return False

    def set_technique(self, technique: OptillmTechnique | str) -> None:
        """Update the default technique."""
        if isinstance(technique, str):
            technique = OptillmTechnique(technique)
        self.config = self.config.with_technique(technique)
