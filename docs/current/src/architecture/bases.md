# Bases Feature Store

Bases is an entity-centric feature store backed by Apache Kudu (via PostgreSQL FDW) with a fluent query API, BFO ontology grounding, and query guardrails. It abstracts multiple storage backends behind a unified interface.

## Core Concepts

A **Base** is a named, typed view over features and entities. Bases hide the underlying storage backend (PostgreSQL, Iceberg, Kudu FDW) behind a consistent query interface.

Three base types determine query semantics and backend routing:

| Type | Semantics | Backend |
|------|-----------|---------|
| `SNAPSHOT` | Latest value per entity | Kudu via FDW (PostgreSQL stub) |
| `HISTORICAL` | Event-sourced with time-travel | Apache Iceberg |
| `REGISTRY` | Metadata queries | PostgreSQL |

## Fluent Query API

The primary query interface uses Kudu SDK-style method chaining:

```python
from gaius.bases import Base, col, term

results = await (
    Base("events")
    .where(col("age") > 30)
    .where(col("status").isin("active", "pending"))
    .select("name", "email")
    .order_by("created_at", desc=True)
    .limit(100)
    .scan()
)
```

Ontology-grounded queries resolve BFO terms to column names via the base's `@context`:

```python
results = await (
    Base("events")
    .where(term("BFO:material_entity") == "ENT-12345")
    .scan()
)
```

Time-travel queries on historical bases:

```python
results = await (
    Base("events")
    .as_of("2026-01-01T00:00:00Z")
    .where(col("entity_id") == "user-42")
    .scan()
)
```

## Base Definition (.base YAML)

Bases are defined in YAML files with JSON-LD style semantic grounding:

```yaml
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
  - name: event_time
    type: TIMESTAMP
```

## Query Guardrails

All queries pass through guardrails that enforce resource limits:

| Guardrail | Default | Maximum |
|-----------|---------|---------|
| Result limit | 1,000 rows | 10,000 rows |
| Query timeout | 30 seconds | 120 seconds |
| Time range (historical) | 7 days | 90 days |

Historical bases require a time constraint (`.as_of()` or time column filter). Unbounded historical scans are rejected.

## MCP Tools

| Tool | Operation |
|------|-----------|
| `bases_list` | List available bases with metadata |
| `bases_query` | Execute fluent queries against bases |
| `bases_entity_history` | Get event-sourced history for an entity |
| `bases_health` | Check service health |

## Architecture

```
Fluent API (Base/col/term) ──> Parser ──> Compiler (SQLGlot) ──> Executor
                                              |                      |
                                              v                      v
                                    Guardrail Enforcer         PostgreSQL / Iceberg
```

The [DQL Query Language](./dql.md) provides the text-based query syntax parsed by the fluent expression parser.

## Guru Meditation Codes

| Code | Meaning |
|------|---------|
| `#BASES.00000001.NOPOOL` | Database pool not configured |
| `#BASES.00000002.NOICEBERG` | Iceberg catalog unavailable |
| `#FLUENT.00000001.BADAST` | Invalid query expression |
| `#FLUENT.00000002.UNSAFEOP` | Unsafe operation attempted |
