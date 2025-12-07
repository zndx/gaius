# Phase 5: Compute Services + Client Integration

**Date**: 2025-12-05
**Status**: Complete

## Summary

Completed Phase 5 of the gaius-engine: Compute services and client library integration. This phase adds TDA and grid projection services to the engine, plus compute proxies for the client library.

## Files Created

### Compute Services
- `src/gaius/engine/compute/tda_service.py`
  - `TDARequest` / `TDAResult` dataclasses
  - `TDAService` with caching and lazy loading

- `src/gaius/engine/compute/grid_service.py`
  - `GridPoint`, `ProjectionRequest`, `ProjectionResult`
  - `GridService` for UMAP/PCA projections

### Tests
All Phase 4 tests still pass (34/34).

## Files Modified

- `src/gaius/engine/compute/__init__.py` - Exports new services
- `src/gaius/engine/__init__.py` - Re-exports all submodules
- `src/gaius/client/engine_proxy.py` - Added TDAProxy, GridProxy
- `src/gaius/client/__init__.py` - Exports new proxies

## Architecture

```
gaius-engine
├── backends/          # vLLM, optillm controllers
├── compute/           # TDA, Grid projection (NEW)
│   ├── tda_service.py
│   └── grid_service.py
├── resources/         # GPU allocation
├── services/          # Orchestrator, Scheduler, Evolution, Health
└── transport/         # Message router, Aeron bridge

gaius.client
├── aeron_client.py    # IPC communication
└── engine_proxy.py    # Duck-typed proxies
    ├── OrchestratorProxy
    ├── SchedulerProxy
    ├── EvolutionProxy
    ├── HealthProxy
    ├── TDAProxy      (NEW)
    └── GridProxy     (NEW)
```

## API

### TDAService
```python
from gaius.engine.compute import TDAService, TDARequest

service = TDAService(max_dimension=2)
request = TDARequest(
    request_id="tda-1",
    embeddings=embeddings,  # (n, dim) array
    grid_coords=coords,     # Optional (n, 2) array
)
result = service.compute(request)
# result.h0_count, result.h1_count, result.h2_count
# result.entropy, result.h1_cycles, result.risk_scores
```

### GridService
```python
from gaius.engine.compute import GridService, ProjectionRequest

service = GridService(method="umap")
request = ProjectionRequest(
    request_id="grid-1",
    embeddings=embeddings,
    metadata=[{"path": "...", "title": "..."}],
)
result = service.project(request)
# result.points, result.document_positions
# result.allocations, result.coverage
```

### Client Proxies
```python
from gaius.client import get_tda_proxy, get_grid_proxy

tda = await get_tda_proxy()
result = await tda.compute(embeddings)

grid = await get_grid_proxy()
result = await grid.project(embeddings, metadata)
```

## CLI Verification

All CLI commands verified working:
- `/state` - Application state
- `/help` - Command help
- `/agents` - Agent list with positions
- `/grid` - ASCII grid representation
- `/reindex` - KB reindexing (returns 0 docs when KB empty)

## Investigation: /reindex TUI Issue

The `/reindex` command works correctly via CLI. The TUI issue reported by user is environmental:
1. Qdrant vector store not running
2. KB directory empty or not configured

This is not related to engine changes.

## Next Steps

The gaius-engine implementation is substantially complete:
- Phase 1: Transport + Config ✓
- Phase 2: Resource Management + Backends ✓
- Phase 3: Core Services ✓
- Phase 4: Evolution + Health ✓
- Phase 5: Compute + Client ✓

Remaining work:
- Phase 6: Dead code elimination (identify unused MCP tools)
- Integration testing with actual vLLM/optillm backends
- Documentation updates
