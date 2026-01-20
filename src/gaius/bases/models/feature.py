"""Feature and entity type models."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class EntityType:
    """Entity type definition.

    Entity types define what kind of thing features are computed for
    (user, transaction, device, etc.).
    """

    entity_type_id: str  # e.g., "user", "transaction"
    display_name: str
    description: str | None = None
    key_columns: list[dict[str, str]] = field(default_factory=list)  # [{name, type}]
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entity_type_id": self.entity_type_id,
            "display_name": self.display_name,
            "description": self.description,
            "key_columns": self.key_columns,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "EntityType":
        """Create from database row."""
        return cls(
            entity_type_id=row["entity_type_id"],
            display_name=row["display_name"],
            description=row.get("description"),
            key_columns=row.get("key_columns", []),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


@dataclass
class FeatureGroup:
    """Feature group definition.

    Feature groups organize related features (e.g., "user_profile",
    "transaction_risk").
    """

    group_id: str  # e.g., "user_profile"
    display_name: str
    description: str | None = None
    entity_type_id: str | None = None
    owner: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "group_id": self.group_id,
            "display_name": self.display_name,
            "description": self.description,
            "entity_type_id": self.entity_type_id,
            "owner": self.owner,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "FeatureGroup":
        """Create from database row."""
        return cls(
            group_id=row["group_id"],
            display_name=row["display_name"],
            description=row.get("description"),
            entity_type_id=row.get("entity_type_id"),
            owner=row.get("owner"),
            tags=row.get("tags", []),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


@dataclass
class Feature:
    """Individual feature definition."""

    feature_id: str  # e.g., "user_profile.age"
    group_id: str
    name: str  # Short name: "age"
    display_name: str | None = None
    description: str | None = None

    # Type information (Arrow-compatible)
    value_type: str = "STRING"  # STRING, INT64, FLOAT64, BOOLEAN, TIMESTAMP, etc.
    nullable: bool = True
    default_value: Any = None

    # Computation metadata
    transformation: str | None = None  # SQL/expression to compute
    aggregation_type: str | None = None  # For time-window features: SUM, AVG, etc.
    window_duration: timedelta | None = None

    # Lifecycle
    status: str = "active"  # active, deprecated, archived
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "feature_id": self.feature_id,
            "group_id": self.group_id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "value_type": self.value_type,
            "nullable": self.nullable,
            "default_value": self.default_value,
            "transformation": self.transformation,
            "aggregation_type": self.aggregation_type,
            "window_duration_seconds": (
                self.window_duration.total_seconds() if self.window_duration else None
            ),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Feature":
        """Create from database row."""
        return cls(
            feature_id=row["feature_id"],
            group_id=row["group_id"],
            name=row["name"],
            display_name=row.get("display_name"),
            description=row.get("description"),
            value_type=row.get("value_type", "STRING"),
            nullable=row.get("nullable", True),
            default_value=row.get("default_value"),
            transformation=row.get("transformation"),
            aggregation_type=row.get("aggregation_type"),
            window_duration=row.get("window_duration"),
            status=row.get("status", "active"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
