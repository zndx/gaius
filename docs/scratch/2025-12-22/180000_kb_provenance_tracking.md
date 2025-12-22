# KB Content Provenance Tracking

Date: 2025-12-22

## Overview

Implemented a unified content provenance and freshness tracking system for KB resources from heterogeneous sources. This addresses the need for a single "in-sync" constraint per KB resource, regardless of source type.

## Problem Statement

> "the ZIPs were easy to hash to watch for content changes, and product versions are apparent in URLs but with several sources of truth the logical matrix of inputs needs to translate into a single logical 'in-sync' constraint on a per-kb-resource basis."

The KB ingests content from multiple source types:
- ZIP archives (Cloudera docs, versioned releases)
- HTML pages (scraped web content)
- External documentation (Apache Flink, Kafka)
- Git repositories
- API endpoints

Each source type has different change detection mechanisms (content hash, ETag, Last-Modified, commit hash), but consumers need a single boolean answer: "Is this KB resource current?"

## Solution Architecture

```
Sources                    Lineage Layer              KB Resource
─────────────────────────────────────────────────────────────────
ZIP Archive (hashable)  ─┐
                         ├─► ContentSource ─► transforms ─► kb_path
HTML Page (ETag/hash)   ─┤      │
                         │      ├─ source_uri
Apache Flink docs      ─┘      ├─ content_hash
                               ├─ upstream_version
                               ├─ fetched_at
                               └─ transform_chain[]
```

## Implementation

### New Module: `gaius.rase.domains.kb.provenance`

#### Core Models

**`ContentSource`** - Upstream content source with provenance metadata:
```python
ContentSource(
    source_uri="https://docs.cloudera.com/downloads/csa-docs-archive.zip",
    source_type=SourceType.ARCHIVE,  # ARCHIVE, HTML, API, GIT, MANUAL
    content_hash="541b2c78b28da47e",
    upstream_version="1.5.4",
    fetched_at=datetime(2025, 12, 22, 7, 17, 45),
    etag="",  # for HTTP conditional requests
    last_modified="",
)
```

**`KBResourceLineage`** - Complete provenance chain:
```python
KBResourceLineage(
    kb_path="current/cloudera/docs/csa/1.5.4/overview.md",
    sources=[source1, source2],  # Multiple sources per resource
    transforms=[Transform(transform_type=TransformType.PDF_TO_MARKDOWN)],
    derived_at=datetime.now(),
    derived_hash="sha256...",
)
```

**`Transform`** - Pipeline step:
```python
Transform(
    transform_type=TransformType.PDF_TO_MARKDOWN,
    tool_version="docling 2.15.0",
    input_hash="...",
    output_hash="...",
)
```

#### RASE Constraints

**`SourceInSync`** - Single boolean freshness check:
```python
constraint = SourceInSync(
    document_path="current/cloudera/docs/csa/1.5.4/overview.md",
    max_age_days=7,       # Time-based staleness
    check_upstream=False,  # HTTP freshness check
    require_hash=False,    # Require content_hash
)
result = constraint.evaluate(state)
# result.satisfied = True/False
# result.message = "All 1 source(s) in sync (version 1.5.4)"
```

**`ProvenanceComplete`** - Audit trail verification:
```python
constraint = ProvenanceComplete(
    document_path="current/cloudera/docs/csa/1.5.4/overview.md",
    require_transform_chain=False,
    require_version=False,
)
```

#### Database Integration

Integrates with existing postgres lineage tables:
- `summary_lineage` - KB summaries back to raw content
- `kb_sync_state` - Per-file sync state with content_hash
- `lineage_events` - OpenLineage standard events

```python
# Query existing lineage from DB
lineage = await get_lineage_from_db("current/topics/kudu.md")

# Check S3 sync state
state = await get_sync_state_from_db("current/...", "minio-local")

# Record lineage event
await record_lineage_event(
    run_id=str(uuid4()),
    job_namespace="gaius.sync",
    job_name="cloudera_docs",
    run_state="COMPLETE",
    inputs=[{"namespace": "cloudera", "name": "csa-operator-archive"}],
    outputs=[{"namespace": "kb", "name": "current/cloudera/docs/csa-operator/..."}],
)
```

## Frontmatter Compatibility

Parses existing Cloudera docs frontmatter:
```yaml
---
title: "csa-op-overview"
source: docs.cloudera.com
product: csa-operator
version: 1.4
archive: csa-operator
source_path: csa-operator/1.4/overview/csa-op-overview.pdf
synced_at: 2025-12-22T07:17:45.774381
archive_hash: 541b2c78b28da47e
---
```

And new unified format:
```yaml
---
source_uri: https://docs.cloudera.com/downloads/csa-operator-docs-archive.zip
source_type: archive
content_hash: 541b2c78b28da47e
upstream_version: "1.4"
fetched_at: 2025-12-22T07:17:45.774381
transform_chain:
  - type: pdf_to_markdown
    tool_version: docling 2.15.0
---
```

## Files Changed

- `src/gaius/rase/domains/kb/provenance.py` - New module (850 lines)
- `src/gaius/rase/domains/kb/constraints.py` - Added SourceInSync, ProvenanceComplete
- `src/gaius/rase/domains/kb/__init__.py` - Exported new types

## Next Steps

1. **Strip boilerplate** before ontology extraction (30-40 lines legal text per doc)
2. **Enrich coverage** with Apache Flink/Kafka docs from official sources
3. **Automated freshness checks** via `/health` or scheduled task
4. **UI indicator** showing sync status in KB file tree

## Usage Example

```python
from gaius.rase.domains.kb import (
    KBState, SourceInSync, KBResourceLineage,
)

# Capture KB state
state = KBState.capture("build/dev", ["current/cloudera/docs/..."])

# Check if resource is in sync
constraint = SourceInSync(document_path="...", max_age_days=7)
result = constraint.evaluate(state)

if not result.satisfied:
    print(f"Stale: {result.message}")
    print(f"Details: {result.details}")
```
