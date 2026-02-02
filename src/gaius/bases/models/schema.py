"""Schema and result models for query responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from gaius.bases.models.base import BaseDefinition
    from gaius.bases.models.types import KuduDataType


@dataclass
class ColumnSchema:
    """Schema for a single column in query results.

    Uses Kudu types as the canonical representation. The data_type field
    is a string that can be parsed into a KuduDataType.
    """

    name: str
    data_type: str  # Kudu type string: STRING, INT64, DECIMAL(18,2), VARCHAR(255), etc.
    nullable: bool = True
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "description": self.description,
        }

    @property
    def kudu_type(self) -> "KuduDataType":
        """Parse data_type string into KuduDataType."""
        from gaius.bases.models.types import KuduDataType
        return KuduDataType.from_string(self.data_type)

    @property
    def postgres_type(self) -> str:
        """Get equivalent PostgreSQL type string."""
        from gaius.bases.models.types import TypeConverter
        return TypeConverter.kudu_to_postgres(self.kudu_type)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnSchema":
        """Create from dictionary.

        Handles both "data_type" and "type" keys for compatibility.
        Normalizes type strings to Kudu format.
        """
        raw_type = d.get("data_type") or d.get("type", "STRING")

        # Normalize common type aliases to Kudu types
        type_aliases = {
            "INTEGER": "INT32",
            "INT": "INT32",
            "BIGINT": "INT64",
            "SMALLINT": "INT16",
            "TINYINT": "INT8",
            "REAL": "FLOAT",
            "FLOAT32": "FLOAT",
            "FLOAT64": "DOUBLE",
            "DOUBLE PRECISION": "DOUBLE",
            "BOOLEAN": "BOOL",
            "TEXT": "STRING",
            "BYTEA": "BINARY",
            "TIMESTAMP": "UNIXTIME_MICROS",
            "TIMESTAMPTZ": "UNIXTIME_MICROS",
            "TIMESTAMP WITH TIME ZONE": "UNIXTIME_MICROS",
        }
        normalized_type = type_aliases.get(raw_type.upper(), raw_type.upper())

        return cls(
            name=d["name"],
            data_type=normalized_type,
            nullable=d.get("nullable", True),
            description=d.get("description"),
        )

    @classmethod
    def from_kudu_type(
        cls,
        name: str,
        kudu_type: "KuduDataType",
        nullable: bool = True,
        description: str | None = None,
    ) -> "ColumnSchema":
        """Create from KuduDataType."""
        return cls(
            name=name,
            data_type=str(kudu_type),
            nullable=nullable,
            description=description,
        )


@dataclass
class QueryResult:
    """Structured result from query_base."""

    columns: list[ColumnSchema]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool  # True if LIMIT applied
    query_time_ms: int
    backend: str  # postgres, iceberg, pinot

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "columns": [c.to_dict() for c in self.columns],
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "query_time_ms": self.query_time_ms,
            "backend": self.backend,
        }


@dataclass
class EntityHistoryResult:
    """Result from get_entity_history."""

    entity_id: str
    entity_type: str
    events: list[dict[str, Any]]  # Ordered by event_time DESC
    total_events: int
    time_range: tuple[datetime, datetime] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "events": self.events,
            "total_events": self.total_events,
            "time_range": (
                [self.time_range[0].isoformat(), self.time_range[1].isoformat()]
                if self.time_range
                else None
            ),
        }


@dataclass
class BaseInfo:
    """Metadata about a Base for list_bases response."""

    name: str
    display_name: str
    description: str | None
    base_type: str  # "snapshot", "historical", "registry"
    schema: list[ColumnSchema]
    entity_type: str | None
    feature_groups: list[str]
    default_dql: str | None
    tags: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "base_type": self.base_type,
            "schema": [c.to_dict() for c in self.schema],
            "entity_type": self.entity_type,
            "feature_groups": self.feature_groups,
            "default_dql": self.default_dql,
            "tags": self.tags,
        }

    @classmethod
    def from_base_definition(cls, base: "BaseDefinition") -> "BaseInfo":
        """Create from BaseDefinition."""
        from gaius.bases.models.base import BaseDefinition

        return cls(
            name=base.base_id,
            display_name=base.display_name,
            description=base.description,
            base_type=base.base_type.value,
            schema=[ColumnSchema.from_dict(c) for c in base.schema],
            entity_type=base.source_entity_type,
            feature_groups=base.source_feature_groups,
            default_dql=base.default_dql,
            tags=base.tags,
        )
