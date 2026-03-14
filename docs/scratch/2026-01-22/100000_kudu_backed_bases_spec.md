# Kudu-Backed Bases: Architecture Specification

**Date**: 2026-01-22
**Status**: Draft
**Author**: Claude (with rch)

## Vision

Obsidian Bases backed by Apache Kudu via PostgreSQL FDW, combining:
- **Kudu primitives** - Practitioners build intuition for distributed columnar storage
- **BFO ontology** - Formal semantics via `@context` in YAML frontmatter
- **Data Elements** - M.D. Anderson-style dependent field semantics
- **Obsidian compatibility** - `.base` files parse without errors (unknown frontmatter ignored)

## Architecture Stack

```
┌─────────────────────────────────────────────────────────────┐
│  Obsidian / Gaius TUI / CLI / MCP                           │
│  (/dataview command with fluent syntax)                     │
├─────────────────────────────────────────────────────────────┤
│  Fluent Query API (Kudu SDK style)                          │
│  Base("events").where(col("age") >= 30).scan()              │
├─────────────────────────────────────────────────────────────┤
│  SQLGlot (AST → PostgreSQL SQL)                             │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL + kudu_fdw                                      │
├─────────────────────────────────────────────────────────────┤
│  Apache Kudu (distributed columnar storage)                 │
│  - Primary keys, hash/range partitioning                    │
│  - DECIMAL, new vector types                                │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Kudu as Single Storage Backend

Unlike the previous DQL approach with multiple backends (Postgres, Iceberg, Pinot), we commit to Kudu:

| Aspect | Implication |
|--------|-------------|
| **Primary Key** | Every base requires explicit PK (no auto-increment) |
| **Partitioning** | Hash and/or range partitioning declared in .base |
| **Types** | Kudu type system: INT8-64, FLOAT, DOUBLE, DECIMAL, STRING, BINARY, BOOL, UNIXTIME_MICROS |
| **Vector types** | New Kudu complex types for embedding storage |
| **Mutability** | Kudu supports updates (unlike pure append-only) |

### 2. `.base` YAML Format with `@context`

```yaml
---
"@context":
  "@vocab": "https://purl.obolibrary.org/obo/"
  Person: "http://dbpedia.org/ontology/Person"
  entity_id:
    "@id": "BFO_0000040"  # material entity
    "@type": "@id"
  event_time:
    "@id": "BFO_0000038"  # one-dimensional temporal region

# Kudu-specific metadata
kudu:
  table: "gaius.pension_events"
  primary_key: [entity_id, event_time]
  partitioning:
    hash:
      columns: [entity_id]
      buckets: 16
    range:
      column: event_time
      splits: ["2024-01-01", "2025-01-01", "2026-01-01"]

# Schema with Data Element references
schema:
  - name: entity_id
    type: STRING
    data_element: "DE:person_identifier"

  - name: event_time
    type: UNIXTIME_MICROS
    data_element: "DE:event_timestamp"

  - name: biopsy_location
    type: STRING
    data_element: "DE:anatomical_landmark"
    requires:  # Data Element dependency
      - distance_from_landmark
      - direction_from_landmark

  - name: distance_from_landmark
    type: DECIMAL(10, 2)
    data_element: "DE:measurement_distance"
    unit: "cm"

  - name: direction_from_landmark
    type: STRING
    data_element: "DE:anatomical_direction"
    enum: [superior, inferior, anterior, posterior, medial, lateral]
---

# Biopsy Events Base

This base tracks biopsy sample collection events with precise anatomical localization.

## Usage

```dataview
Base("biopsy_events")
    .where(col("biopsy_location") == "liver")
    .select("entity_id", "event_time", "distance_from_landmark")
    .scan()
```
```

### 3. Obsidian Compatibility

Obsidian ignores unknown YAML frontmatter keys. The `@context` and `kudu` blocks are valid YAML that Obsidian will parse without errors but not interpret. This means:

- `.base` files live in the KB git repo alongside markdown
- IRIs are version-controlled with content
- The `.base` file is a **view definition**, not the data itself
- Actual data lives in unbounded Kudu tables

### 4. Data Elements (M.D. Anderson Pattern)

Data Elements express **semantic dependencies** between fields:

```yaml
data_elements:
  DE:anatomical_landmark:
    description: "A reference point on or in the body"
    bfo_class: "BFO_0000029"  # site
    requires_context:
      - DE:measurement_distance
      - DE:anatomical_direction
    validation: |
      If biopsy_location is specified, distance_from_landmark
      and direction_from_landmark MUST be non-null.

  DE:measurement_distance:
    description: "Distance measurement from a reference point"
    bfo_class: "BFO_0000019"  # quality
    unit_required: true

  DE:anatomical_direction:
    description: "Directional orientation relative to anatomical axes"
    bfo_class: "BFO_0000026"  # one-dimensional spatial region
    controlled_vocabulary: true
```

This prevents the "intake screen missing required fields" problem - the schema enforces that dependent fields travel together.

### 5. Fluent Query API

Mirrors Kudu SDK patterns, compiles via SQLGlot to PostgreSQL (which proxies to Kudu via FDW):

```python
from gaius.bases import Base, col, term

# Column-based query (Kudu SDK style)
results = (Base("biopsy_events")
    .where(col("biopsy_location") == "liver")
    .where(col("distance_from_landmark") < 5.0)
    .select("entity_id", "event_time", "direction_from_landmark")
    .order_by("event_time", desc=True)
    .limit(100)
    .scan())

# Ontology-term query (BFO grounded)
results = (Base("biopsy_events")
    .where(term("BFO:site") == "liver")
    .select(term("BFO:material_entity"), term("BFO:temporal_region"))
    .scan())

# The fluent API builds a query plan, SQLGlot compiles to:
# SELECT entity_id, event_time, direction_from_landmark
# FROM kudu.biopsy_events
# WHERE biopsy_location = 'liver' AND distance_from_landmark < 5.0
# ORDER BY event_time DESC
# LIMIT 100
```

### 6. `/dataview` Command

Available in CLI, TUI, and MCP:

```bash
# CLI
gaius-cli --cmd "/dataview Base('events').where(col('age') > 30).limit(10)"

# TUI (command mode)
/dataview Base("events").where(col("age") > 30).limit(10)

# MCP tool
bases_query(base_name="events", fluent="where(col('age') > 30).limit(10)")
```

## Kudu Type Mapping

| Kudu Type | Python Type | BFO Alignment |
|-----------|-------------|---------------|
| INT8, INT16, INT32, INT64 | int | BFO:quality (if measurement) |
| FLOAT, DOUBLE | float | BFO:quality |
| DECIMAL(p, s) | Decimal | BFO:quality (precise) |
| STRING | str | Varies by semantics |
| BINARY | bytes | BFO:generically_dependent_continuant |
| BOOL | bool | - |
| UNIXTIME_MICROS | datetime | BFO:temporal_region |
| VECTOR(dim) | np.ndarray | (new complex type for embeddings) |

## Implementation Plan

### Phase 1: Foundation
- [ ] Define `.base` YAML schema with JSON Schema validation
- [ ] Implement fluent query builder classes
- [ ] SQLGlot integration for PostgreSQL output
- [ ] Basic `/dataview` CLI command

### Phase 2: Kudu Integration
- [ ] kudu_fdw PostgreSQL extension setup
- [ ] Schema synchronization (`.base` → Kudu table)
- [ ] Primary key and partitioning support

### Phase 3: Semantic Layer
- [ ] `@context` parsing and IRI resolution
- [ ] Data Element dependency validation
- [ ] Ontology-term queries via `term()`

### Phase 4: Full Stack
- [ ] TUI integration with result display
- [ ] MCP tool exposure
- [ ] Data Element violation reporting

## Open Questions

1. **Vector type syntax** - How to express embedding dimensions in Kudu's new vector types?
2. **FDW development** - Timeline for kudu_fdw? Existing work to build on?
3. **Partitioning UI** - How much partitioning detail to expose in `/dataview`?
4. **BFO version** - BFO 2.0 (2020) or BFO 2020 ISO/IEC 21838-2?

## References

- [Apache Kudu Schema Design](https://kudu.apache.org/docs/schema_design.html)
- [BFO 2020](https://basic-formal-ontology.org/)
- [SQLGlot](https://github.com/tobymao/sqlglot)
- [Obsidian Dataview](https://blacksmithgu.github.io/obsidian-dataview/)
- [JSON-LD @context](https://www.w3.org/TR/json-ld11/#the-context)
