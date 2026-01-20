"""Query executor for Bases feature store.

Routes compiled queries to the appropriate backend and handles
result transformation.

Guru Meditation Codes:
- #BASES.00000001.NOPOOL - Database pool not configured
- #BASES.00000002.NOICEBERG - Iceberg catalog not configured
- #BASES.00000006.ICEBERGTABLE - Iceberg table not found
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog

from gaius.bases.dql.compiler import CompiledQuery
from gaius.bases.models.base import BaseDefinition, BaseType
from gaius.bases.models.schema import ColumnSchema, QueryResult

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
    """Execute compiled queries against backends.

    Routes queries to the appropriate backend (PostgreSQL, Iceberg, Pinot)
    and transforms results into a common format.
    """

    def __init__(self, config: ExecutorConfig):
        self.config = config

    async def execute(
        self,
        compiled: CompiledQuery,
        base: BaseDefinition,
        timeout_ms: int = 30000,
    ) -> QueryResult:
        """Execute a compiled query.

        Args:
            compiled: Compiled query with SQL and parameters
            base: Base definition for schema information
            timeout_ms: Query timeout in milliseconds

        Returns:
            QueryResult with rows and metadata

        Raises:
            ExecutionError: If query execution fails
        """
        start_time = time.monotonic()

        try:
            if compiled.backend == "postgres":
                rows = await self._execute_postgres(compiled, timeout_ms)
            elif compiled.backend == "iceberg":
                rows = await self._execute_iceberg(compiled, timeout_ms)
            elif compiled.backend == "pinot":
                rows = await self._execute_pinot(compiled, timeout_ms)
            else:
                raise ExecutionError(f"Unknown backend: {compiled.backend}")

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            # Build column schema from base definition
            columns = [ColumnSchema.from_dict(c) for c in base.schema]

            # Check if results were truncated by LIMIT
            # (We can't know for sure without COUNT, but we can infer)
            truncated = False
            if "LIMIT" in compiled.sql.upper():
                # Parse limit from SQL (simplified)
                import re
                match = re.search(r"LIMIT\s+(\d+)", compiled.sql, re.IGNORECASE)
                if match:
                    limit = int(match.group(1))
                    truncated = len(rows) >= limit

            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                query_time_ms=elapsed_ms,
                backend=compiled.backend,
            )

        except Exception as e:
            logger.exception(f"Query execution failed: {compiled.sql}")
            raise ExecutionError(f"Query execution failed: {e}") from e

    async def _execute_postgres(
        self,
        compiled: CompiledQuery,
        timeout_ms: int,
    ) -> list[dict[str, Any]]:
        """Execute query against PostgreSQL."""
        if self.config.db_pool is None:
            raise ExecutionError(
                "[#BASES.00000001.NOPOOL] Database pool not configured. "
                "Ensure BasesService is initialized with a db_pool."
            )

        async with self.config.db_pool.acquire() as conn:
            # Set statement timeout
            await conn.execute(f"SET statement_timeout = {timeout_ms}")

            # Convert named parameters to positional for asyncpg
            sql, values = self._convert_params_asyncpg(compiled.sql, compiled.parameters)

            try:
                records = await conn.fetch(sql, *values)
                return [dict(r) for r in records]
            finally:
                # Reset statement timeout
                await conn.execute("RESET statement_timeout")

    async def _execute_iceberg(
        self,
        compiled: CompiledQuery,
        timeout_ms: int,
    ) -> list[dict[str, Any]]:
        """Execute query against Iceberg via PyIceberg.

        Uses PyIceberg's scan API with row filters and limit.
        Converts Arrow results to list of dicts.

        Args:
            compiled: Compiled query (contains iceberg_filter and iceberg_limit)
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
            # Extract table name from compiled query
            # Table name is stored in compiled.table_name (set by compiler)
            table_name = getattr(compiled, "table_name", None)
            if not table_name:
                # Fall back to parsing from SQL (SELECT ... FROM table_name ...)
                import re
                match = re.search(r"FROM\s+(\S+)", compiled.sql, re.IGNORECASE)
                if match:
                    table_name = match.group(1)
                else:
                    raise ExecutionError(
                        "[#BASES.00000006.ICEBERGTABLE] Could not determine table name from query"
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

            # Build scan with filter and limit
            scan_kwargs: dict[str, Any] = {}

            # Apply row filter if present
            iceberg_filter = getattr(compiled, "iceberg_filter", None)
            if iceberg_filter:
                scan_kwargs["row_filter"] = iceberg_filter

            # Apply limit if present
            iceberg_limit = getattr(compiled, "iceberg_limit", None)
            if iceberg_limit:
                scan_kwargs["limit"] = iceberg_limit

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
