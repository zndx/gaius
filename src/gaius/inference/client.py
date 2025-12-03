"""Unified inference client with local-first fallback.

Tiered inference architecture:
1. optillm → vLLM: Local inference with optimization techniques (COT, MOA, etc.)
2. vLLM direct: Local fallback if optillm unavailable
3. XAI Grok: Outsider model for objective evaluation/critique
4. OpenAI: Last resort fallback
"""

from dataclasses import dataclass
from typing import AsyncIterator
import httpx
import logging
import os

from .config import InferenceConfig, InferenceBackend, OptillmTechnique

logger = logging.getLogger(__name__)

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
    backend: str | None = None  # Which backend actually served the request


class InferenceClient:
    """Unified inference client with local-first fallback.

    Architecture:
        Primary: optillm → vLLM (local with optimization techniques)
        Fallback chain: vLLM direct → XAI → OpenAI

    Usage:
        client = InferenceClient()
        result = await client.complete([Message(role="user", content="Hello")])
        print(result.content)

        # With optimization technique
        result = await client.complete(
            [Message(role="user", content="Explain quantum computing")],
            technique="cot_reflection"
        )

        # XAI evaluation (outsider perspective)
        result = await client.evaluate([Message(role="user", content="Review this...")])
    """

    def __init__(self, config: InferenceConfig | None = None):
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "openai package required. Install with: uv sync --extra inference"
            )

        self.config = config or InferenceConfig.from_env()

        # Client pool for fallback chain
        self._clients: dict[str, AsyncOpenAI] = {}
        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize OpenAI-compatible clients for all available backends."""
        # optillm (local proxy with optimization)
        # Uses API key from config (which loads from env var or HOCON)
        self._clients["optillm"] = AsyncOpenAI(
            api_key=self.config.optillm_api_key,
            base_url=self.config.optillm_url,
            timeout=self.config.timeout,
        )

        # vLLM direct (local fallback)
        self._clients["vllm"] = AsyncOpenAI(
            api_key="sk-vllm",
            base_url=self.config.vllm_url,
            timeout=self.config.timeout,
        )

        # XAI Grok (outsider evaluation model)
        if self.config.xai_api_key:
            self._clients["xai"] = AsyncOpenAI(
                api_key=self.config.xai_api_key,
                base_url=self.config.xai_url,
                timeout=self.config.timeout,
            )

        # OpenAI (last resort)
        if self.config.openai_api_key and not self.config.offline_mode:
            self._clients["openai"] = AsyncOpenAI(
                api_key=self.config.openai_api_key,
                timeout=self.config.timeout,
            )

    def _get_primary_client(self) -> tuple[AsyncOpenAI | None, str]:
        """Get the primary client based on configured backend."""
        backend = self.config.backend.value
        return self._clients.get(backend), backend

    def _get_fallback_chain(self) -> list[tuple[str, AsyncOpenAI]]:
        """Get fallback chain: local first, then remote.

        Order: vLLM → XAI → OpenAI
        """
        chain = []

        # Local fallback first
        if "vllm" in self._clients:
            chain.append(("vllm", self._clients["vllm"]))

        # XAI for outsider evaluation
        if "xai" in self._clients:
            chain.append(("xai", self._clients["xai"]))

        # OpenAI last resort
        if "openai" in self._clients:
            chain.append(("openai", self._clients["openai"]))

        return chain

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
        model: str | None = None,
    ) -> CompletionResult:
        """Complete a conversation using local-first inference.

        Args:
            messages: List of chat messages
            technique: optillm technique to use (overrides config)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            model: Override model (uses config model if not specified)

        Returns:
            CompletionResult with response content and metadata
        """
        # Use provided model or get from config with technique prefix
        if model:
            model_name = model
        else:
            model_name = self._get_model_name(technique)
        max_tokens = max_tokens or self.config.max_tokens

        openai_messages = [{"role": m.role, "content": m.content} for m in messages]

        # Try primary client (optillm by default)
        primary_client, primary_backend = self._get_primary_client()
        last_error = None

        if primary_client:
            try:
                response = await primary_client.chat.completions.create(
                    model=model_name,
                    messages=openai_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return self._parse_response(response, technique, backend=primary_backend)
            except Exception as e:
                logger.warning(f"Primary backend ({primary_backend}) failed: {e}")
                last_error = e

        # Try fallback chain: vLLM → XAI → OpenAI
        for backend_name, client in self._get_fallback_chain():
            if backend_name == primary_backend:
                continue  # Skip if already tried

            try:
                # Discover vLLM model if needed (different model may be loaded)
                if backend_name == "vllm":
                    await self._discover_vllm_model()

                # Use appropriate model for backend
                fallback_model = self._get_model_for_backend(backend_name)
                response = await client.chat.completions.create(
                    model=fallback_model,
                    messages=openai_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                logger.info(f"Fallback to {backend_name} succeeded")
                return self._parse_response(response, technique=None, backend=backend_name)
            except Exception as e:
                logger.warning(f"Fallback backend ({backend_name}) failed: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All inference backends failed. Last error: {last_error}")

    def _get_model_for_backend(self, backend: str) -> str:
        """Get appropriate model name for a backend."""
        if backend == "vllm":
            # Use cached model if available, otherwise use config default
            return getattr(self, "_vllm_model", None) or self.config.model
        elif backend == "xai":
            return self.config.xai_model
        elif backend == "openai":
            return self.config.fallback_model
        return self.config.model

    async def _discover_vllm_model(self) -> str | None:
        """Discover available model from vLLM endpoint.

        Queries /v1/models and caches the first available model.
        Returns None if endpoint unavailable or no models loaded.
        """
        if hasattr(self, "_vllm_model") and self._vllm_model:
            return self._vllm_model

        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{self.config.vllm_url.rstrip('/v1')}/v1/models",
                    timeout=5,
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("data"):
                        self._vllm_model = data["data"][0]["id"]
                        logger.debug(f"Discovered vLLM model: {self._vllm_model}")
                        return self._vllm_model
        except Exception as e:
            logger.debug(f"vLLM model discovery failed: {e}")

        return None

    async def evaluate(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
        temperature: float = 0.5,
    ) -> CompletionResult:
        """Evaluate using XAI Grok as outsider model.

        XAI provides an 'outsider' perspective for objective evaluation,
        useful for workflow optimization and quality assessment.

        Falls back to other frontiers if XAI unavailable.
        """
        max_tokens = max_tokens or self.config.max_tokens
        openai_messages = [{"role": m.role, "content": m.content} for m in messages]

        # Prefer XAI for evaluation
        if "xai" in self._clients:
            try:
                response = await self._clients["xai"].chat.completions.create(
                    model=self.config.xai_model,
                    messages=openai_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return self._parse_response(response, technique=None, backend="xai")
            except Exception as e:
                logger.warning(f"XAI evaluation failed: {e}")

        # Fallback to OpenAI for evaluation
        if "openai" in self._clients:
            try:
                response = await self._clients["openai"].chat.completions.create(
                    model=self.config.fallback_model,
                    messages=openai_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return self._parse_response(response, technique=None, backend="openai")
            except Exception as e:
                logger.warning(f"OpenAI evaluation fallback failed: {e}")

        # Last resort: use local model
        return await self.complete(messages, max_tokens=max_tokens, temperature=temperature)

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
        self,
        response,
        technique: OptillmTechnique | str | None,
        backend: str | None = None,
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
            backend=backend,
        )

    async def is_available(self) -> bool:
        """Check if the primary backend is available."""
        primary_client, _ = self._get_primary_client()
        if not primary_client:
            return False

        try:
            base_url = str(primary_client.base_url).rstrip("/v1")
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{base_url}/v1/models", timeout=5)
                return r.status_code == 200
        except Exception:
            return False

    async def check_backends(self) -> dict[str, bool]:
        """Check availability of all configured backends."""
        results = {}

        for name, client in self._clients.items():
            try:
                base_url = str(client.base_url).rstrip("/v1")
                async with httpx.AsyncClient() as http_client:
                    # Add auth header for optillm
                    headers = {}
                    if name == "optillm":
                        headers["Authorization"] = f"Bearer {self.config.optillm_api_key}"

                    r = await http_client.get(
                        f"{base_url}/v1/models",
                        timeout=5,
                        headers=headers,
                    )
                    results[name] = r.status_code == 200
            except Exception as e:
                logger.debug(f"Backend {name} check failed: {e}")
                results[name] = False

        return results

    def get_status(self) -> dict:
        """Get current client configuration status."""
        return {
            "primary_backend": self.config.backend.value,
            "available_backends": list(self._clients.keys()),
            "model": self.config.model,
            "xai_model": self.config.xai_model,
            "fallback_model": self.config.fallback_model,
            "offline_mode": self.config.offline_mode,
        }

    def set_technique(self, technique: OptillmTechnique | str) -> None:
        """Update the default technique."""
        if isinstance(technique, str):
            technique = OptillmTechnique(technique)
        self.config = self.config.with_technique(technique)
