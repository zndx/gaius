"""Fluent query expressions for Kudu SDK-style queries.

Provides col() and term() helpers for building type-safe predicates:

    from gaius.bases import col, term

    # Column-based predicate
    col("age") > 30

    # Ontology term predicate (BFO grounded)
    term("BFO:material_entity") == "ENT-12345"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ColumnRef:
    """Reference to a column in a Base.

    Supports comparison operators for building predicates:
        col("age") > 30
        col("status").isin("active", "pending")
        col("name").like("John%")
    """

    name: str

    def __eq__(self, other: Any) -> Comparison:  # type: ignore[override]
        return Comparison(self, "=", other)

    def __ne__(self, other: Any) -> Comparison:  # type: ignore[override]
        return Comparison(self, "!=", other)

    def __lt__(self, other: Any) -> Comparison:
        return Comparison(self, "<", other)

    def __le__(self, other: Any) -> Comparison:
        return Comparison(self, "<=", other)

    def __gt__(self, other: Any) -> Comparison:
        return Comparison(self, ">", other)

    def __ge__(self, other: Any) -> Comparison:
        return Comparison(self, ">=", other)

    def isin(self, *values: Any) -> Comparison:
        """Check if column value is in a set of values."""
        return Comparison(self, "IN", list(values))

    def like(self, pattern: str) -> Comparison:
        """Pattern matching with SQL LIKE syntax."""
        return Comparison(self, "LIKE", pattern)

    def is_null(self) -> Comparison:
        """Check if column is NULL."""
        return Comparison(self, "IS", None)

    def is_not_null(self) -> Comparison:
        """Check if column is NOT NULL."""
        return Comparison(self, "IS NOT", None)


@dataclass(frozen=True, slots=True)
class TermRef:
    """Reference to an ontology term (BFO IRI).

    Used for semantic queries grounded in BFO ontology:
        term("BFO:material_entity") == "ENT-12345"
        term("BFO:temporal_region") > "2024-01-01"

    The IRI is resolved against the @context in the .base file.
    """

    iri: str

    def __eq__(self, other: Any) -> Comparison:  # type: ignore[override]
        return Comparison(self, "=", other)

    def __ne__(self, other: Any) -> Comparison:  # type: ignore[override]
        return Comparison(self, "!=", other)

    def __lt__(self, other: Any) -> Comparison:
        return Comparison(self, "<", other)

    def __le__(self, other: Any) -> Comparison:
        return Comparison(self, "<=", other)

    def __gt__(self, other: Any) -> Comparison:
        return Comparison(self, ">", other)

    def __ge__(self, other: Any) -> Comparison:
        return Comparison(self, ">=", other)

    def isin(self, *values: Any) -> Comparison:
        """Check if term value is in a set of values."""
        return Comparison(self, "IN", list(values))


ComparisonOp = Literal["=", "!=", "<", "<=", ">", ">=", "IN", "LIKE", "IS", "IS NOT"]


@dataclass(frozen=True, slots=True)
class Comparison:
    """A comparison predicate between a column/term and a value.

    Built using comparison operators on ColumnRef or TermRef:
        col("age") > 30  # Comparison(ColumnRef("age"), ">", 30)
    """

    left: ColumnRef | TermRef
    op: ComparisonOp
    right: Any

    def __and__(self, other: Comparison) -> LogicalExpr:
        """Combine with AND: (col("a") > 1) & (col("b") < 10)"""
        return LogicalExpr("AND", [self, other])

    def __or__(self, other: Comparison) -> LogicalExpr:
        """Combine with OR: (col("a") > 1) | (col("b") < 10)"""
        return LogicalExpr("OR", [self, other])

    def __invert__(self) -> LogicalExpr:
        """Negate with NOT: ~(col("a") > 1)"""
        return LogicalExpr("NOT", [self])


LogicalOp = Literal["AND", "OR", "NOT"]


@dataclass(frozen=True, slots=True)
class LogicalExpr:
    """A logical expression combining comparisons.

    Built using &, |, ~ operators on Comparison objects:
        (col("a") > 1) & (col("b") < 10)
        (col("x") == "foo") | (col("x") == "bar")
        ~(col("deleted") == True)
    """

    op: LogicalOp
    operands: list[Comparison | LogicalExpr]

    def __and__(self, other: Comparison | LogicalExpr) -> LogicalExpr:
        if self.op == "AND":
            return LogicalExpr("AND", [*self.operands, other])
        return LogicalExpr("AND", [self, other])

    def __or__(self, other: Comparison | LogicalExpr) -> LogicalExpr:
        if self.op == "OR":
            return LogicalExpr("OR", [*self.operands, other])
        return LogicalExpr("OR", [self, other])

    def __invert__(self) -> LogicalExpr:
        return LogicalExpr("NOT", [self])


# Type alias for any predicate expression
Predicate = Comparison | LogicalExpr


def col(name: str) -> ColumnRef:
    """Create a column reference for building predicates.

    Args:
        name: Column name in the Base schema

    Returns:
        ColumnRef that supports comparison operators

    Example:
        >>> col("age") > 30
        Comparison(ColumnRef("age"), ">", 30)
    """
    return ColumnRef(name)


def term(iri: str) -> TermRef:
    """Create an ontology term reference for semantic queries.

    Args:
        iri: Ontology IRI (e.g., "BFO:material_entity" or full IRI)

    Returns:
        TermRef that supports comparison operators

    Example:
        >>> term("BFO:site") == "liver"
        Comparison(TermRef("BFO:site"), "=", "liver")
    """
    return TermRef(iri)
