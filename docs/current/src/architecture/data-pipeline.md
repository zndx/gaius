# Data Pipeline

The data pipeline connects external sources to the knowledge base, card collections, and search index through a sequence of ingestion, processing, and indexing stages.

## End-to-End Flow

```
Web Sources (Brave, arXiv, RSS)
    |
    v
NiFi Ingestion ──> Raw Content (HX / Iceberg)
    |
    v
Metaflow Pipelines ──> Article Drafts, Card Creation
    |
    v
Qdrant Indexing ──> 768-dim Nomic Embeddings
    |
    v
PostgreSQL (zndx_gaius:5444) ──> Cards, Collections, Metadata
    |
    v
R2 Storage ──> Rendered Visualizations (viz.gaius.zndx.org)
```

## Pipeline Stages

**Ingestion.** NiFi processors fetch content from external APIs, RSS feeds, and web search results (Brave). Raw content is stored in Apache Iceberg tables via the HX data lake before any processing occurs. This preserves the original source material and provides a replay capability.

**Processing.** Metaflow pipelines handle the compute-intensive work: PDF conversion via docling, topic extraction via BERTopic, relevance scoring via local LLMs, and article draft generation. See [Metaflow Integration](./metaflow.md) for details on the execution environment.

**Article Curation.** The [Article Curation](./article-curation.md) flow orchestrates the full lifecycle from article selection through card creation and publication. Each run produces approximately 20 cards in under 2 minutes.

**Indexing.** Processed content is embedded using Nomic (768-dimensional vectors) and indexed in Qdrant for semantic search. The same embeddings drive the TUI's 19x19 grid layout and the [visualization pipeline](./visualization.md).

**Storage.** Cards, collections, and metadata live in PostgreSQL (`zndx_gaius` on port 5444). Rendered card images are uploaded to Cloudflare R2 and served from `viz.gaius.zndx.org`. See [Viz Storage](./viz-storage.md) for the object key convention.

## Lineage Tracking

Every pipeline stage emits OpenLineage events that are materialized into an Apache AGE graph. This provides full provenance from source URL to published card. See [Lineage Tracking](./lineage.md) for Cypher query examples.

## Knowledge Base

The [Knowledge Base](./knowledge-base.md) serves as both input and output of the pipeline. Articles begin as zettelkasten notes in `build/dev/scratch/`, and the curation flow produces structured content in `build/dev/current/articles/`.

## Key Services

| Service | Role | Port |
|---------|------|------|
| NiFi | Content ingestion | 8443 |
| Metaflow | Pipeline execution | 8180 |
| PostgreSQL | Metadata, cards, collections | 5444 |
| Qdrant | Vector search | 6333 |
| MinIO | Artifact storage (S3-compatible) | 9000 |
| Gaius Engine (gRPC) | Orchestration, scheduling | 50051 |

## CLI Access

```bash
# List available flows
uv run gaius-cli --cmd "/flows list"

# Trigger article curation
uv run gaius-cli --cmd "/article curate ai-reasoning-weekly"

# Query lineage for a KB file
uv run gaius-cli --cmd "/lineage query scratch/2026-03-14/paper.md"
```
