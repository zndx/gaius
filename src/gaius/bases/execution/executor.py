"""Query executor for Bases feature store.

Routes queries to the appropriate backend (PostgreSQL + kudu_fdw when available,
or Iceberg for HISTORICAL bases) and handles result transformation.

Guru Meditation Codes:
- #BASES.00000001.NOPOOL - Database pool not configured
- #BASES.00000002.NOICEBERG - Iceberg catalog not configured
- #BASES.00000006.ICEBERGTABLE - Iceberg table not found
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog

from gaius.bases.fluent.compiler import CompiledQuery
from gaius.bases.models.base import BaseDefinition, BaseType
from gaius.bases.models.schema import ColumnSchema, QueryResult
from gaius.bases.models.types import TypeConverter, KuduDataType

logger = logging.getLogger(__name__)


@dataclass
class ExecutorConfig:
    """Configuration for query executor."""

    # PostgreSQL connection pool
    db_pool: Any = None

    # Iceberg catalog (PyIceberg) - required for HISTORICAL bases
    iceberg_catalog: "Catalog | None" = None

    # Iceberg namespace
    iceberg_namespace: str = "gaius"


class QueryExecutor:
    """Execute queries against backends.

    Routes queries to the appropriate backend:
    - PostgreSQL (+ kudu_fdw when available) for SNAPSHOT bases
    - Iceberg for HISTORICAL bases
    """

    def __init__(self, config: ExecutorConfig):
        self.config = config

    async def execute_sql(
        self,
        sql: str,
        parameters: dict[str, Any],
        base: BaseDefinition,
        timeout_ms: int = 30000,
    ) -> QueryResult:
        """Execute a SQL query against the appropriate backend.

        This is the primary entry point for query execution, called by
        BasesService after fluent query compilation via SQLGlot.

        Args:
            sql: SQL query string (dialect-appropriate)
            parameters: Query parameters (named, e.g., :param_name)
            base: Base definition for schema information and backend routing
            timeout_ms: Query timeout in milliseconds

        Returns:
            QueryResult with columns, rows, and metadata

        Raises:
            ExecutionError: If query execution fails
        """
        start_time = time.monotonic()

        try:
            # Route based on base type
            if base.base_type == BaseType.HISTORICAL:
                # Historical bases use Iceberg
                rows = await self._execute_iceberg_sql(sql, parameters, base, timeout_ms)
                backend = "iceberg"
            else:
                # Snapshot and registry bases use PostgreSQL (+ kudu_fdw later)
                rows = await self._execute_postgres_sql(sql, parameters, timeout_ms)
                backend = "postgres"

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            # Build column schema from base definition
            columns = [ColumnSchema.from_dict(c) for c in base.schema]

            # Coerce row values to match Kudu type expectations
            coerced_rows = self._coerce_rows(rows, columns)

            # Check if results were truncated by LIMIT
            truncated = False
            if "LIMIT" in sql.upper():
                match = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
                if match:
                    limit = int(match.group(1))
                    truncated = len(coerced_rows) >= limit

            return QueryResult(
                columns=columns,
                rows=coerced_rows,
                row_count=len(coerced_rows),
                truncated=truncated,
                query_time_ms=elapsed_ms,
                backend=backend,
            )

        except ExecutionError:
            raise
        except Exception as e:
            logger.exception(f"Query execution failed: {sql}")
            raise ExecutionError(f"Query execution failed: {e}") from e

    async def execute(
        self,
        compiled: CompiledQuery,
        base: BaseDefinition,
        timeout_ms: int = 30000,
    ) -> QueryResult:
        """Execute a compiled query (legacy interface).

        Prefer execute_sql() for new code.

        Args:
            compiled: Compiled query with SQL and parameters
            base: Base definition for schema information
            timeout_ms: Query timeout in milliseconds

        Returns:
            QueryResult with rows and metadata
        """
        return await self.execute_sql(
            compiled.sql,
            compiled.parameters,
            base,
            timeout_ms,
        )

    async def _execute_postgres_sql(
        self,
        sql: str,
        parameters: dict[str, Any],
        timeout_ms: int,
    ) -> list[dict[str, Any]]:
        """Execute SQL query against PostgreSQL (or kudu_fdw when available).

        Args:
            sql: SQL query string
            parameters: Named parameters dict
            timeout_ms: Query timeout in milliseconds

        Returns:
            List of row dictionaries

        Raises:
            ExecutionError: If database pool not configured or query fails
        """
        if self.config.db_pool is None:
            raise ExecutionError(
                "[#BASES.00000001.NOPOOL] Database pool not configured. "
                "Ensure BasesService is initialized with a db_pool."
            )

        async with self.config.db_pool.acquire() as conn:
            # Set statement timeout
            await conn.execute(f"SET statement_timeout = {timeout_ms}")

            # Convert named parameters to positional for asyncpg
            converted_sql, values = self._convert_params_asyncpg(sql, parameters)

            try:
                records = await conn.fetch(converted_sql, *values)
                return [dict(r) for r in records]
            finally:
                # Reset statement timeout
                await conn.execute("RESET statement_timeout")

    async def _execute_iceberg_sql(
        self,
        sql: str,
        parameters: dict[str, Any],
        base: BaseDefinition,
        timeout_ms: int,
    ) -> list[dict[str, Any]]:
        """Execute query against Iceberg via PyIceberg.

        Uses PyIceberg's scan API. For simple queries, we parse the SQL to
        extract filter conditions and limits. Complex queries may require
        DuckDB or Trino integration in the future.

        Args:
            sql: SQL query string
            parameters: Named parameters dict (currently unused for Iceberg)
            base: Base definition with table name
            timeout_ms: Query timeout (note: PyIceberg doesn't support timeouts directly)

        Returns:
            List of row dictionaries

        Raises:
            ExecutionError: If catalog not configured or table not found
        """
        if self.config.iceberg_catalog is None:
            raise ExecutionError(
                "[#BASES.00000002.NOICEBERG] Iceberg catalog not configured.\n"
                "  Historical bases require Iceberg catalog.\n"
                "  Configure: BasesConfig(iceberg_enabled=True) with iceberg_catalog"
            )

        try:
            # Get table name from base definition
            table_name = base.physical_table or base.base_id
            if not table_name:
                # Fall back to parsing from SQL
                match = re.search(r"FROM\s+(\S+)", sql, re.IGNORECASE)
                if match:
                    table_name = match.group(1)
                else:
                    raise ExecutionError(
                        "[#BASES.00000006.ICEBERGTABLE] Could not determine table name"
                    )

            # Load table from catalog
            namespace = self.config.iceberg_namespace
            try:
                table = self.config.iceberg_catalog.load_table(f"{namespace}.{table_name}")
            except Exception as e:
                raise ExecutionError(
                    f"[#BASES.00000006.ICEBERGTABLE] Table not found: {namespace}.{table_name}\n"
                    f"  Error: {e}"
                ) from e

            # Build scan with limit if present in SQL
            scan_kwargs: dict[str, Any] = {}

            # Extract LIMIT from SQL
            limit_match = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
            if limit_match:
                scan_kwargs["limit"] = int(limit_match.group(1))

            # TODO: Parse WHERE clause to Iceberg row_filter for better pushdown
            # For now, we fetch all rows and filter in Python (not ideal for large tables)

            # Execute scan
            scan = table.scan(**scan_kwargs)

            # Convert Arrow table to list of dicts
            arrow_table = scan.to_arrow()
            rows: list[dict[str, Any]] = []

            for i in range(arrow_table.num_rows):
                row = {
                    col: arrow_table.column(col)[i].as_py()
                    for col in arrow_table.column_names
                }
                rows.append(row)

            logger.debug(f"Iceberg query returned {len(rows)} rows from {table_name}")
            return rows

        except ExecutionError:
            raise
        except Exception as e:
            raise ExecutionError(
                f"[#BASES.00000002.NOICEBERG] Iceberg query failed: {e}"
            ) from e

    def _coerce_rows(
        self,
        rows: list[dict[str, Any]],
        columns: list[ColumnSchema],
    ) -> list[dict[str, Any]]:
        """Coerce row values to match Kudu type expectations.

        Ensures type consistency between database results and Kudu types.
        Handles PostgreSQL → Kudu type conversions.

        Args:
            rows: Raw rows from database
            columns: Column schema with Kudu types

        Returns:
            Rows with coerced values
        """
        if not rows or not columns:
            return rows

        # Build column type map
        type_map: dict[str, KuduDataType] = {}
        for col in columns:
            try:
                type_map[col.name] = col.kudu_type
            except ValueError:
                # Unknown type - skip coercion for this column
                logger.warning(f"Unknown type for column {col.name}: {col.data_type}")

        # Coerce each row
        coerced: list[dict[str, Any]] = []
        for row in rows:
            coerced_row: dict[str, Any] = {}
            for key, value in row.items():
                if key in type_map:
                    try:
                        coerced_row[key] = TypeConverter.coerce_value(value, type_map[key])
                    except Exception as e:
                        logger.debug(f"Coercion failed for {key}={value}: {e}")
                        coerced_row[key] = value  # Keep original on failure
                else:
                    coerced_row[key] = value
            coerced.append(coerced_row)

        return coerced

    def _convert_params_asyncpg(
        self,
        sql: str,
        params: dict[str, Any],
    ) -> tuple[str, list[Any]]:
        """Convert named parameters to positional ($1, $2, etc.) for asyncpg.

        Args:
            sql: SQL with :param_name placeholders
            params: Dictionary of parameter values

        Returns:
            Tuple of (sql_with_positional_params, ordered_values)
        """
        if not params:
            return sql, []

        # Find all :param_name patterns
        import re
        pattern = re.compile(r":(\w+)")
        matches = list(pattern.finditer(sql))

        # Build ordered parameter list
        values: list[Any] = []
        param_positions: dict[str, int] = {}

        result_sql = sql
        for match in reversed(matches):  # Reverse to preserve positions
            param_name = match.group(1)

            if param_name not in param_positions:
                param_positions[param_name] = len(values) + 1
                if param_name in params:
                    values.append(params[param_name])
                else:
                    raise ExecutionError(f"Missing parameter: {param_name}")

            pos = param_positions[param_name]
            result_sql = result_sql[:match.start()] + f"${pos}" + result_sql[match.end():]

        # Values were added in reverse order, so reverse back
        values.reverse()

        return result_sql, values


class ExecutionError(Exception):
    """Exception raised when query execution fails."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
