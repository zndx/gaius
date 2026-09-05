"""BasesService - Engine-First service for the feature store.

Follows the BaseDaemon pattern for integration with gaius-engine gRPC server.

Guru Meditation Codes:
- #BASES.00000001.NOPOOL - Database pool not configured
- #BASES.00000002.NOICEBERG - Iceberg catalog not configured
- #BASES.00000003.NOPINOT - Pinot broker not configured
- #BASES.00000004.STARTFAIL - Service failed to start
- #BASES.00000005.QUERYFAIL - Query execution failed
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

from gaius.bases.fluent import FluentCompiler, parse_fluent, BaseQuery
from gaius.bases.execution.guardrails import QueryGuardrails, GuardrailEnforcer
from gaius.bases.execution.executor import QueryExecutor, ExecutorConfig
from gaius.bases.models.base import BaseDefinition, BaseType
from gaius.bases.models.schema import BaseInfo, QueryResult, EntityHistoryResult
from gaius.bases.registry.client import RegistryClient

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class BasesConfig:
    """Configuration for BasesService."""

    # Guardrails
    guardrails: QueryGuardrails = field(default_factory=QueryGuardrails)

    # Iceberg configuration (required for HISTORICAL bases)
    iceberg_enabled: bool = True  # Default to enabled - fail-fast if not configured
    iceberg_namespace: str = "gaius"  # Iceberg namespace for bases tables

    # Pinot is roadmap-only
    pinot_enabled: bool = False  # Intentionally disabled - roadmap only

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "guardrails": self.guardrails.to_dict(),
            "iceberg_enabled": self.iceberg_enabled,
            "iceberg_namespace": self.iceberg_namespace,
            "pinot_enabled": self.pinot_enabled,
        }


class BasesService:
    """BasesService for Engine-First architecture.

    Provides the core feature store operations:
    - list_bases(): List available bases
    - query_base(): Execute DQL queries
    - get_entity_history(): Get event history for an entity

    Integrates with the gRPC servicer for remote access.
    """

    def __init__(
        self,
        config: BasesConfig,
        db_pool: Any = None,
    ):
        """Initialize BasesService.

        Args:
            config: Service configuration
            db_pool: asyncpg connection pool (required)
        """
        self.config = config
        self._db_pool = db_pool

        # Components (initialized lazily or in start())
        self._registry: RegistryClient | None = None
        self._executor: QueryExecutor | None = None
        self._guardrail_enforcer: GuardrailEnforcer | None = None

        # State
        self._running = False
        self._started_at: datetime | None = None

        # Statistics
        self._query_count = 0
        self._error_count = 0

        logger.info("BasesService initialized")

    @property
    def name(self) -> str:
        """Service name."""
        return "bases"

    @property
    def is_running(self) -> bool:
        """Whether the service is running."""
        return self._running

    async def start(self) -> None:
        """Start the BasesService.

        Initializes registry client and query executor.
        """
        if self._running:
            logger.warning("BasesService already running")
            return

        if self._db_pool is None:
            raise RuntimeError(
                "[#BASES.00000001.NOPOOL] Database pool not configured. "
                "BasesService requires a db_pool for registry access."
            )

        # Initialize registry client
        self._registry = RegistryClient(self._db_pool)

        # Initialize guardrail enforcer
        self._guardrail_enforcer = GuardrailEnforcer(self.config.guardrails)

        # Initialize Iceberg catalog (required - PyIceberg is a hard dependency)
        iceberg_catalog = None
        if self.config.iceberg_enabled:
            try:
                from gaius.hx.catalog import get_catalog
                iceberg_catalog = get_catalog()
                logger.info("Iceberg catalog initialized from gaius.hx")
            except Exception as e:
                # PyIceberg is a hard requirement - fail fast on init
                raise RuntimeError(
                    f"[#BASES.00000002.NOICEBERG] Iceberg catalog initialization failed: {e}\n"
                    "  PyIceberg is a hard requirement. Check:\n"
                    "  1. PostgreSQL is running (catalog metadata store)\n"
                    "  2. RustFS (Signals, 127.0.0.1:9010) is running (data file storage)\n"
                    "  3. HX config is correct in gaius.hx.config"
                ) from e

        # Initialize executor
        executor_config = ExecutorConfig(
            db_pool=self._db_pool,
            iceberg_catalog=iceberg_catalog,
            iceberg_namespace=self.config.iceberg_namespace,
        )
        self._executor = QueryExecutor(executor_config)

        self._running = True
        self._started_at = datetime.now()

        logger.info("BasesService started")

    async def stop(self) -> None:
        """Stop the BasesService."""
        if not self._running:
            return

        self._running = False
        self._registry = None
        self._executor = None

        logger.info("BasesService stopped")

    async def health_check(self) -> dict[str, Any]:
        """Check service health.

        Returns:
            Health status dict
        """
        if not self._running:
            return {
                "healthy": False,
                "message": "BasesService not running",
                "guru_code": "#BASES.00000004.STARTFAIL",
            }

        return {
            "healthy": True,
            "message": "BasesService operational",
            "details": {
                "query_count": self._query_count,
                "error_count": self._error_count,
                "uptime_seconds": (
                    (datetime.now() - self._started_at).total_seconds()
                    if self._started_at
                    else 0
                ),
                "iceberg_enabled": self.config.iceberg_enabled,
                "pinot_enabled": self.config.pinot_enabled,
            },
        }

    # =========================================================================
    # MCP-facing Operations
    # =========================================================================

    async def list_bases(
        self,
        base_type: str = "all",
        tags: list[str] | None = None,
    ) -> list[BaseInfo]:
        """List available bases.

        Args:
            base_type: Filter by type ("snapshot", "historical", "registry", "all")
            tags: Filter by tags (matches if base has ANY of the tags)

        Returns:
            List of BaseInfo objects
        """
        if not self._registry:
            raise RuntimeError("[#BASES.00000001.NOPOOL] Service not started")

        return await self._registry.list_bases(base_type, tags)

    async def query_base(
        self,
        base_name: str,
        dql: str | None = None,
        fluent: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a query against a base.

        Supports both fluent syntax (preferred) and legacy DQL-style strings.

        Args:
            base_name: Name of the base to query
            dql: Legacy DQL-style query string (WHERE, ORDER BY, etc.)
            fluent: Fluent query string like 'where(col("x") > 1).limit(10)'
            options: Additional options:
                - timeout_ms: Query timeout
                - max_rows: Override default LIMIT
                - include_metadata: Include _metadata column

        Returns:
            QueryResult with columns, rows, and metadata
        """
        if not self._registry or not self._executor or not self._guardrail_enforcer:
            raise RuntimeError("[#BASES.00000001.NOPOOL] Service not started")

        options = options or {}
        start_time = datetime.now()

        try:
            # Get base definition
            base = await self._registry.get_base(base_name)

            # Build query from fluent or DQL
            if fluent:
                # Parse fluent expression as method chain on base
                full_expr = f'Base("{base_name}").{fluent}'
                query = parse_fluent(full_expr)
            elif dql:
                # Convert simple DQL to fluent query
                query = self._dql_to_fluent(base_name, dql)
            else:
                # No filter - select all
                from gaius.bases.fluent import Base
                query = Base(base_name)

            # Apply guardrails (limit, etc.)
            query = self._apply_guardrails(query, base, options)

            # Get timeout
            timeout_ms = self._guardrail_enforcer.validate_timeout(
                options.get("timeout_ms")
            )

            # Compile using SQLGlot
            compiler = FluentCompiler(dialect="postgres")
            compiled = compiler.compile(query, base)

            # Execute
            result = await self._executor.execute_sql(
                compiled.sql,
                compiled.parameters,
                base,
                timeout_ms,
            )

            # Update stats
            self._query_count += 1

            # Log query for audit
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            await self._registry.log_query(
                base_id=base_name,
                dql_query=fluent or dql or "",
                compiled_sql=compiled.sql,
                backend="postgres",  # Kudu via FDW when available
                duration_ms=duration_ms,
                rows_returned=result.row_count,
                client_id=options.get("client_id"),
                error=None,
            )

            return result

        except Exception as e:
            self._error_count += 1
            logger.exception(f"Query failed: {base_name}")

            # Log error
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            if self._registry:
                try:
                    await self._registry.log_query(
                        base_id=base_name,
                        dql_query=fluent or dql or "",
                        compiled_sql=None,
                        backend="unknown",
                        duration_ms=duration_ms,
                        rows_returned=0,
                        client_id=options.get("client_id") if options else None,
                        error=str(e),
                    )
                except Exception:
                    pass  # Don't fail on audit log error

            raise

    async def execute_fluent(self, query: BaseQuery) -> QueryResult:
        """Execute a fluent query object.

        Called by BaseQuery.scan() method.

        Args:
            query: Fluent query object

        Returns:
            QueryResult with columns, rows, and metadata
        """
        if not self._registry or not self._executor or not self._guardrail_enforcer:
            raise RuntimeError("[#BASES.00000001.NOPOOL] Service not started")

        start_time = datetime.now()
        base_name = query._base_name

        try:
            # Get base definition
            base = await self._registry.get_base(base_name)

            # Apply guardrails
            query = self._apply_guardrails(query, base, {})

            # Get timeout
            timeout_ms = self._guardrail_enforcer.validate_timeout(None)

            # Compile using SQLGlot
            compiler = FluentCompiler(dialect="postgres")
            compiled = compiler.compile(query, base)

            # Execute
            result = await self._executor.execute_sql(
                compiled.sql,
                compiled.parameters,
                base,
                timeout_ms,
            )

            # Update stats
            self._query_count += 1

            # Log query for audit
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            await self._registry.log_query(
                base_id=base_name,
                dql_query=str(query.to_dict()),
                compiled_sql=compiled.sql,
                backend="postgres",
                duration_ms=duration_ms,
                rows_returned=result.row_count,
                client_id=None,
                error=None,
            )

            return result

        except Exception as e:
            self._error_count += 1
            logger.exception(f"Fluent query failed: {base_name}")
            raise

    def _dql_to_fluent(self, base_name: str, dql: str) -> BaseQuery:
        """Convert a simple DQL string to a fluent query.

        Handles basic patterns like:
            WHERE x > 1 ORDER BY y DESC LIMIT 10

        For complex queries, use the fluent API directly.
        """
        from gaius.bases.fluent import Base, col
        import re

        query = Base(base_name)

        # Simple parsing - production would use a proper parser
        dql_upper = dql.upper()

        # Extract LIMIT
        limit_match = re.search(r'LIMIT\s+(\d+)', dql_upper)
        if limit_match:
            query = query.limit(int(limit_match.group(1)))

        # Extract ORDER BY (simple case)
        order_match = re.search(r'ORDER\s+BY\s+(\w+)(?:\s+(ASC|DESC))?', dql_upper)
        if order_match:
            col_name = order_match.group(1).lower()
            desc = order_match.group(2) == "DESC" if order_match.group(2) else False
            query = query.order_by(col_name, desc=desc)

        # For WHERE clauses, we'd need more sophisticated parsing
        # For now, just log that complex WHERE should use fluent API
        if 'WHERE' in dql_upper:
            logger.warning(
                "DQL WHERE clauses are deprecated. Use fluent API: "
                "Base('name').where(col('x') > 1)"
            )

        return query

    def _apply_guardrails(
        self,
        query: BaseQuery,
        base: BaseDefinition,
        options: dict[str, Any],
    ) -> BaseQuery:
        """Apply guardrails to a fluent query.

        Ensures queries have appropriate limits and validates constraints.
        """
        if not self._guardrail_enforcer:
            return query

        # Get effective limit
        effective_limit = self._guardrail_enforcer.get_effective_limit(
            query._limit_value,
            options,
        )

        # Apply limit if not set or if clamped
        if query._limit_value is None or query._limit_value > effective_limit:
            query = query.limit(effective_limit)

        return query

    async def get_entity_history(
        self,
        entity_id: str,
        entity_type: str | None = None,
        base_name: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> EntityHistoryResult:
        """Get event-sourced history for an entity.

        Args:
            entity_id: The entity identifier
            entity_type: Entity type (required if base_name not provided)
            base_name: Specific historical base to query
            options: Additional options:
                - time_range: Tuple of (start, end) datetime
                - max_events: Maximum events to return
                - include_deleted: Include DELETE operations

        Returns:
            EntityHistoryResult with event history
        """
        if not self._registry:
            raise RuntimeError("[#BASES.00000001.NOPOOL] Service not started")

        options = options or {}

        # Find the historical base for this entity type
        if base_name:
            base = await self._registry.get_base(base_name)
            if base.base_type != BaseType.HISTORICAL:
                raise ValueError(f"Base {base_name} is not a historical base")
            entity_type = base.source_entity_type
        elif entity_type:
            # Find default historical base for entity type
            bases = await self._registry.list_bases(base_type="historical")
            matching = [b for b in bases if b.entity_type == entity_type]
            if not matching:
                raise ValueError(f"No historical base found for entity type: {entity_type}")
            base_name = matching[0].name
            base = await self._registry.get_base(base_name)
        else:
            raise ValueError("Either entity_type or base_name is required")

        # Build DQL query for this entity
        max_events = options.get("max_events", 1000)
        dql = f'WHERE entity_id = "{entity_id}" ORDER BY event_time DESC LIMIT {max_events}'

        # Handle time range
        time_range = options.get("time_range")
        if time_range:
            start, end = time_range
            if isinstance(start, str):
                dql = f'WHERE entity_id = "{entity_id}" AND event_time >= "{start}" AND event_time <= "{end}" ORDER BY event_time DESC LIMIT {max_events}'
            else:
                dql = f'WHERE entity_id = "{entity_id}" AND event_time >= "{start.isoformat()}" AND event_time <= "{end.isoformat()}" ORDER BY event_time DESC LIMIT {max_events}'

        # Execute query
        result = await self.query_base(base_name, dql=dql, options=options)

        # Transform to EntityHistoryResult
        events = result.rows
        if not options.get("include_deleted", False):
            events = [e for e in events if e.get("operation") != "DELETE"]

        # Determine actual time range from results
        actual_range = None
        if events:
            times = [e.get("event_time") for e in events if e.get("event_time")]
            if times:
                actual_range = (min(times), max(times))

        return EntityHistoryResult(
            entity_id=entity_id,
            entity_type=entity_type or "",
            events=events,
            total_events=len(events),
            time_range=actual_range,
        )

    def _select_backend(self, base: BaseDefinition) -> str:
        """Select the appropriate backend for a base.

        Fail-fast policy:
        - REGISTRY → PostgreSQL (always available)
        - HISTORICAL → Iceberg (required, no fallback)
        - SNAPSHOT → Pinot is roadmap-only, PostgreSQL for now

        Args:
            base: Base definition

        Returns:
            Backend name (postgres, iceberg)

        Raises:
            RuntimeError: If required backend not available
        """
        if base.base_type == BaseType.REGISTRY:
            return "postgres"

        elif base.base_type == BaseType.HISTORICAL:
            # HISTORICAL bases require Iceberg - no fallback
            if not self.config.iceberg_enabled:
                raise RuntimeError(
                    f"[#BASES.00000002.NOICEBERG] Historical base '{base.base_id}' requires Iceberg.\n"
                    "  Iceberg must be enabled for event-sourced historical queries.\n"
                    "  Configure: iceberg_enabled=True with iceberg_catalog_uri"
                )
            return "iceberg"

        elif base.base_type == BaseType.SNAPSHOT:
            # Kudu is the target - use PostgreSQL as stub until kudu_fdw available
            # Pinot is roadmap-only and intentionally disabled
            if self.config.pinot_enabled:
                raise RuntimeError(
                    f"[#BASES.00000003.NOPINOT] Pinot backend is roadmap-only.\n"
                    f"  Base '{base.base_id}' cannot use Pinot - not yet implemented.\n"
                    f"  Using PostgreSQL stub until kudu_fdw is available."
                )
            return "postgres"

        else:
            return "postgres"


# Module-level singleton for direct imports
_bases_service: BasesService | None = None


def get_bases_service(config: BasesConfig | None = None, db_pool: Any = None) -> BasesService:
    """Get or create BasesService singleton.

    Args:
        config: Optional config (only used on first call)
        db_pool: Database pool (only used on first call)

    Returns:
        BasesService instance
    """
    global _bases_service
    if _bases_service is None:
        _bases_service = BasesService(config or BasesConfig(), db_pool)
    return _bases_service


async def reset_bases_service() -> None:
    """Reset BasesService singleton (for testing)."""
    global _bases_service
    if _bases_service:
        await _bases_service.stop()
    _bases_service = None
