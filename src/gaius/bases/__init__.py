"""Bases: Kudu-backed Feature Store with Fluent Query API.

A feature store with Kudu SDK-style fluent queries, BFO ontology grounding,
and Data Element semantics. Storage is backed by Apache Kudu via PostgreSQL FDW.

Fluent Query API:
    from gaius.bases import Base, col, term

    # Column-based query (Kudu SDK style)
    results = await (
        Base("events")
        .where(col("age") > 30)
        .where(col("status").isin("active", "pending"))
        .select("name", "email")
        .order_by("created_at", desc=True)
        .limit(100)
        .scan()
    )

    # Ontology-grounded query (BFO)
    results = await (
        Base("events")
        .where(term("BFO:material_entity") == "ENT-12345")
        .scan()
    )

MCP Tools:
- bases_list(): List available bases with metadata
- bases_query(): Execute fluent queries against bases
- bases_entity_history(): Get event-sourced history for an entity

.base YAML Format:
    ---
    "@context":
      "@vocab": "https://purl.obolibrary.org/obo/"
      entity_id:
        "@id": "BFO_0000040"

    kudu:
      table: "gaius.events"
      primary_key: [entity_id, event_time]

    schema:
      - name: entity_id
        type: STRING
    ---
"""

# Fluent query API
from gaius.bases.fluent import (
    Base,
    col,
    term,
    BaseQuery,
    ColumnRef,
    TermRef,
    Comparison,
    parse_fluent,
    FluentCompiler,
    CompiledQuery,
    FluentParseError,
    UnsafeOperationError,
)

# Models
from gaius.bases.models import (
    BaseDefinition,
    BaseType,
    ColumnSchema,
    EntityType,
    Feature,
    FeatureGroup,
    QueryResult,
    EntityHistoryResult,
    # Kudu type system
    KuduType,
    KuduDataType,
    TypeConverter,
    int8,
    int16,
    int32,
    int64,
    float32,
    float64,
    boolean,
    string,
    varchar,
    binary,
    timestamp,
    date_type,
    decimal,
)

# Semantic layer
from gaius.bases.semantic import (
    # Prefixes and BFO
    OntologyPrefix,
    BFO,
    OBO,
    RDF,
    RDFS,
    XSD,
    OWL,
    DC,
    DCT,
    SKOS,
    SCHEMA,
    GAIUS,
    BFOClasses,
    BFO_ALIASES,
    DEFAULT_PREFIXES,
    expand_curie,
    compact_iri,
    # Context
    OntologyContext,
    TermMapping,
    TermResolutionError,
    # Data Elements
    DataElement,
    DataElementSchema,
    ValueConstraint,
)

# Service
from gaius.bases.service import BasesService, BasesConfig

__all__ = [
    # Fluent API (primary interface)
    "Base",
    "col",
    "term",
    "BaseQuery",
    "ColumnRef",
    "TermRef",
    "Comparison",
    "parse_fluent",
    "FluentCompiler",
    "CompiledQuery",
    "FluentParseError",
    "UnsafeOperationError",
    # Models
    "BaseDefinition",
    "BaseType",
    "ColumnSchema",
    "EntityType",
    "Feature",
    "FeatureGroup",
    "QueryResult",
    "EntityHistoryResult",
    # Kudu type system
    "KuduType",
    "KuduDataType",
    "TypeConverter",
    "int8",
    "int16",
    "int32",
    "int64",
    "float32",
    "float64",
    "boolean",
    "string",
    "varchar",
    "binary",
    "timestamp",
    "date_type",
    "decimal",
    # Semantic layer
    "OntologyPrefix",
    "BFO",
    "OBO",
    "RDF",
    "RDFS",
    "XSD",
    "OWL",
    "DC",
    "DCT",
    "SKOS",
    "SCHEMA",
    "GAIUS",
    "BFOClasses",
    "BFO_ALIASES",
    "DEFAULT_PREFIXES",
    "expand_curie",
    "compact_iri",
    "OntologyContext",
    "TermMapping",
    "TermResolutionError",
    "DataElement",
    "DataElementSchema",
    "ValueConstraint",
    # Service
    "BasesService",
    "BasesConfig",
]
