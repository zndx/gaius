"""Base definition models.

A Base is the core abstraction - a named, typed view over features/entities
that abstracts away the underlying storage backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from gaius.bases.semantic import OntologyContext


class BaseType(str, Enum):
    """Type of Base determining query semantics and backend routing."""

    SNAPSHOT = "snapshot"  # Latest value per entity (Kudu via FDW / PostgreSQL)
    HISTORICAL = "historical"  # Event-sourced with time-travel (Iceberg)
    REGISTRY = "registry"  # Metadata queries (PostgreSQL)


@dataclass
class BaseDefinition:
    """Definition of a Base in the feature store.

    Bases are the primary abstraction exposed to MCP clients. They hide
    the complexity of underlying backends (PostgreSQL, Iceberg, Kudu FDW)
    behind a unified query interface.

    The @context field provides JSON-LD style semantic grounding, mapping
    column names to ontology IRIs (BFO, OBO, etc.).
    """

    # Identity
    base_id: str  # e.g., "user_features"
    display_name: str
    description: str | None = None
    base_type: BaseType = BaseType.SNAPSHOT

    # Schema definition (columns exposed by this base)
    schema: list[dict[str, Any]] = field(default_factory=list)

    # Semantic layer: JSON-LD style @context for ontology grounding
    context: dict[str, Any] = field(default_factory=dict)

    # Source binding
    source_entity_type: str | None = None
    source_feature_groups: list[str] = field(default_factory=list)

    # Physical binding
    physical_table: str | None = None  # Kudu/Iceberg/Postgres table
    kudu_table: str | None = None  # Kudu table name (when kudu_fdw available)

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

    # Cached ontology context (lazy-loaded)
    _ontology_context: "OntologyContext | None" = field(default=None, repr=False)

    @property
    def ontology_context(self) -> "OntologyContext":
        """Get the parsed OntologyContext for this base.

        Lazily parses the @context dictionary into an OntologyContext
        object for term resolution.
        """
        if self._ontology_context is None:
            from gaius.bases.semantic import OntologyContext
            object.__setattr__(self, "_ontology_context", OntologyContext.from_dict(self.context))
        return self._ontology_context  # type: ignore[return-value]

    def resolve_term(self, term_iri: str) -> str | None:
        """Resolve an ontology term to a column name.

        Convenience method for term resolution.

        Args:
            term_iri: Ontology IRI (CURIE or full)

        Returns:
            Column name if found, None otherwise
        """
        return self.ontology_context.resolve_term(term_iri)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "base_id": self.base_id,
            "display_name": self.display_name,
            "description": self.description,
            "base_type": self.base_type.value,
            "schema": self.schema,
            "context": self.context,
            "source_entity_type": self.source_entity_type,
            "source_feature_groups": self.source_feature_groups,
            "physical_table": self.physical_table,
            "kudu_table": self.kudu_table,
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
            context=row.get("context", {}),
            source_entity_type=row.get("source_entity_type"),
            source_feature_groups=row.get("source_feature_groups", []),
            physical_table=row.get("physical_table"),
            kudu_table=row.get("kudu_table"),
            default_dql=row.get("default_dql"),
            default_time_range=row.get("default_time_range", timedelta(days=7)),
            max_time_range=row.get("max_time_range", timedelta(days=90)),
            read_acl=row.get("read_acl", ["*"]),
            owner=row.get("owner"),
            tags=row.get("tags", []),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
