"""Fluent query API for Kudu SDK-style queries.

Provides a type-safe, composable query builder:

    from gaius.bases.fluent import Base, col, term

    # Simple column-based query
    results = await (
        Base("events")
        .where(col("age") > 30)
        .where(col("status") == "active")
        .select("name", "email")
        .order_by("created_at", desc=True)
        .limit(100)
        .scan()
    )

    # Ontology-grounded query (BFO)
    results = await (
        Base("biopsy_events")
        .where(term("BFO:site") == "liver")
        .select(term("BFO:material_entity"), term("BFO:temporal_region"))
        .scan()
    )

Key components:
- Base(name): Entry point for building queries
- col(name): Column reference with comparison operators
- term(iri): Ontology term reference for BFO-grounded queries
- BaseQuery: The query builder with .where(), .select(), .order_by(), .limit()
- parse_fluent(expr): Parse string expressions safely (no eval)
- FluentCompiler: Compile queries to SQL using SQLGlot
"""

from gaius.bases.fluent.expressions import (
    col,
    term,
    ColumnRef,
    TermRef,
    Comparison,
    LogicalExpr,
    Predicate,
)
from gaius.bases.fluent.builder import Base, BaseQuery
from gaius.bases.fluent.compiler import FluentCompiler, CompiledQuery, CompilationError
from gaius.bases.fluent.parser import (
    parse_fluent,
    FluentParseError,
    UnsafeOperationError,
)

__all__ = [
    # Entry points
    "Base",
    "col",
    "term",
    # Query builder
    "BaseQuery",
    # Expression types
    "ColumnRef",
    "TermRef",
    "Comparison",
    "LogicalExpr",
    "Predicate",
    # Compiler
    "FluentCompiler",
    "CompiledQuery",
    "CompilationError",
    # Parser
    "parse_fluent",
    "FluentParseError",
    "UnsafeOperationError",
]
