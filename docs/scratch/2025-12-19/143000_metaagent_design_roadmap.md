# MetaAgent Design & Roadmap

**Date**: 2025-12-19
**Status**: Foundation Implemented
**Feature Branch**: `feature/metaagent`

---

## Executive Summary

MetaAgent is Gaius's orchestration layer for data pipeline intelligence. It integrates three systems:

1. **Metaflow** - Execution orchestration (K8s-based via Tilt)
2. **NiFi** - Visual flow management and monitoring interface
3. **Metabase** - Analytics dashboards for operational insights

The NiFi SoM/ToM dataset generation pipeline (completed 2025-12-19) provides the foundational training data for vision-language models that will enable agents to understand and operate these systems autonomously.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MetaAgent Layer                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────────┐   │
│  │ NiFi Client │   │ MetaSyncFlow│   │ DatasetService (gRPC)   │   │
│  │ (REST API)  │   │ (Metaflow)  │   │ (Priority Queue)        │   │
│  └──────┬──────┘   └──────┬──────┘   └───────────┬─────────────┘   │
└─────────┼─────────────────┼──────────────────────┼─────────────────┘
          │                 │                      │
          ▼                 ▼                      ▼
    ┌──────────┐     ┌───────────┐         ┌─────────────┐
    │   NiFi   │     │ PostgreSQL│         │ MinIO/S3    │
    │ (8450)   │     │  (5444)   │         │ (9000)      │
    │ Canvas   │     │ meta.*    │         │ Datasets    │
    └──────────┘     └───────────┘         └─────────────┘
          │                │
          ▼                ▼
    ┌──────────┐     ┌───────────┐
    │ Selenium │     │ Metabase  │
    │ Capture  │     │ (3100)    │
    └──────────┘     └───────────┘
```

---

## Component Status

### Implemented (Phase 1 - Foundation)

| Component | Status | Lines | Notes |
|-----------|--------|-------|-------|
| NiFi SoM/ToM Generator | ✅ Complete | 6,351 | 16 modules, full pipeline |
| DatasetService (gRPC) | ✅ Complete | 1,200+ | Priority queue, streaming |
| gaius-dataset CLI | ✅ Complete | 585 | submit/status/cancel/lineage |
| NiFi REST Client | ✅ Complete | 264 | Async httpx, full API |
| NiFi Flow Projector | ✅ Complete | 317+ | Metaflow → NiFi mapping |
| MetaSyncFlow | ✅ Complete | 200+ | Incremental sync pipeline |
| meta.* Schema | ✅ Complete | 10 tables | Analytics layer |
| XAI Calibration | ✅ Complete | 810 | 6-dimension rubric |
| OpenLineage Integration | ✅ Complete | - | Provenance tracking |
| Fail-Fast Infrastructure | ✅ Complete | - | Guru Meditation codes |

### Configured (Phase 1.5 - Infrastructure)

| Component | Port | Status | Enable With |
|-----------|------|--------|-------------|
| NiFi | 8450 | Disabled | `DISABLE_NIFI=false` |
| Metabase | 3100 | Disabled | `DISABLE_METABASE=false` |
| Metaflow UI | 8451 | Disabled | `DISABLE_METAFLOW=false` |

### Not Yet Implemented (Phase 2+)

| Component | Priority | Description |
|-----------|----------|-------------|
| Metabase Dashboards | High | Pre-built dashboards for meta.* |
| NiFi ↔ Metaflow Sync | Medium | Real-time flow synchronization |
| Agent Canvas Control | Medium | Programmatic NiFi manipulation |
| Semantic Region UI | Low | User labeling in Metabase |

---

## Data Flow Pipeline

### Dataset Generation (Implemented)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Dataset Generation Pipeline                   │
└─────────────────────────────────────────────────────────────────┘

1. SUBMIT JOB
   gaius-dataset submit --flow ArxivDoclingFlow --variants 5
                │
                ▼
2. BACKEND CHECK (fail-fast)
   ├── NiFi reachable?     → #NF.00000001.UNREACHABLE
   ├── Selenium available? → LLMGenerationError
   └── Engine running?     → #DS.00000001.SVCNOTINIT
                │
                ▼
3. SCREENSHOT CAPTURE
   ├── Create NiFi process group
   ├── Create processors (placeholder type)
   ├── Create connections
   ├── Capture via Selenium (1280×1024)
   └── Validate pixels ≠ placeholder (240,240,240)
                │
                ▼
4. ANNOTATION (SoM/ToM)
   ├── Element detection (bounding boxes)
   ├── UI element labeling
   └── Generate SoM overlay image
                │
                ▼
5. INSTRUCTION GENERATION
   ├── Template-based (simple)
   ├── LLM-powered (complex)
   └── BON sampling with XAI scoring
                │
                ▼
6. QUALITY VALIDATION
   ├── Schema validation
   ├── Instruction quality check
   └── Screenshot integrity
                │
                ▼
7. XAI CALIBRATION (optional)
   ├── 6-dimension rubric scoring
   ├── Inline (5%) or batch mode
   └── Budget management (100/day, 500/week)
                │
                ▼
8. EXPORT
   ├── Magma format (JSONL + images)
   ├── LLaVA format (conversations)
   ├── MinIO upload (gaius-datasets bucket)
   └── OpenLineage COMPLETE event
```

### Analytics Sync (Implemented)

```
┌─────────────────────────────────────────────────────────────────┐
│                    MetaSyncFlow Pipeline                         │
└─────────────────────────────────────────────────────────────────┘

MetaSyncFlow (triggered manually or via pg_cron)
        │
        ├── sync_lineage()
        │   ├── Read lineage_events (Apache AGE)
        │   ├── Deduplicate datasets → meta.dataset_catalog
        │   ├── Aggregate jobs → meta.job_catalog
        │   └── Flatten edges → meta.data_dependencies
        │
        ├── sync_operations()
        │   ├── Metaflow runs → meta.flow_runs
        │   ├── Agent evals → meta.agent_performance
        │   ├── nvidia-smi → meta.gpu_utilization
        │   └── Scheduler stats → meta.inference_throughput
        │
        └── sync_topology()
            ├── Grid snapshots → meta.kb_topology
            ├── HDBSCAN → meta.document_clusters
            └── Regions → meta.semantic_regions
```

---

## Database Schema (meta.*)

### Lineage Analytics
```sql
meta.dataset_catalog      -- Deduplicated dataset registry
meta.job_catalog          -- Job execution statistics
meta.data_dependencies    -- Lineage edges (source → target)
```

### Operations Analytics
```sql
meta.flow_runs            -- Metaflow execution history
meta.agent_performance    -- Daily agent metrics
meta.gpu_utilization      -- GPU time-series
meta.inference_throughput -- Hourly inference stats
```

### KB Topology Analytics
```sql
meta.kb_topology          -- Grid snapshots (Betti, entropy)
meta.document_clusters    -- HDBSCAN assignments
meta.semantic_regions     -- Named regions
```

### Operational Tracking
```sql
meta.nifi_flows           -- Projected flows in NiFi
meta.sync_watermarks      -- Incremental sync state
```

---

## Fail-Fast Error Handling

### Guru Meditation Codes

| Code | Component | Error |
|------|-----------|-------|
| `#DS.00000001.SVCNOTINIT` | DatasetService | Service not initialized |
| `#NF.00000001.UNREACHABLE` | NiFi | NiFi not reachable |

### Remediation Commands

```bash
# DatasetService issues
/health fix dataset

# NiFi connectivity
/health fix nifi
```

### KB Heuristics Location
```
current/heuristics/gaius/engine/dataset_service_not_initialized.md
current/heuristics/gaius/engine/nifi_unreachable.md
```

---

## Roadmap

### Phase 2: Analytics Integration (Next)

**Goal**: Populate meta.* tables and create Metabase dashboards

1. **MetaSyncFlow Scheduling**
   - [ ] Add pg_cron schedule for hourly sync
   - [ ] Implement watermark-based incremental updates
   - [ ] Add sync status to `/health status`

2. **Metabase Dashboard Templates**
   - [ ] GPU utilization over time
   - [ ] Agent performance trends
   - [ ] Dataset generation history
   - [ ] Lineage graph visualization

3. **NiFi Flow Sync**
   - [ ] Poll NiFi for flow status changes
   - [ ] Update meta.nifi_flows with live status
   - [ ] Surface in Metabase dashboards

### Phase 3: Agent Canvas Control (Medium-term)

**Goal**: Enable agents to manipulate NiFi flows programmatically

1. **NiFi Write Operations**
   - [ ] Create flow from KB template
   - [ ] Modify processor configurations
   - [ ] Start/stop flow execution

2. **Vision-Language Model Training**
   - [ ] Train on NiFi SoM/ToM datasets
   - [ ] Implement screen understanding agent
   - [ ] GUI action prediction

3. **Closed-Loop Optimization**
   - [ ] Monitor Metabase metrics
   - [ ] Identify optimization opportunities
   - [ ] Execute NiFi modifications
   - [ ] Measure improvement

### Phase 4: Full Autonomy (Long-term)

**Goal**: MetaAgent as self-improving system operator

1. **Self-Healing Pipelines**
   - Detect failures via Metabase
   - Auto-remediate via NiFi modifications
   - Learn from successful interventions

2. **Topology-Driven Discovery**
   - Use KB topology to identify gaps
   - Generate research tasks
   - Execute Metaflow pipelines

3. **Multi-Agent Coordination**
   - Swarm analysis for complex decisions
   - Consensus-based flow modifications
   - Human-in-the-loop approval gates

---

## Usage Examples

### Generate Training Dataset
```bash
# Submit 5 variants of ArxivDoclingFlow
uv run gaius-dataset submit --flow ArxivDoclingFlow --variants 5

# With XAI calibration
uv run gaius-dataset submit --flow ArxivDoclingFlow --variants 10 --xai-calibrate

# Monitor progress
uv run gaius-dataset status <job_id>

# View lineage
uv run gaius-dataset lineage <job_id>
```

### Enable MetaAgent Components
```bash
# Edit devenv.nix or set environment
export DISABLE_NIFI=false
export DISABLE_METABASE=false

# Restart processes
devenv processes down
devenv processes up
```

### Run Analytics Sync
```python
from gaius.agents.metaagent.flows.meta_sync import MetaSyncFlow

# Sync all analytics
flow = MetaSyncFlow()
flow.run(sync_types=["lineage", "operations", "topology"])
```

---

## Key Design Decisions

### 1. Visualization-Only NiFi Projection
NiFi is used as a **visual monitoring interface**, not an execution engine. All execution remains in Metaflow via Kubernetes. This separation:
- Keeps execution deterministic and reproducible
- Provides familiar visual interface for operators
- Avoids NiFi's complexity for actual orchestration

### 2. Materialized Analytics Schema
The meta.* schema provides a **denormalized analytics layer** optimized for Metabase queries. This:
- Decouples analytics from operational data
- Enables efficient dashboard queries
- Supports incremental sync for performance

### 3. Fail-Fast with Actionable Errors
Every error includes:
- Unique Guru Meditation code
- Specific `/health fix` command
- KB heuristic with remediation steps

### 4. Dataset Generation as gRPC Service
Running in gaius-engine (not CLI directly):
- Centralized resource management
- Progress streaming to clients
- OpenLineage integration
- Priority-based scheduling

---

## Files Reference

| Category | Path |
|----------|------|
| MetaAgent Core | `src/gaius/agents/metaagent/` |
| Dataset Generator | `src/gaius/datasets/nifi_som/` |
| DatasetService | `src/gaius/engine/services/dataset_service.py` |
| gRPC Servicer | `src/gaius/engine/grpc/servicers/gaius_servicer.py` |
| Proto Definitions | `src/gaius/engine/proto/gaius_service.proto` |
| DB Schema | `db/migrations/20251218000001_meta_schema.sql` |
| Infrastructure | `devenv.nix` (lines 693-924) |
| Health Fixes | `src/gaius/health/service_fixes.py` |

---

## Related Commits

- `b6275e1` - Add MetaAgent foundation with Metabase, NiFi, and meta schema
- `e2c0571` - Add NiFi SoM/ToM dataset generation with gRPC service and fail-fast policy

---

*This document will be updated as MetaAgent evolves.*
