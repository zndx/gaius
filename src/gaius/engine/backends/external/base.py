"""Base class for external inference backends.

Defines the abstract interface that all external inference providers
(XAI, Cerebras, Bytez) must implement.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExternalResponse:
    """Response from an external inference API.

    Attributes:
        content: Generated text content
        model: Model that generated response
        provider: Provider name (xai, cerebras, bytez)
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Request latency in milliseconds
        error: Error message if request failed
    """

    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None

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
        max_tokens: int = 4096,
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
