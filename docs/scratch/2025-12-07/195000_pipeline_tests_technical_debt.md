# Content Pipeline BDD Tests: Technical Debt Tracker

## Overview

This document tracks simplifications and workarounds implemented in the BDD test suite that must be resolved before production-ready validation.

## Critical Issues

### 1. Missing Schema Columns

**Status**: WORKAROUND IN PLACE
**Location**: `features/steps/content_pipeline_steps.py`

The production schema lacks required columns for proper triage scoring:

```sql
-- MISSING from content_items table:
heuristic_score FLOAT       -- Computed by heuristic triage
llm_quality_score FLOAT     -- Computed by LLM triage
combined_score FLOAT        -- Weighted combination
```

**Current Workaround**:
- Heuristic and LLM scores computed in-memory during tests
- Scores stored in context variables, not persisted to DB
- This means lineage tracking to scores is non-functional

**Required Fix**:
```sql
-- Migration needed:
ALTER TABLE content_items ADD COLUMN heuristic_score FLOAT;
ALTER TABLE content_items ADD COLUMN llm_quality_score FLOAT;
ALTER TABLE content_items ADD COLUMN combined_score FLOAT;
ALTER TABLE content_items ADD COLUMN triage_status VARCHAR(20) DEFAULT 'pending';
```

### 2. Simplified Heuristic Scoring

**Status**: WORKAROUND IN PLACE
**Location**: `features/steps/content_pipeline_steps.py:step_run_heuristic_triage`

**Current Implementation**:
```python
# Naive scoring: title length * 2 + summary length / 10
score = min(100, len(title) * 2 + len(summary) // 10)
```

**Production Requirement**:
- Use `src/gaius/workers/triage.py:compute_heuristic_score()`
- Apply proper weights from feature file:
  - content_length: 0.3
  - title_quality: 0.2
  - metadata_complete: 0.3
  - source_reputation: 0.2

### 3. LLM Triage Not Using Actual Module

**Status**: WORKAROUND IN PLACE
**Location**: `features/steps/content_pipeline_steps.py:step_run_llm_triage`

**Current Implementation**:
- Direct HTTP call to optillm endpoint
- Simple prompt asking for 0-100 score
- No structured output parsing

**Production Requirement**:
- Use `src/gaius/workers/triage.py:TriageWorker`
- Proper JSON-structured responses
- Quality assessment rubric (relevance, novelty, depth)
- Duplicate detection via embeddings

### 4. KB Creation Bypasses Processor Module

**Status**: WORKAROUND IN PLACE
**Location**: `features/steps/content_pipeline_steps.py:step_run_content_processor`

**Current Implementation**:
```python
# Direct file writes with minimal frontmatter
content = f"""---
title: {item.get("title", "Untitled")}
source: test
fetched_at: {datetime.now().isoformat()}
quality: {item.get("combined_score", 50)}
---

# {item.get("title", "Untitled")}

Content processed from test data.
"""
```

**Production Requirement**:
- Use `src/gaius/content/processor.py` module
- Proper YAML frontmatter with all metadata
- Source linkage and lineage tracking
- Embedding generation for semantic search

### 5. No Lineage Tracking

**Status**: NOT IMPLEMENTED
**Location**: All step definitions

The feature file specifies lineage requirements:
- `lineage should record heuristic_score origin`
- `lineage should link content_item to triage_assessment`
- `lineage should link kb_entries to cognition to thoughts`
- `lineage should be complete from source to agent_version`

**Current Implementation**: None of these are verified

**Production Requirement**:
- Implement `lineage` table with source/target/relationship columns
- Each step must create lineage records
- E2E tests must verify complete lineage chains

### 6. Iceberg Integration Mocked

**Status**: WORKAROUND IN PLACE
**Location**: `features/steps/content_pipeline_steps.py:step_unprocessed_content_exists`

**Current Implementation**:
- Content items stored directly in PostgreSQL
- MinIO used but not via Iceberg tables
- No Parquet file management

**Production Requirement**:
- PyIceberg catalog configuration
- Content stored in Iceberg tables on MinIO
- Proper time-travel and schema evolution

### 7. Engine Not Integrated

**Status**: NOT IMPLEMENTED
**Location**: Tier-4/5 scenarios

**Current State**:
- gaius-engine gRPC service not running
- GPU allocation scenarios untested
- QwQ reasoning scenarios skipped

**Production Requirement**:
- Engine must be started via devenv
- GPU allocation verified via nvidia-smi
- Tensor-parallel configuration validated
- vLLM endpoint health checks implemented

## Schema Differences Summary

| Feature File Column | Actual Schema Column | Status |
|---------------------|---------------------|--------|
| `url` | `base_url` | FIXED |
| `enabled` | `active` | FIXED |
| `heuristic_score` | N/A | MISSING |
| `llm_quality_score` | N/A | MISSING |
| `combined_score` | N/A | MISSING |
| `triage_status` | N/A | MISSING |

### 8. Using Local GPUOrchestrator Instead of gRPC Engine

**Status**: WORKAROUND IN PLACE
**Location**: `features/steps/content_pipeline_fixtures.py:ServiceLifecycleManager`

**Current Implementation**:
- Tests use `gaius.inference.orchestrator.GPUOrchestrator` (local subprocess manager)
- This is the same orchestrator used by MCP tools
- Bypasses the gRPC engine entirely

**Production Requirement**:
- Tests should communicate with gaius-engine via gRPC
- Use `gaius.client.grpc_client.GrpcEngineClient` for orchestrator commands
- Verify actual engine GPU allocation, not just local subprocess state
- Validate tensor-parallel configuration through engine APIs

**Why This Matters**:
- The gRPC engine handles multi-tenant GPU scheduling
- The local orchestrator only sees its own subprocesses
- Production uses engine for coordination across services

## Resolution Plan

### Phase 1: Schema Migration
1. Create migration adding triage columns
2. Update step definitions to use actual columns
3. Verify data persistence between steps

### Phase 2: Module Integration
1. Wire up `TriageWorker` for LLM scoring
2. Wire up `ContentProcessor` for KB creation
3. Implement lineage tracking

### Phase 3: Infrastructure
1. Integrate Iceberg for content storage
2. Start engine for GPU allocation tests
3. Implement proper endpoint health checks

### Phase 4: Validation
1. Remove all in-memory workarounds
2. Run full tier-1 through tier-5 suite
3. Verify lineage completeness
4. Confirm metrics accuracy

## Files Modified with Workarounds

- `features/steps/content_pipeline_steps.py` - Most workarounds
- `features/steps/content_pipeline_fixtures.py` - Schema handling
- `scripts/run_pipeline_tests.sh` - Service startup

## Config Changes Made

### GPU Allocation for QwQ-32B

**Issue**: QwQ-32B with tensor-parallel=2 causes OOM on 2 GPUs
**Fix**: Updated `config/base.conf` to use 4 GPUs for reasoning endpoint

```hocon
reasoning {
  models = ["Qwen/QwQ-32B"]
  gpus = [0, 1, 2, 3]
  tensor_parallel = 4
}
```

This required:
1. Moving coding endpoint to GPU 4
2. Moving fast endpoint to GPU 5
3. Disabling orchestration endpoint (was GPU 4-5)
4. Note: Evolution endpoints overlap with reasoning GPUs - conflict to resolve

### 9. Tier-4 GPU Allocation Tests Failing

**Status**: KNOWN ISSUE
**Location**: Tier-4 scenarios in `content_pipeline.feature`

**Current Issue**:
- QwQ-32B with tensor-parallel=4 requires all 4 GPUs to be completely free
- Test fixtures don't properly clean up vLLM processes between scenarios
- Second tier-4 scenario finds GPUs occupied by previous scenario's processes
- vLLM rejects startup when `gpu_memory_utilization` can't be satisfied

**Error Message**:
```
ValueError: Free memory on device (6.71/23.43 GiB) on startup is less than
desired GPU memory utilization (0.9, 21.09 GiB).
```

**Workarounds Applied**:
1. Reduced `gpu_memory_utilization` from 0.9 to 0.8
2. Added `orchestrator.cleanup_stale_processes()` call in fixtures

**Production Fix Required**:
1. Proper async cleanup in `after_scenario` hook
2. Force kill all vLLM processes between GPU-intensive scenarios
3. Wait for GPU memory to be fully released before starting new processes
4. Consider running GPU-intensive scenarios in isolation (separate test runs)

### 10. AsyncIO Event Loop Cleanup Issues

**Status**: KNOWN ISSUE
**Location**: Test teardown

**Current Issue**:
- GPUOrchestrator background tasks not properly cancelled
- Event loop closed before tasks finish
- Results in "Task was destroyed but it is pending" warnings

**Required Fix**:
- Proper async cleanup in `after_scenario` hook
- Cancel and await background tasks before closing event loop

## Related Documentation

- `docs/scratch/2025-12-07/190700_pipeline_tests_tier2.md` - Initial tier-2 work
- `db/migrations/` - Schema migrations directory
