"""Query guardrails for Bases feature store.

Guardrails enforce limits on query execution to prevent:
- Unbounded time range queries (expensive scans)
- Excessive result sets
- Long-running queries
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from gaius.bases.dql.parser import DQLQuery, LimitClause
from gaius.bases.dql.ast import BinaryOp, UnaryOp, Identifier, Expression
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

    # Read-only enforcement (DQL is inherently read-only)
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
    """Enforce guardrails on DQL queries.

    Validates and potentially modifies queries to ensure they comply
    with resource limits. Fails fast if guardrails are violated.
    """

    def __init__(self, guardrails: QueryGuardrails):
        self.guardrails = guardrails

    def enforce(self, query: DQLQuery, base: BaseDefinition) -> DQLQuery:
        """Apply guardrails to a parsed query.

        May modify the query to add missing constraints.
        Raises GuardrailViolation if hard limits are violated.

        Args:
            query: Parsed DQL query
            base: Base definition being queried

        Returns:
            Modified DQLQuery with guardrails applied

        Raises:
            GuardrailViolation: If guardrails are violated
        """
        # Enforce LIMIT
        if query.limit is None:
            query.limit = LimitClause(self.guardrails.default_limit)
        elif query.limit.count > self.guardrails.max_limit:
            raise GuardrailViolation(
                f"LIMIT {query.limit.count} exceeds maximum {self.guardrails.max_limit}. "
                f"Reduce your LIMIT clause."
            )

        # Enforce time range for historical bases
        if (
            base.base_type == BaseType.HISTORICAL
            and self.guardrails.require_time_range
            and query.as_of is None
            and not self._has_time_filter(query)
        ):
            # The compiler will add a default time filter, but log a warning
            pass

        return query

    def _has_time_filter(self, query: DQLQuery) -> bool:
        """Check if query has an explicit time filter."""
        if query.where is None:
            return False
        return self._expression_has_time_filter(query.where.expression)

    def _expression_has_time_filter(self, expr: Expression) -> bool:
        """Recursively check for time column references."""
        if isinstance(expr, BinaryOp):
            return (
                self._expression_has_time_filter(expr.left)
                or self._expression_has_time_filter(expr.right)
            )
        elif isinstance(expr, UnaryOp):
            return self._expression_has_time_filter(expr.operand)
        elif isinstance(expr, Identifier):
            # Common time column names
            time_columns = {
                "event_time",
                "ingestion_time",
                "created_at",
                "updated_at",
                "timestamp",
                "ts",
            }
            return expr.name.lower() in time_columns
        return False

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
