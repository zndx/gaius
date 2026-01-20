"""Schema and result models for query responses."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ColumnSchema:
    """Schema for a single column in query results."""

    name: str
    data_type: str  # STRING, INT64, FLOAT64, BOOLEAN, TIMESTAMP, ARRAY<T>, STRUCT<...>
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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnSchema":
        """Create from dictionary.

        Handles both "data_type" and "type" keys for compatibility.
        """
        return cls(
            name=d["name"],
            data_type=d.get("data_type") or d.get("type", "STRING"),
            nullable=d.get("nullable", True),
            description=d.get("description"),
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
