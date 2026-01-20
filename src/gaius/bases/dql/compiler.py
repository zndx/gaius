"""DQL Compilers - translate DQL AST to backend-specific SQL.

Each backend (PostgreSQL, Iceberg, Pinot) has its own compiler that
translates the DQL AST into the appropriate SQL dialect.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from gaius.bases.dql.ast import (
    Expression,
    BinaryOp,
    UnaryOp,
    Identifier,
    Literal,
    ListLiteral,
)
from gaius.bases.dql.parser import DQLQuery
from gaius.bases.models.base import BaseDefinition, BaseType


@dataclass
class CompiledQuery:
    """Result of compiling DQL to backend-specific query."""

    sql: str
    parameters: dict[str, Any] = field(default_factory=dict)
    backend: str = "postgres"  # postgres, iceberg

    # Iceberg-specific fields (set by IcebergCompiler)
    table_name: str | None = None  # Table name for catalog lookup
    iceberg_filter: str | None = None  # PyIceberg row_filter expression
    iceberg_limit: int | None = None  # Limit for PyIceberg scan

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sql": self.sql,
            "parameters": self.parameters,
            "backend": self.backend,
            "table_name": self.table_name,
            "iceberg_filter": self.iceberg_filter,
            "iceberg_limit": self.iceberg_limit,
        }


class DQLCompiler(ABC):
    """Base class for backend-specific DQL compilers."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Return the backend name."""
        ...

    @abstractmethod
    def compile(self, query: DQLQuery, base: BaseDefinition) -> CompiledQuery:
        """Compile DQL to backend-specific query."""
        ...

    def _compile_expression(self, expr: Expression) -> tuple[str, dict[str, Any]]:
        """Compile expression to SQL fragment and parameters.

        Returns:
            Tuple of (sql_fragment, parameters_dict)
        """
        if isinstance(expr, BinaryOp):
            left_sql, left_params = self._compile_expression(expr.left)
            right_sql, right_params = self._compile_expression(expr.right)

            op = expr.op
            if op in ("AND", "OR"):
                return f"({left_sql} {op} {right_sql})", {**left_params, **right_params}
            elif op == "LIKE":
                return f"{left_sql} LIKE {right_sql}", {**left_params, **right_params}
            elif op == "IN":
                return f"{left_sql} IN {right_sql}", {**left_params, **right_params}
            else:
                return f"{left_sql} {op} {right_sql}", {**left_params, **right_params}

        elif isinstance(expr, UnaryOp):
            operand_sql, operand_params = self._compile_expression(expr.operand)
            return f"NOT ({operand_sql})", operand_params

        elif isinstance(expr, Identifier):
            # Quote identifier to prevent injection
            safe_name = self._quote_identifier(expr.name)
            return safe_name, {}

        elif isinstance(expr, Literal):
            param_name = f"p{id(expr)}"
            return f":{param_name}", {param_name: expr.value}

        elif isinstance(expr, ListLiteral):
            # Compile list for IN operator
            param_names = []
            params = {}
            for i, lit in enumerate(expr.values):
                param_name = f"p{id(expr)}_{i}"
                param_names.append(f":{param_name}")
                params[param_name] = lit.value
            return f"({', '.join(param_names)})", params

        raise ValueError(f"Unknown expression type: {type(expr)}")

    def _quote_identifier(self, name: str) -> str:
        """Quote an identifier safely."""
        # Only allow alphanumeric and underscore
        if not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"Invalid identifier: {name}")
        return f'"{name}"'


class PostgresCompiler(DQLCompiler):
    """Compile DQL to PostgreSQL queries (for registry/metadata bases)."""

    @property
    def backend_name(self) -> str:
        return "postgres"

    def compile(self, query: DQLQuery, base: BaseDefinition) -> CompiledQuery:
        """Compile DQL to PostgreSQL SQL."""
        # Validate table name
        table = base.physical_table
        if not table:
            raise ValueError(f"Base {base.base_id} has no physical_table defined")

        parts = [f"SELECT * FROM {table}"]
        params: dict[str, Any] = {}

        if query.where:
            where_sql, where_params = self._compile_expression(query.where.expression)
            parts.append(f"WHERE {where_sql}")
            params.update(where_params)

        if query.group_by:
            cols = ", ".join(self._quote_identifier(c) for c in query.group_by.columns)
            parts.append(f"GROUP BY {cols}")

        if query.order_by:
            order_parts = [
                f'{self._quote_identifier(spec.column)} {spec.direction}'
                for spec in query.order_by.specs
            ]
            parts.append(f"ORDER BY {', '.join(order_parts)}")

        if query.limit:
            parts.append(f"LIMIT {query.limit.count}")

        return CompiledQuery(
            sql=" ".join(parts),
            parameters=params,
            backend="postgres",
        )


class IcebergCompiler(DQLCompiler):
    """Compile DQL to Iceberg queries (for historical queries with time-travel).

    PyIceberg uses row_filter expressions (string-based filter language)
    for efficient predicate pushdown. This compiler produces both:
    - sql: Human-readable SQL for debugging/logging
    - iceberg_filter: PyIceberg row_filter expression string
    """

    @property
    def backend_name(self) -> str:
        return "iceberg"

    def compile(self, query: DQLQuery, base: BaseDefinition) -> CompiledQuery:
        """Compile DQL to Iceberg query with PyIceberg filter expressions."""
        table = base.physical_table
        if not table:
            raise ValueError(f"Base {base.base_id} has no physical_table defined")

        # Build SQL for logging (human-readable)
        if query.as_of:
            parts = [
                f"SELECT * FROM {table} FOR SYSTEM_TIME AS OF TIMESTAMP '{query.as_of.timestamp}'"
            ]
        else:
            parts = [f"SELECT * FROM {table}"]

        params: dict[str, Any] = {}

        # Build WHERE clause for SQL and iceberg_filter
        where_clauses = []
        iceberg_filters = []

        if query.where:
            where_sql, where_params = self._compile_expression(query.where.expression)
            where_clauses.append(where_sql)
            params.update(where_params)
            # Build PyIceberg filter (substitute params inline)
            iceberg_filter = self._compile_iceberg_filter(query.where.expression)
            iceberg_filters.append(iceberg_filter)

        # Add default time range filter for historical bases (guardrail)
        if not query.as_of and base.base_type == BaseType.HISTORICAL:
            time_filter_sql = self._build_time_filter_sql(base)
            time_filter_iceberg = self._build_time_filter_iceberg(base)
            if time_filter_sql:
                where_clauses.append(time_filter_sql)
            if time_filter_iceberg:
                iceberg_filters.append(time_filter_iceberg)

        if where_clauses:
            combined = " AND ".join(f"({c})" for c in where_clauses)
            parts.append(f"WHERE {combined}")

        if query.group_by:
            cols = ", ".join(self._quote_identifier(c) for c in query.group_by.columns)
            parts.append(f"GROUP BY {cols}")

        if query.order_by:
            order_parts = [
                f'{self._quote_identifier(spec.column)} {spec.direction}'
                for spec in query.order_by.specs
            ]
            parts.append(f"ORDER BY {', '.join(order_parts)}")

        limit_value = query.limit.count if query.limit else None
        if limit_value:
            parts.append(f"LIMIT {limit_value}")

        # Build combined iceberg filter
        iceberg_filter_str = None
        if iceberg_filters:
            iceberg_filter_str = " and ".join(f"({f})" for f in iceberg_filters)

        return CompiledQuery(
            sql=" ".join(parts),
            parameters=params,
            backend="iceberg",
            table_name=table,
            iceberg_filter=iceberg_filter_str,
            iceberg_limit=limit_value,
        )

    def _compile_iceberg_filter(self, expr: Expression) -> str:
        """Compile expression to PyIceberg row_filter string.

        PyIceberg uses a simple expression language:
        - column == 'value'
        - column > 123
        - column >= '2024-01-01'
        - expr1 and expr2
        - expr1 or expr2
        - not expr
        """
        if isinstance(expr, BinaryOp):
            left = self._compile_iceberg_filter(expr.left)
            right = self._compile_iceberg_filter(expr.right)

            op = expr.op
            if op == "AND":
                return f"({left} and {right})"
            elif op == "OR":
                return f"({left} or {right})"
            elif op == "=":
                return f"{left} == {right}"
            elif op == "LIKE":
                # PyIceberg doesn't support LIKE directly, use contains/starts_with
                # Fall back to basic equality for now
                return f"{left} == {right}"
            elif op == "IN":
                # PyIceberg supports IN
                return f"{left} in {right}"
            else:
                # >, <, >=, <=, !=
                return f"{left} {op} {right}"

        elif isinstance(expr, UnaryOp):
            operand = self._compile_iceberg_filter(expr.operand)
            return f"not ({operand})"

        elif isinstance(expr, Identifier):
            return expr.name

        elif isinstance(expr, Literal):
            value = expr.value
            if isinstance(value, str):
                return f"'{value}'"
            elif value is None:
                return "null"
            else:
                return str(value)

        elif isinstance(expr, ListLiteral):
            values = ", ".join(
                f"'{v.value}'" if isinstance(v.value, str) else str(v.value)
                for v in expr.values
            )
            return f"({values})"

        raise ValueError(f"Unknown expression type: {type(expr)}")

    def _build_time_filter_sql(self, base: BaseDefinition) -> str:
        """Build SQL time range filter for historical bases."""
        days = int(base.default_time_range.total_seconds() / 86400)
        return f'"event_time" >= NOW() - INTERVAL \'{days} days\''

    def _build_time_filter_iceberg(self, base: BaseDefinition) -> str:
        """Build PyIceberg time range filter for historical bases."""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - base.default_time_range
        return f"event_time >= '{cutoff.isoformat()}'"


class PinotCompiler(DQLCompiler):
    """Compile DQL to Pinot SQL (for snapshot/online queries)."""

    @property
    def backend_name(self) -> str:
        return "pinot"

    def compile(self, query: DQLQuery, base: BaseDefinition) -> CompiledQuery:
        """Compile DQL to Pinot SQL."""
        table = base.pinot_table or base.physical_table
        if not table:
            raise ValueError(f"Base {base.base_id} has no pinot_table or physical_table defined")

        parts = [f"SELECT * FROM {table}"]
        params: dict[str, Any] = {}

        if query.where:
            where_sql, where_params = self._compile_expression(query.where.expression)
            parts.append(f"WHERE {where_sql}")
            params.update(where_params)

        if query.group_by:
            cols = ", ".join(self._quote_identifier(c) for c in query.group_by.columns)
            parts.append(f"GROUP BY {cols}")

        if query.order_by:
            order_parts = [
                f'{self._quote_identifier(spec.column)} {spec.direction}'
                for spec in query.order_by.specs
            ]
            parts.append(f"ORDER BY {', '.join(order_parts)}")

        if query.limit:
            parts.append(f"LIMIT {query.limit.count}")
        else:
            # Pinot requires LIMIT for safety
            parts.append("LIMIT 1000")

        return CompiledQuery(
            sql=" ".join(parts),
            parameters=params,
            backend="pinot",
        )


def get_compiler(backend: str) -> DQLCompiler:
    """Get compiler for a backend.

    Args:
        backend: Backend name (postgres, iceberg, pinot)

    Returns:
        DQLCompiler instance

    Raises:
        ValueError: If backend is not supported
    """
    compilers = {
        "postgres": PostgresCompiler,
        "iceberg": IcebergCompiler,
        "pinot": PinotCompiler,
    }

    if backend not in compilers:
        raise ValueError(f"Unknown backend: {backend}. Supported: {list(compilers.keys())}")

    return compilers[backend]()
