"""Registry client for Bases feature store.

Manages base definitions, feature groups, and entity types stored in PostgreSQL.
"""

import json
import logging
from datetime import timedelta
from typing import Any

from gaius.bases.models.base import BaseDefinition, BaseType
from gaius.bases.models.feature import EntityType, FeatureGroup, Feature
from gaius.bases.models.schema import BaseInfo, ColumnSchema

logger = logging.getLogger(__name__)


def _parse_json_column(value: Any) -> Any:
    """Parse JSONB column that may come as string or native type."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class RegistryClient:
    """Client for the Bases registry (PostgreSQL).

    Provides CRUD operations for base definitions, feature groups, and entity types.
    """

    def __init__(self, db_pool: Any):
        """Initialize registry client.

        Args:
            db_pool: asyncpg connection pool
        """
        self._pool = db_pool

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
        async with self._pool.acquire() as conn:
            # Build query
            query = """
                SELECT
                    base_id, display_name, description, base_type,
                    schema, source_entity_type, source_feature_groups,
                    default_dql, tags
                FROM bases.bases
                WHERE 1=1
            """
            params: list[Any] = []

            if base_type and base_type != "all":
                params.append(base_type)
                query += f" AND base_type = ${len(params)}"

            if tags:
                params.append(tags)
                query += f" AND tags && ${len(params)}"

            query += " ORDER BY base_id"

            rows = await conn.fetch(query, *params)

            result = []
            for row in rows:
                schema_data = _parse_json_column(row["schema"]) or []
                result.append(BaseInfo(
                    name=row["base_id"],
                    display_name=row["display_name"],
                    description=row["description"],
                    base_type=row["base_type"],
                    schema=[ColumnSchema.from_dict(c) for c in schema_data],
                    entity_type=row["source_entity_type"],
                    feature_groups=row["source_feature_groups"] or [],
                    default_dql=row["default_dql"],
                    tags=row["tags"] or [],
                ))
            return result

    async def get_base(self, base_id: str) -> BaseDefinition:
        """Get a base definition by ID.

        Args:
            base_id: Base identifier

        Returns:
            BaseDefinition

        Raises:
            ValueError: If base not found
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM bases.bases
                WHERE base_id = $1
                """,
                base_id,
            )

            if row is None:
                raise ValueError(f"Base not found: {base_id}")

            return self._row_to_base_definition(dict(row))

    async def create_base(self, base: BaseDefinition) -> BaseDefinition:
        """Create a new base definition.

        Args:
            base: BaseDefinition to create

        Returns:
            Created BaseDefinition with timestamps
        """
        async with self._pool.acquire() as conn:
            import json

            row = await conn.fetchrow(
                """
                INSERT INTO bases.bases (
                    base_id, display_name, description, base_type,
                    schema, context, source_entity_type, source_feature_groups,
                    physical_table, kudu_table, default_dql,
                    default_time_range, max_time_range, read_acl,
                    owner, tags
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16
                )
                RETURNING *
                """,
                base.base_id,
                base.display_name,
                base.description,
                base.base_type.value,
                json.dumps(base.schema),
                json.dumps(base.context) if base.context else "{}",
                base.source_entity_type,
                base.source_feature_groups,
                base.physical_table,
                base.kudu_table,
                base.default_dql,
                base.default_time_range,
                base.max_time_range,
                base.read_acl,
                base.owner,
                base.tags,
            )

            return self._row_to_base_definition(dict(row))

    async def list_entity_types(self) -> list[EntityType]:
        """List all entity types."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM bases.entity_types ORDER BY entity_type_id
                """
            )
            return [EntityType.from_row(dict(r)) for r in rows]

    async def get_entity_type(self, entity_type_id: str) -> EntityType:
        """Get an entity type by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM bases.entity_types WHERE entity_type_id = $1
                """,
                entity_type_id,
            )
            if row is None:
                raise ValueError(f"Entity type not found: {entity_type_id}")
            return EntityType.from_row(dict(row))

    async def list_feature_groups(
        self,
        entity_type_id: str | None = None,
    ) -> list[FeatureGroup]:
        """List feature groups.

        Args:
            entity_type_id: Optional filter by entity type
        """
        async with self._pool.acquire() as conn:
            if entity_type_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM bases.feature_groups
                    WHERE entity_type_id = $1
                    ORDER BY group_id
                    """,
                    entity_type_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM bases.feature_groups ORDER BY group_id
                    """
                )
            return [FeatureGroup.from_row(dict(r)) for r in rows]

    async def list_features(
        self,
        group_id: str | None = None,
        status: str = "active",
    ) -> list[Feature]:
        """List features.

        Args:
            group_id: Optional filter by group
            status: Filter by status (default "active")
        """
        async with self._pool.acquire() as conn:
            query = "SELECT * FROM bases.features WHERE status = $1"
            params: list[Any] = [status]

            if group_id:
                params.append(group_id)
                query += f" AND group_id = ${len(params)}"

            query += " ORDER BY feature_id"

            rows = await conn.fetch(query, *params)
            return [Feature.from_row(dict(r)) for r in rows]

    async def log_query(
        self,
        base_id: str,
        dql_query: str,
        compiled_sql: str | None,
        backend: str,
        duration_ms: int,
        rows_returned: int,
        client_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Log a query execution for audit.

        Args:
            base_id: Base that was queried
            dql_query: Original DQL query
            compiled_sql: Compiled backend SQL
            backend: Backend used (postgres, iceberg, pinot)
            duration_ms: Query duration in milliseconds
            rows_returned: Number of rows returned
            client_id: Optional MCP client identifier
            error: Error message if query failed
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bases.query_log (
                    base_id, dql_query, compiled_sql, backend,
                    duration_ms, rows_returned, client_id, error
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                base_id,
                dql_query,
                compiled_sql,
                backend,
                duration_ms,
                rows_returned,
                client_id,
                error,
            )

    def _row_to_base_definition(self, row: dict[str, Any]) -> BaseDefinition:
        """Convert database row to BaseDefinition."""
        # Handle interval conversion
        default_time_range = row.get("default_time_range")
        if isinstance(default_time_range, timedelta):
            pass
        elif default_time_range is None:
            default_time_range = timedelta(days=7)
        else:
            # Assume seconds
            default_time_range = timedelta(seconds=float(default_time_range))

        max_time_range = row.get("max_time_range")
        if isinstance(max_time_range, timedelta):
            pass
        elif max_time_range is None:
            max_time_range = timedelta(days=90)
        else:
            max_time_range = timedelta(seconds=float(max_time_range))

        return BaseDefinition(
            base_id=row["base_id"],
            display_name=row["display_name"],
            description=row.get("description"),
            base_type=BaseType(row["base_type"]),
            schema=_parse_json_column(row.get("schema")) or [],
            context=_parse_json_column(row.get("context")) or {},
            source_entity_type=row.get("source_entity_type"),
            source_feature_groups=row.get("source_feature_groups") or [],
            physical_table=row.get("physical_table"),
            kudu_table=row.get("kudu_table") or row.get("pinot_table"),  # Backwards compat
            default_dql=row.get("default_dql"),
            default_time_range=default_time_range,
            max_time_range=max_time_range,
            read_acl=row.get("read_acl") or ["*"],
            owner=row.get("owner"),
            tags=row.get("tags") or [],
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
