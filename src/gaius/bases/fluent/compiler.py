"""Fluent query compiler using SQLGlot.

Compiles BaseQuery objects to SQL using SQLGlot's AST:

    query = Base("events").where(col("age") > 30).limit(10)
    sql = FluentCompiler().compile(query, base_def)
    # SELECT * FROM events WHERE age > 30 LIMIT 10
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlglot
from sqlglot import exp

from gaius.bases.fluent.expressions import (
    ColumnRef,
    Comparison,
    LogicalExpr,
    Predicate,
    TermRef,
)

if TYPE_CHECKING:
    from gaius.bases.fluent.builder import BaseQuery
    from gaius.bases.models import BaseDefinition
    from gaius.bases.semantic import OntologyContext


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    """Result of compiling a fluent query.

    Attributes:
        sql: The generated SQL string
        dialect: SQL dialect used (postgres, etc.)
        table_name: Physical table name
        parameters: Bound parameters for the query
    """

    sql: str
    dialect: str
    table_name: str
    parameters: dict[str, Any]


class FluentCompiler:
    """Compile fluent queries to SQL using SQLGlot.

    Generates PostgreSQL-compatible SQL. When kudu_fdw is available,
    queries will be routed through PostgreSQL to Kudu transparently.
    """

    def __init__(self, dialect: str = "postgres"):
        """Initialize compiler with target dialect.

        Args:
            dialect: SQLGlot dialect name (postgres, duckdb, etc.)
        """
        self.dialect = dialect

    def compile(
        self,
        query: BaseQuery,
        base: BaseDefinition,
    ) -> CompiledQuery:
        """Compile a fluent query to SQL.

        Args:
            query: The fluent query to compile
            base: Base definition with schema and @context

        Returns:
            CompiledQuery with SQL string and metadata

        Raises:
            CompilationError: If query cannot be compiled
        """
        # Resolve table name from base definition
        table_name = base.physical_table or base.base_id

        # Get ontology context for term resolution
        ont_ctx = base.ontology_context

        # Build SELECT clause
        if query._columns:
            columns = [self._resolve_column(c, ont_ctx) for c in query._columns]
            select_expr = sqlglot.select(*columns)
        else:
            select_expr = sqlglot.select("*")

        # FROM clause
        select_expr = select_expr.from_(table_name)

        # WHERE clause
        if query._predicates:
            where_expr = self._build_where(query._predicates, ont_ctx)
            select_expr = select_expr.where(where_expr)

        # ORDER BY clause
        for col_name, direction in query._order_specs:
            resolved_col = self._resolve_column(col_name, ont_ctx)
            select_expr = select_expr.order_by(
                exp.Ordered(
                    this=exp.Column(this=resolved_col),
                    desc=(direction == "DESC"),
                )
            )

        # LIMIT clause
        if query._limit_value is not None:
            select_expr = select_expr.limit(query._limit_value)

        # Generate SQL
        sql = select_expr.sql(dialect=self.dialect)

        return CompiledQuery(
            sql=sql,
            dialect=self.dialect,
            table_name=table_name,
            parameters={},
        )

    def _resolve_column(
        self,
        col: str | TermRef,
        ont_ctx: "OntologyContext",
    ) -> str:
        """Resolve column name, handling ontology terms.

        Uses OntologyContext for BFO-grounded term resolution:
        - term("BFO:site") -> resolves to column mapped to BFO:site in @context
        - term("BFO:temporal_region") -> resolves to timestamp column

        Args:
            col: Column name or TermRef
            ont_ctx: OntologyContext for IRI resolution

        Returns:
            Resolved column name

        Raises:
            CompilationError: If term cannot be resolved
        """
        if isinstance(col, TermRef):
            # Resolve IRI to column name via @context
            resolved = ont_ctx.resolve_term(col.iri)
            if resolved:
                return resolved

            # Fallback: extract local part of CURIE/IRI
            if ":" in col.iri:
                local = col.iri.split(":")[-1]
                # Try lowercase version as column name
                return local.lower()
            return col.iri
        return col

    def _build_where(
        self,
        predicates: list[Predicate],
        ont_ctx: "OntologyContext",
    ) -> exp.Expression:
        """Build WHERE clause from predicates.

        Multiple predicates are combined with AND.
        """
        if len(predicates) == 1:
            return self._compile_predicate(predicates[0], ont_ctx)

        # Combine multiple predicates with AND
        exprs = [self._compile_predicate(p, ont_ctx) for p in predicates]
        result = exprs[0]
        for expr in exprs[1:]:
            result = exp.And(this=result, expression=expr)
        return result

    def _compile_predicate(
        self,
        pred: Predicate,
        ont_ctx: "OntologyContext",
    ) -> exp.Expression:
        """Compile a single predicate to SQLGlot expression."""
        if isinstance(pred, Comparison):
            return self._compile_comparison(pred, ont_ctx)
        elif isinstance(pred, LogicalExpr):
            return self._compile_logical(pred, ont_ctx)
        else:
            raise CompilationError(f"Unknown predicate type: {type(pred)}")

    def _compile_comparison(
        self,
        comp: Comparison,
        ont_ctx: "OntologyContext",
    ) -> exp.Expression:
        """Compile a comparison to SQLGlot expression."""
        # Resolve left side (column or term)
        if isinstance(comp.left, ColumnRef):
            left = exp.Column(this=comp.left.name)
        elif isinstance(comp.left, TermRef):
            col_name = self._resolve_column(comp.left, ont_ctx)
            left = exp.Column(this=col_name)
        else:
            raise CompilationError(f"Unknown left operand type: {type(comp.left)}")

        # Compile right side (value)
        right = self._compile_value(comp.right)

        # Build comparison expression based on operator
        op = comp.op
        if op == "=":
            return exp.EQ(this=left, expression=right)
        elif op == "!=":
            return exp.NEQ(this=left, expression=right)
        elif op == "<":
            return exp.LT(this=left, expression=right)
        elif op == "<=":
            return exp.LTE(this=left, expression=right)
        elif op == ">":
            return exp.GT(this=left, expression=right)
        elif op == ">=":
            return exp.GTE(this=left, expression=right)
        elif op == "IN":
            values = [self._compile_value(v) for v in comp.right]
            return exp.In(this=left, expressions=values)
        elif op == "LIKE":
            return exp.Like(this=left, expression=right)
        elif op == "IS":
            return exp.Is(this=left, expression=exp.Null())
        elif op == "IS NOT":
            return exp.Not(this=exp.Is(this=left, expression=exp.Null()))
        else:
            raise CompilationError(f"Unknown operator: {op}")

    def _compile_logical(
        self,
        logical: LogicalExpr,
        ont_ctx: "OntologyContext",
    ) -> exp.Expression:
        """Compile a logical expression to SQLGlot expression."""
        compiled = [self._compile_predicate(op, ont_ctx) for op in logical.operands]

        if logical.op == "AND":
            result = compiled[0]
            for expr in compiled[1:]:
                result = exp.And(this=result, expression=expr)
            return result
        elif logical.op == "OR":
            result = compiled[0]
            for expr in compiled[1:]:
                result = exp.Or(this=result, expression=expr)
            return result
        elif logical.op == "NOT":
            if len(compiled) != 1:
                raise CompilationError("NOT requires exactly one operand")
            return exp.Not(this=compiled[0])
        else:
            raise CompilationError(f"Unknown logical operator: {logical.op}")

    def _compile_value(self, value: Any) -> exp.Expression:
        """Compile a Python value to SQLGlot literal."""
        if value is None:
            return exp.Null()
        elif isinstance(value, bool):
            return exp.Boolean(this=value)
        elif isinstance(value, int):
            return exp.Literal.number(value)
        elif isinstance(value, float):
            return exp.Literal.number(value)
        elif isinstance(value, str):
            return exp.Literal.string(value)
        else:
            # Fallback: convert to string
            return exp.Literal.string(str(value))


class CompilationError(Exception):
    """Error during query compilation.

    Guru Meditation: #FLUENT.00000003.COMPILEFAIL
    """

    pass
