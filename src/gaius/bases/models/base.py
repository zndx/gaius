"""Base definition models.

A Base is the core abstraction - a named, typed view over features/entities
that abstracts away the underlying storage backend.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Literal


class BaseType(str, Enum):
    """Type of Base determining query semantics and backend routing."""

    SNAPSHOT = "snapshot"  # Latest value per entity (Pinot)
    HISTORICAL = "historical"  # Event-sourced with time-travel (Iceberg)
    REGISTRY = "registry"  # Metadata queries (PostgreSQL)


@dataclass
class BaseDefinition:
    """Definition of a Base in the feature store.

    Bases are the primary abstraction exposed to MCP clients. They hide
    the complexity of underlying backends (PostgreSQL, Iceberg, Pinot)
    behind a unified query interface.
    """

    # Identity
    base_id: str  # e.g., "user_features"
    display_name: str
    description: str | None = None
    base_type: BaseType = BaseType.SNAPSHOT

    # Schema definition (columns exposed by this base)
    schema: list[dict[str, Any]] = field(default_factory=list)

    # Source binding
    source_entity_type: str | None = None
    source_feature_groups: list[str] = field(default_factory=list)

    # Physical binding
    physical_table: str | None = None  # Iceberg/Postgres table
    pinot_table: str | None = None  # Pinot table (for snapshot bases)

    # Query defaults
    default_dql: str | None = None
    default_time_range: timedelta = field(default_factory=lambda: timedelta(days=7))
    max_time_range: timedelta = field(default_factory=lambda: timedelta(days=90))

    # Access control
    read_acl: list[str] = field(default_factory=lambda: ["*"])

    # Metadata
    owner: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "base_id": self.base_id,
            "display_name": self.display_name,
            "description": self.description,
            "base_type": self.base_type.value,
            "schema": self.schema,
            "source_entity_type": self.source_entity_type,
            "source_feature_groups": self.source_feature_groups,
            "physical_table": self.physical_table,
            "pinot_table": self.pinot_table,
            "default_dql": self.default_dql,
            "default_time_range_seconds": self.default_time_range.total_seconds(),
            "max_time_range_seconds": self.max_time_range.total_seconds(),
            "read_acl": self.read_acl,
            "owner": self.owner,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "BaseDefinition":
        """Create from database row."""
        return cls(
            base_id=row["base_id"],
            display_name=row["display_name"],
            description=row.get("description"),
            base_type=BaseType(row["base_type"]),
            schema=row.get("schema", []),
            source_entity_type=row.get("source_entity_type"),
            source_feature_groups=row.get("source_feature_groups", []),
            physical_table=row.get("physical_table"),
            pinot_table=row.get("pinot_table"),
            default_dql=row.get("default_dql"),
            default_time_range=row.get("default_time_range", timedelta(days=7)),
            max_time_range=row.get("max_time_range", timedelta(days=90)),
            read_acl=row.get("read_acl", ["*"]),
            owner=row.get("owner"),
            tags=row.get("tags", []),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
