# Metabase

Metabase provides self-service analytics dashboards connected to the Gaius PostgreSQL database (`zndx_gaius` on port 5444). It queries the `meta` schema, which contains materialized analytics tables designed for dashboard consumption.

## Architecture

```
PostgreSQL (zndx_gaius)
  ├── public schema    --> operational tables (cards, agents, health)
  ├── meta schema      --> analytics views for Metabase
  ├── collections      --> curated content for landing page
  └── bases schema     --> feature store registry
         |
    Metabase (localhost:3000)
         |
    Dashboards: lineage, operations, KB geometry
```

## Meta Schema

The `meta` schema (`db/migrations/20251218000001_meta_schema.sql`) provides pre-aggregated analytics:

| Table | Purpose |
|-------|---------|
| `meta.dataset_catalog` | Deduplicated dataset registry from lineage events |
| `meta.job_catalog` | Job registry with run counts, success/failure rates |

These tables are populated from OpenLineage events and provide the foundation for data lineage dashboards.

## Dashboard Categories

### Lineage
- Data provenance graph (which flows produce which datasets)
- Dataset read/write frequency
- Job success rates over time

### Operations
- Agent evaluation scores and evolution trends
- GPU utilization over time
- Inference throughput and latency distributions
- Pipeline health (cards published, curation cadence)

### KB Geometry
- Document cluster topology
- Embedding space coverage
- Content freshness by domain

## Process Management

Metabase runs as a devenv process defined in `scripts/processes/metabase.sh`. It starts on `localhost:3000` and connects to PostgreSQL using the same credentials as the application (`gaius:gaius@localhost:5444/zndx_gaius`).

## Source

Metabase process: `scripts/processes/metabase.sh`. Meta schema: `db/migrations/20251218000001_meta_schema.sql`.
