"""Fluent query builder for Kudu SDK-style queries.

Provides the Base() entry point and BaseQuery class for building queries:

    from gaius.bases import Base, col

    results = await (
        Base("events")
        .where(col("age") > 30)
        .select("name", "email")
        .order_by("created_at", desc=True)
        .limit(100)
        .scan()
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from gaius.bases.fluent.expressions import (
    ColumnRef,
    Predicate,
    TermRef,
    col,
    term,
)

if TYPE_CHECKING:
    from gaius.bases.models import QueryResult


@dataclass
class BaseQuery:
    """Fluent query builder for Bases.

    Mirrors the Kudu SDK scanner pattern with method chaining.
    Call .scan() to execute the query asynchronously.
    """

    _base_name: str
    _predicates: list[Predicate] = field(default_factory=list)
    _columns: list[str | TermRef] = field(default_factory=list)
    _order_specs: list[tuple[str, Literal["ASC", "DESC"]]] = field(default_factory=list)
    _limit_value: int | None = None
    _as_of_timestamp: str | None = None

    def where(self, predicate: Predicate) -> BaseQuery:
        """Add a filter predicate.

        Multiple .where() calls are combined with AND.

        Args:
            predicate: A comparison built with col() or term()

        Returns:
            Self for method chaining

        Example:
            Base("events").where(col("age") > 30).where(col("active") == True)
        """
        self._predicates.append(predicate)
        return self

    def select(self, *columns: str | TermRef) -> BaseQuery:
        """Select specific columns to return.

        By default, all columns (*) are returned.

        Args:
            *columns: Column names or TermRef for ontology-grounded selection

        Returns:
            Self for method chaining

        Example:
            Base("events").select("name", "email", term("BFO:temporal_region"))
        """
        self._columns.extend(columns)
        return self

    def order_by(self, column: str, desc: bool = False) -> BaseQuery:
        """Add an ORDER BY clause.

        Multiple .order_by() calls add additional sort keys.

        Args:
            column: Column name to sort by
            desc: Sort descending if True

        Returns:
            Self for method chaining

        Example:
            Base("events").order_by("created_at", desc=True).order_by("name")
        """
        direction: Literal["ASC", "DESC"] = "DESC" if desc else "ASC"
        self._order_specs.append((column, direction))
        return self

    def limit(self, n: int) -> BaseQuery:
        """Limit the number of rows returned.

        Args:
            n: Maximum rows to return

        Returns:
            Self for method chaining

        Raises:
            ValueError: If n is negative
        """
        if n < 0:
            raise ValueError(f"LIMIT must be non-negative, got {n}")
        self._limit_value = n
        return self

    def as_of(self, timestamp: str) -> BaseQuery:
        """Time-travel query for historical bases (Iceberg).

        Args:
            timestamp: ISO 8601 timestamp

        Returns:
            Self for method chaining

        Example:
            Base("events").as_of("2024-01-01T00:00:00Z").where(col("x") > 1)
        """
        self._as_of_timestamp = timestamp
        return self

    async def scan(self) -> QueryResult:
        """Execute the query and return results.

        Returns:
            QueryResult with columns, rows, and metadata

        Raises:
            BasesError: If query execution fails
        """
        from gaius.bases.service import get_bases_service

        service = get_bases_service()
        if not service.is_running:
            await service.start()
        return await service.execute_fluent(self)

    def to_sql(self, dialect: str = "postgres") -> str:
        """Generate SQL without executing.

        Useful for debugging and logging.

        Args:
            dialect: SQLGlot dialect (postgres, duckdb, etc.)

        Returns:
            Generated SQL string
        """
        from gaius.bases.fluent.compiler import FluentCompiler
        from gaius.bases.models import BaseDefinition, BaseType

        # Create a minimal base definition for compilation
        base = BaseDefinition(
            base_id=self._base_name,
            display_name=self._base_name,
            base_type=BaseType.SNAPSHOT,
            physical_table=self._base_name,
            schema=[],
        )

        compiler = FluentCompiler(dialect=dialect)
        compiled = compiler.compile(self, base)
        return compiled.sql

    def to_dict(self) -> dict[str, Any]:
        """Convert query to dictionary representation.

        Returns:
            Dictionary with query structure
        """
        result: dict[str, Any] = {
            "base": self._base_name,
        }

        if self._predicates:
            result["predicates"] = [_predicate_to_dict(p) for p in self._predicates]

        if self._columns:
            result["columns"] = [
                c.iri if isinstance(c, TermRef) else c for c in self._columns
            ]

        if self._order_specs:
            result["order_by"] = [
                {"column": col, "direction": dir} for col, dir in self._order_specs
            ]

        if self._limit_value is not None:
            result["limit"] = self._limit_value

        if self._as_of_timestamp:
            result["as_of"] = self._as_of_timestamp

        return result


def _predicate_to_dict(pred: Predicate) -> dict[str, Any]:
    """Convert a predicate to dictionary representation."""
    from gaius.bases.fluent.expressions import Comparison, LogicalExpr

    if isinstance(pred, Comparison):
        left = pred.left
        if isinstance(left, ColumnRef):
            left_dict = {"type": "column", "name": left.name}
        elif isinstance(left, TermRef):
            left_dict = {"type": "term", "iri": left.iri}
        else:
            left_dict = {"type": "unknown"}

        return {
            "type": "comparison",
            "left": left_dict,
            "op": pred.op,
            "right": pred.right,
        }
    elif isinstance(pred, LogicalExpr):
        return {
            "type": "logical",
            "op": pred.op,
            "operands": [_predicate_to_dict(op) for op in pred.operands],
        }
    else:
        return {"type": "unknown"}


def Base(name: str) -> BaseQuery:
    """Create a fluent query builder for a Base.

    This is the main entry point for the fluent query API.

    Args:
        name: Name of the Base to query

    Returns:
        BaseQuery builder for method chaining

    Example:
        results = await (
            Base("events")
            .where(col("age") > 30)
            .limit(100)
            .scan()
        )
    """
    return BaseQuery(_base_name=name)


# Re-export expression helpers for convenience
__all__ = ["Base", "BaseQuery", "col", "term"]
