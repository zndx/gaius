"""Unified budget tracking for external inference backends.

Manages separate budget pools for each per-token provider (XAI, Cerebras)
and concurrency tracking for subscription providers (Bytez).
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProviderBudget:
    """Budget tracking for a single per-token provider.

    Attributes:
        provider: Provider name (xai, cerebras)
        daily_limit: Maximum requests per day
        weekly_limit: Maximum requests per week
        daily_used: Requests used today
        weekly_used: Requests used this week
        current_day: Current day for daily reset
        week_start: Start of current week for weekly reset
        total_tokens_used: Total tokens consumed (for analytics)
    """

    provider: str
    daily_limit: int = 50
    weekly_limit: int = 200
    daily_used: int = 0
    weekly_used: int = 0
    current_day: date = field(default_factory=date.today)
    week_start: date = field(default_factory=date.today)
    total_tokens_used: int = 0

    def _maybe_reset(self) -> None:
        """Reset counters if day/week changed."""
        today = date.today()

        # Reset daily counter
        if today != self.current_day:
            logger.debug(f"{self.provider}: Daily budget reset ({self.daily_used} -> 0)")
            self.daily_used = 0
            self.current_day = today

        # Reset weekly counter (Monday is 0)
        if today.weekday() == 0 and today != self.week_start:
            logger.debug(f"{self.provider}: Weekly budget reset ({self.weekly_used} -> 0)")
            self.weekly_used = 0
            self.week_start = today

    def can_use(self) -> bool:
        """Check if provider can be used within budget."""
        self._maybe_reset()
        return self.daily_used < self.daily_limit and self.weekly_used < self.weekly_limit

    def record_use(self, tokens: int = 0) -> None:
        """Record a request use.

        Args:
            tokens: Number of tokens used (for analytics)
        """
        self._maybe_reset()
        self.daily_used += 1
        self.weekly_used += 1
        self.total_tokens_used += tokens
        logger.debug(
            f"{self.provider}: Budget used (daily: {self.daily_used}/{self.daily_limit}, "
            f"weekly: {self.weekly_used}/{self.weekly_limit})"
        )

    @property
    def daily_remaining(self) -> int:
        """Remaining daily budget."""
        self._maybe_reset()
        return max(0, self.daily_limit - self.daily_used)

    @property
    def weekly_remaining(self) -> int:
        """Remaining weekly budget."""
        self._maybe_reset()
        return max(0, self.weekly_limit - self.weekly_used)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for status display."""
        self._maybe_reset()
        return {
            "provider": self.provider,
            "daily_used": self.daily_used,
            "daily_limit": self.daily_limit,
            "daily_remaining": self.daily_remaining,
            "weekly_used": self.weekly_used,
            "weekly_limit": self.weekly_limit,
            "weekly_remaining": self.weekly_remaining,
            "total_tokens": self.total_tokens_used,
            "can_use": self.can_use(),
        }


@dataclass
class ExternalBudget:
    """Unified budget tracking for all external backends.

    Manages separate budget pools for per-token providers (XAI, Cerebras)
    and concurrency tracking for subscription providers (Bytez).
    """

    # Per-token provider budgets (separate pools)
    xai: ProviderBudget = field(
        default_factory=lambda: ProviderBudget(provider="xai", daily_limit=50, weekly_limit=200)
    )
    cerebras: ProviderBudget = field(
        default_factory=lambda: ProviderBudget(provider="cerebras", daily_limit=50, weekly_limit=200)
    )

    # Bytez concurrency tracking (subscription model)
    bytez_active_requests: int = 0
    bytez_max_concurrent: int = 2
    bytez_total_requests: int = 0

    def can_use_xai(self) -> bool:
        """Check if XAI can be used."""
        return self.xai.can_use()

    def can_use_cerebras(self) -> bool:
        """Check if Cerebras can be used."""
        return self.cerebras.can_use()

    def can_use_bytez(self) -> bool:
        """Check if Bytez can accept another request."""
        return self.bytez_active_requests < self.bytez_max_concurrent

    def record_xai_use(self, tokens: int = 0) -> None:
        """Record XAI API usage."""
        self.xai.record_use(tokens)

    def record_cerebras_use(self, tokens: int = 0) -> None:
        """Record Cerebras API usage."""
        self.cerebras.record_use(tokens)

    def record_bytez_start(self) -> bool:
        """Record start of Bytez request.

        Returns:
            True if request was accepted, False if at capacity
        """
        if not self.can_use_bytez():
            return False
        self.bytez_active_requests += 1
        self.bytez_total_requests += 1
        return True

    def record_bytez_end(self) -> None:
        """Record end of Bytez request."""
        self.bytez_active_requests = max(0, self.bytez_active_requests - 1)

    def get_available_providers(self) -> list[str]:
        """Get list of providers that can accept requests."""
        available = []
        if self.can_use_xai():
            available.append("xai")
        if self.can_use_cerebras():
            available.append("cerebras")
        if self.can_use_bytez():
            available.append("bytez")
        return available

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for status display."""
        return {
            "xai": self.xai.to_dict(),
            "cerebras": self.cerebras.to_dict(),
            "bytez": {
                "active_requests": self.bytez_active_requests,
                "max_concurrent": self.bytez_max_concurrent,
                "total_requests": self.bytez_total_requests,
                "can_use": self.can_use_bytez(),
            },
            "available_providers": self.get_available_providers(),
        }

    def reset_daily(self, provider: str | None = None) -> None:
        """Reset daily counters for one or all providers.

        Args:
            provider: Specific provider to reset, or None for all
        """
        if provider is None or provider == "xai":
            self.xai.daily_used = 0
            self.xai.current_day = date.today()
        if provider is None or provider == "cerebras":
            self.cerebras.daily_used = 0
            self.cerebras.current_day = date.today()

    def reset_weekly(self, provider: str | None = None) -> None:
        """Reset weekly counters for one or all providers.

        Args:
            provider: Specific provider to reset, or None for all
        """
        if provider is None or provider == "xai":
            self.xai.weekly_used = 0
            self.xai.week_start = date.today()
        if provider is None or provider == "cerebras":
            self.cerebras.weekly_used = 0
            self.cerebras.week_start = date.today()


# Module-level singleton
_external_budget: ExternalBudget | None = None


def get_external_budget() -> ExternalBudget:
    """Get or create the external budget singleton."""
    global _external_budget
    if _external_budget is None:
        _external_budget = ExternalBudget()
    return _external_budget


def reset_external_budget() -> None:
    """Reset the external budget singleton (for testing)."""
    global _external_budget
    _external_budget = None
