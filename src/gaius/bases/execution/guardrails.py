"""Query guardrails for Bases feature store.

Guardrails enforce limits on query execution to prevent:
- Unbounded time range queries (expensive scans)
- Excessive result sets
- Long-running queries
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from gaius.bases.models.base import BaseDefinition, BaseType


@dataclass
class QueryGuardrails:
    """Enforced limits on query execution."""

    # Time range limits (for historical bases)
    default_time_range: timedelta = timedelta(days=7)
    max_time_range: timedelta = timedelta(days=90)
    require_time_range: bool = True

    # Result limits
    default_limit: int = 1000
    max_limit: int = 10000

    # Timeout
    default_timeout_ms: int = 30000
    max_timeout_ms: int = 120000

    # Read-only enforcement (fluent queries are inherently read-only)
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "default_time_range_seconds": self.default_time_range.total_seconds(),
            "max_time_range_seconds": self.max_time_range.total_seconds(),
            "require_time_range": self.require_time_range,
            "default_limit": self.default_limit,
            "max_limit": self.max_limit,
            "default_timeout_ms": self.default_timeout_ms,
            "max_timeout_ms": self.max_timeout_ms,
            "read_only": self.read_only,
        }


class GuardrailEnforcer:
    """Enforce guardrails on fluent queries.

    Validates and potentially modifies queries to ensure they comply
    with resource limits. Fails fast if guardrails are violated.
    """

    def __init__(self, guardrails: QueryGuardrails):
        self.guardrails = guardrails

    def get_effective_limit(
        self,
        requested_limit: int | None,
        options: dict[str, Any] | None = None,
    ) -> int:
        """Get the effective LIMIT to apply.

        Args:
            requested_limit: Limit from the query (if any)
            options: Query options that may override limit

        Returns:
            Effective limit value

        Raises:
            GuardrailViolation: If requested limit exceeds maximum
        """
        # Check for override in options
        if options and "max_rows" in options:
            requested_limit = options["max_rows"]

        # Apply default if not specified
        if requested_limit is None:
            return self.guardrails.default_limit

        # Check against maximum
        if requested_limit > self.guardrails.max_limit:
            raise GuardrailViolation(
                f"LIMIT {requested_limit} exceeds maximum {self.guardrails.max_limit}. "
                f"Reduce your LIMIT clause or max_rows option."
            )

        return requested_limit

    def validate_time_range(
        self,
        base: BaseDefinition,
        has_as_of: bool = False,
        has_time_filter: bool = False,
    ) -> None:
        """Validate time range constraints for historical bases.

        Args:
            base: Base definition being queried
            has_as_of: Whether query has AS OF clause
            has_time_filter: Whether query has time filter in WHERE

        Raises:
            GuardrailViolation: If time range constraint is violated
        """
        if base.base_type != BaseType.HISTORICAL:
            return

        if not self.guardrails.require_time_range:
            return

        if has_as_of or has_time_filter:
            return

        # Historical base without time constraint - this is expensive
        raise GuardrailViolation(
            f"Historical base '{base.base_id}' requires a time constraint.\n"
            f"  Add .as_of('timestamp') or filter on a time column.\n"
            f"  Default time range: {self.guardrails.default_time_range.days} days"
        )

    def validate_timeout(self, timeout_ms: int | None) -> int:
        """Validate and normalize timeout.

        Args:
            timeout_ms: Requested timeout in milliseconds

        Returns:
            Valid timeout in milliseconds
        """
        if timeout_ms is None:
            return self.guardrails.default_timeout_ms

        if timeout_ms > self.guardrails.max_timeout_ms:
            return self.guardrails.max_timeout_ms

        if timeout_ms < 1000:  # Minimum 1 second
            return 1000

        return timeout_ms


class GuardrailViolation(Exception):
    """Exception raised when query violates guardrails."""

    def __init__(self, message: str, code: str = "GUARDRAIL_VIOLATION"):
        super().__init__(message)
        self.code = code
        self.message = message
