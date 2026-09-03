"""Base class for external inference backends.

Defines the abstract interface that all external inference providers
(XAI, Cerebras, Bytez) must implement.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional
from gaius.core.budgets import EXTERNAL_MAX_TOKENS

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """A tool call from an LLM response (OpenAI function calling format).

    Attributes:
        id: Unique identifier for this tool call
        name: Name of the function to call
        arguments: JSON string of arguments to pass
    """

    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class ExternalResponse:
    """Response from an external inference API.

    Attributes:
        content: Generated text content (for reasoning models, parsed JSON)
        model: Model that generated response
        provider: Provider name (xai, cerebras, bytez)
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Request latency in milliseconds
        error: Error message if request failed
        reasoning: Chain-of-thought from reasoning models (for distillation)
        finish_reason: API finish reason (stop, length, content_filter, tool_calls, etc.)
        exchange_id: UUID of captured exchange record (for lineage linkage)
        request_hash: SHA-256 hash of request (for deduplication/linkage)
        tool_calls: List of tool calls if model requested function calling
    """

    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None
    reasoning: Optional[str] = None
    finish_reason: Optional[str] = None
    exchange_id: Optional[str] = None
    request_hash: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None

    @property
    def truncated(self) -> bool:
        """Whether response was truncated due to max_tokens limit.

        This is an important signal for LLM error tracking - truncated
        responses often indicate the model couldn't complete its output.
        """
        return self.finish_reason == "length"

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens


class ExternalBackend(ABC):
    """Base class for external inference APIs.

    All external providers (XAI, Cerebras, Bytez) implement this interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'xai', 'cerebras', 'bytez')."""
        pass

    @property
    @abstractmethod
    def pricing_model(self) -> str:
        """Pricing model: 'per_token' or 'subscription'."""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the backend is configured and available."""
        pass

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = EXTERNAL_MAX_TOKENS,
        **kwargs: Any,
    ) -> ExternalResponse:
        """Execute a completion request.

        Args:
            messages: Chat messages in OpenAI format
            model: Model to use (provider-specific default if None)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            ExternalResponse with completion result
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the backend is healthy and responsive.

        Returns:
            True if backend is operational
        """
        pass

    async def close(self) -> None:
        """Clean up resources. Override if needed."""
        pass

    def get_status(self) -> dict[str, Any]:
        """Get backend status for health reporting.

        Returns:
            Status dict with provider info
        """
        return {
            "name": self.name,
            "available": self.is_available,
            "pricing_model": self.pricing_model,
        }
