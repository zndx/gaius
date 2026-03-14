# Schema Design

The PostgreSQL database (`zndx_gaius`) uses four schemas to organize data by domain.

## Public Schema

The default `public` schema holds core operational tables:

### Content Pipeline
- `feed_sources` -- RSS/API feed configurations with fetch intervals
- `fetch_jobs` -- Scheduled and completed fetch job records
- `content_items` -- Raw content items with KB path references
- `articles` -- Curated articles with frontmatter (keywords, news queries)

### Agent System
- `agent_evaluations` -- Evaluation scores by agent and evaluator (local/xai)
- `evolution_cycles` -- Training cycle records (success, improvement, duration)
- `agent_versions` -- Version history for agent configurations
- `held_out_queries` -- Reserved evaluation queries not used in training
- `routing_decisions` -- Inference routing analytics (fallback/mismatch tracking)

### Health and Observability
- `health_incidents` -- HealthObserver incident records with FMEA scores
- `healing_events` -- Self-healing attempt logs (tier, success, duration)
- `fmea_catalog` -- Failure Mode and Effects Analysis registry
- `scheduler_jobs` -- Async job queue for the inference scheduler

### State
- `grid_state` -- Persisted 19x19 grid positions and overlays
- `cognition_memory` -- Self-observation and thought chain storage
- `research_state` / `research_progress` -- Active research thread tracking

## Meta Schema

The `meta` schema provides materialized analytics tables for [Metabase](./metabase.md):

- `meta.dataset_catalog` -- Deduplicated dataset registry from lineage events
- `meta.job_catalog` -- Job registry with run/success/failure counts

Populated from OpenLineage events for data provenance dashboards.

## Collections Schema

The `collections` schema manages curated content for the public landing page:

- `collections.collections` -- Named collections with featured flags
- `collections.collection_cards` -- Cards assigned to collections with ordering
- `collections.card_summaries` -- Generated card summary text

## Bases Schema

The `bases` schema implements a feature store registry:

- `bases.bases` -- Feature store definitions (type: feature_group, model, dataset)
- `bases.base_versions` -- Versioned snapshots with Iceberg table references
- `bases.entity_history` -- Entity-level change tracking

## Graph Extension

Apache AGE (`ag_catalog` schema) provides graph query capabilities for lineage traversal using Cypher syntax. The lineage graph connects datasets to jobs via read/write edges.

## Source

Full schema dump: `db/schema.sql`. Migrations: `db/migrations/`.
