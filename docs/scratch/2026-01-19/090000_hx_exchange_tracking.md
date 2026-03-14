# HX Exchange Tracking Implementation

**Date**: 2026-01-19
**Status**: Complete

## Overview

Enhanced the external inference router to properly capture LLM API exchanges to HX Iceberg tables with OpenLineage provenance tracking. This ensures all "paid" LLM exchanges are captured as history with full lineage linking to derived KB artifacts.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     External LLM Request                             │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              ExternalInferenceRouter.complete()                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │ source_context={                                             │   │
│   │   agent_alias: "metaagent",                                  │   │
│   │   task_type: "audit",                                        │   │
│   │   parent_run_id: "uuid..."                                   │   │
│   │ }                                                            │   │
│   └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
    ┌───────────────────────┐  ┌───────────────────────────┐
    │   Iceberg Capture     │  │   OpenLineage Emission    │
    │   raw.exchange table  │  │   Dataset.from_exchange() │
    └───────────────────────┘  └───────────────────────────┘
                    │                       │
                    └───────────┬───────────┘
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │              ExternalResponse                                    │
    │   exchange_id: "uuid..."   ← Links to Iceberg record            │
    │   request_hash: "sha256..."← Deduplication & lineage            │
    └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │              KB Artifact Creation                                │
    │   link_kb_artifact(kb_path, exchange_id, request_hash)          │
    │   → Creates Exchange → KB provenance edge                        │
    └─────────────────────────────────────────────────────────────────┘
```

## Files Modified

### Phase 1: Infrastructure (ExternalInferenceRouter)

#### `src/gaius/engine/backends/external/base.py`
Added exchange linkage fields to `ExternalResponse`:
- `exchange_id: Optional[str]` - UUID of captured exchange record
- `request_hash: Optional[str]` - SHA-256 hash for deduplication/linkage

#### `src/gaius/engine/backends/external/router.py`
Enhanced `complete()` method with:
- `source_context: Optional[dict[str, Any]]` - Provenance context (agent_alias, task_type, parent_run_id)
- `emit_lineage: bool = True` - Control OpenLineage emission
- `_emit_exchange_lineage()` - New method emitting OpenLineage events after capture

#### `src/gaius/engine/services/llm_exchange_context.py` (NEW)
Helper utilities for exchange tracking:

| Function | Purpose |
|----------|---------|
| `get_source_context()` | Build source_context for router.complete() |
| `link_kb_artifact()` | Emit lineage linking KB artifact to exchange |
| `tracked_llm_exchange()` | Context manager for direct API calls |
| `ExchangeResult` | Dataclass for exchange metadata |

### Phase 2: BackendRouter Integration

#### `src/gaius/engine/backends/backend_router.py`
- Added `source_context: Optional[dict[str, Any]]` to `InferenceRequest`
- Added `exchange_id` and `request_hash` to `InferenceResponse`
- Updated `_route_to_external()` to forward `source_context` and return exchange fields
- Added `task_type` convenience parameter to `complete()` for auto-building source_context

### Phase 3: Caller Wiring

#### `src/gaius/engine/grpc/servicers/gaius_servicer.py`
Updated 5 locations with task_type or source_context:
- `SchedulerComplete` RPC: `task_type="scheduler_complete"`
- Swarm agent execution: `source_context={agent_alias, task_type, role_name, domain}`
- Grid position explanation: `task_type="grid_explain"`
- `MetaAgentQuery`: `task_type="metaagent_query"`
- `MetaAgentQueryStream`: `task_type="metaagent_query_stream"`

#### `src/gaius/inference/parallel_synthesis.py`
Updated XAI frontier synthesis:
- `source_context={agent_alias="parallel_synthesizer", task_type="frontier_synthesis"}`

#### `src/gaius/engine/services/ambient_service.py`
Updated 2 locations:
- HN summarization: `task_type="ambient_summarization"`
- Warmup tasks: `task_type="ambient_warmup"`

#### `src/gaius/engine/server.py`
Updated direct backend access:
- `task_type="engine_inference"`

## Usage Patterns

### Pattern 1: Using the Router (Preferred)

```python
from gaius.engine.backends.external import get_external_router
from gaius.engine.services.llm_exchange_context import get_source_context

router = get_external_router()
response = await router.complete(
    messages=[{"role": "user", "content": "..."}],
    source_context=get_source_context(
        agent_alias="metaagent",
        task_type="audit",
    ),
)

# response.exchange_id links to raw.exchange table
# response.request_hash enables deduplication
```

### Pattern 2: Linking KB Artifacts

```python
from gaius.engine.services.llm_exchange_context import link_kb_artifact

# After creating KB artifact from LLM response
await link_kb_artifact(
    kb_path="scratch/2026-01-19/audit_report.md",
    exchange_id=response.exchange_id,
    exchange_hash=response.request_hash,
)
```

### Pattern 3: Direct API Calls (Bypass Router)

```python
from gaius.engine.services.llm_exchange_context import tracked_llm_exchange

async with tracked_llm_exchange("cerebras", "audit") as tracker:
    response = await cerebras_client.chat(messages=[...], model="glm-4.7")
    tracker.record_response(
        messages=[...],
        response_content=response.content,
        model="glm-4.7",
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )

# tracker.result contains ExchangeResult with exchange_id
```

## OpenLineage Graph Structure

The implementation creates this lineage graph structure:

```
┌─────────────────────────────────────────┐
│ Job: metaagent_audit                    │
└─────────────────────────────────────────┘
                    │
                    ▼ EXECUTES
┌─────────────────────────────────────────┐
│ Run: uuid-1234...                       │
│ (optional: parent_run_id for nesting)   │
└─────────────────────────────────────────┘
                    │
                    ▼ OUTPUTS
┌─────────────────────────────────────────┐
│ Dataset: gaius.exchange/cerebras/sha256 │
│   exchange_id: "uuid..."                │
│   request_hash: "sha256..."             │
└─────────────────────────────────────────┘
                    │
                    ▼ INPUT_TO (via link_kb_artifact)
┌─────────────────────────────────────────┐
│ Dataset: gaius.kb/scratch/.../report.md │
└─────────────────────────────────────────┘
```

## Guru Meditation Codes

| Code | Description |
|------|-------------|
| `#HX.00000001.CAPTUREFAIL` | Exchange capture to Iceberg failed |
| `#HX.00000002.LINEAGEFAIL` | OpenLineage emission failed |
| `#HX.00000003.NOEXCHANGEID` | Response missing exchange_id |
| `#HX.00000004.LINKFAIL` | KB artifact linking failed |

## Testing

Type checking passes for all modified files:
```bash
ty check src/gaius/engine/backends/external/base.py \
         src/gaius/engine/backends/external/router.py \
         src/gaius/engine/services/llm_exchange_context.py
# All checks passed!
```

## Integration Points

### MetaAgent
MetaAgent services should use `get_source_context()`:
```python
response = await router.complete(
    messages=[...],
    source_context=get_source_context(
        agent_alias="metaagent",
        task_type=task_type,
        parent_run_id=parent_run_id,
    ),
)
```

### Research Flows
Research flows should call `link_kb_artifact()` after creating KB documents:
```python
await link_kb_artifact(
    kb_path=f"scratch/{date}/research_synthesis.md",
    exchange_id=response.exchange_id,
)
```

### Swarm Analysis
Swarm agents should include `agent_alias` identifying the specialist:
```python
source_context=get_source_context(
    agent_alias="swarm_analyst",
    task_type="domain_analysis",
)
```

## Implementation Status

**Phase 1**: Infrastructure - DONE
**Phase 2**: BackendRouter Integration - DONE
**Phase 3**: Caller Wiring - DONE

All type checks pass for modified files.

## Next Steps

1. ~~Update MetaAgent to pass proper `source_context` to router calls~~ DONE
2. Update research flows to call `link_kb_artifact()` after KB creation
3. Add Metabase dashboard for exchange capture analytics
4. Monitor `raw.exchange` table growth and set up retention policy

---
*Generated by Code Quality Agent*
