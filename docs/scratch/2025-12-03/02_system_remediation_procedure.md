# System Remediation Procedure

**Date**: 2025-12-03
**Purpose**: Document the diagnostic and remediation steps for bringing Gaius into a consistent state.

## Problem Statement

The TUI `/reindex` command reported "No documents found" despite KB having 385+ documents via MCP list_kb.

## Diagnostic Steps

### 1. Check Orchestrator Status

```python
# Via MCP
mcp__gaius__orchestrator_status()

# Expected: Shows endpoint status (running/stopped)
# Key fields: total_running, endpoints.*.status
```

If endpoints show `"status": "stopped"`, services need to be started.

### 2. Check Scheduler Status

```python
mcp__gaius__scheduler_status()

# Expected: Shows queue state and endpoint health
# Key fields: pending_jobs, completed_jobs, endpoints.*.healthy
```

### 3. Verify Qdrant Vector Store

```bash
# Check if Qdrant is responding
curl -s http://localhost:6339/collections

# Expected: {"result":{"collections":[{"name":"gaius_kb"}]},"status":"ok"}
```

```bash
# Check collection details
curl -s http://localhost:6339/collections/gaius_kb

# Key fields:
# - points_count: Number of indexed documents
# - indexed_vectors_count: Number of searchable vectors
# - status: "green" means healthy
```

### 4. Verify KB Documents Exist

```python
# Via MCP
mcp__gaius__list_kb(directory="current")

# Expected: List of KB entries
```

```bash
# Direct filesystem check
ls -la build/dev/current/
ls -la build/dev/scratch/
ls -la build/dev/archive/
```

### 5. Test Vector Search Module

```bash
uv run python -c "
from gaius.inference.search.vector import VectorSearch

vs = VectorSearch()
info = vs.get_collection_info()
print(f'Collection: {info}')

# Scroll to verify vectors
client = vs.client
results, _ = client.scroll(
    collection_name=vs.collection_name,
    limit=5,
    with_vectors=True,
    with_payload=True,
)
print(f'Points: {len(results)}')
"
```

## Common Issues and Remediation

### Issue: Missing Search Dependencies

**Symptom**: `ModuleNotFoundError: No module named 'qdrant_client'`

**Diagnosis**:
```bash
uv pip list | grep -E "qdrant|bm25|sentence"
```

**Fix**:
```bash
uv sync --extra search
```

This installs:
- `qdrant-client>=1.12.0`
- `sentence-transformers>=3.0.0`
- `bm25s>=0.2.0`
- `PyStemmer>=2.2.0`

### Issue: Qdrant Not Running

**Symptom**: Connection refused on port 6339

**Diagnosis**:
```bash
curl -s http://localhost:6339/collections || echo "Not responding"
docker ps | grep qdrant
```

**Fix**:
```bash
# Start Qdrant container
docker run -d --name qdrant -p 6339:6333 qdrant/qdrant

# Or via docker-compose if configured
docker-compose up -d qdrant
```

### Issue: Collection Has No Indexed Vectors

**Symptom**: `points_count: 1674` but `indexed_vectors_count: 0`

**Explanation**: Qdrant stores points but HNSW index not built yet. This is normal for small collections - Qdrant has an `indexing_threshold` (default 10000) before building HNSW.

**Diagnosis**: Check collection config:
```bash
curl -s http://localhost:6339/collections/gaius_kb | jq '.result.config.optimizer_config.indexing_threshold'
```

**Note**: Search still works via brute-force for collections under threshold.

### Issue: Projection Returns Empty Grid

**Symptom**: `n_documents: 0` in GridData

**Diagnosis**:
```python
from gaius.core.projection import GridProjector
p = GridProjector()
embeddings, metadata = p._retrieve_embeddings()
print(f"Retrieved: {len(embeddings)}")
```

**Fix**: Ensure embeddings exist in Qdrant:
```bash
uv run python -c "
from gaius.inference.search.vector import VectorSearch
vs = VectorSearch()
count = vs.index_kb()
print(f'Indexed {count} chunks')
"
```

### Issue: TDA Fails with "Not enough points"

**Symptom**: TDA requires minimum 3 points for homology computation

**Fix**: Ensure KB has sufficient content indexed.

### Issue: Iso View Empty (No Curvatures)

**Symptom**: Iso mini-grid shows all empty cells, Embed mini-grid works

**Diagnosis**:
```bash
uv run gaius-cli --cmd "/state" --format json | jq '.data.has_curvature_map'
# Returns: false
```

**Cause**: Geometry (Ricci curvature) was not computed on startup. Only `/init` triggered it.

**Fix Applied** (2025-12-03): Added geometry computation to cache loading path in `app.py`:
- `_try_load_cached_state()` now computes geometry after loading cache
- `_try_load_real_grid_data()` now computes geometry after loading from Qdrant
- Adds ~1.5s to startup time

**Manual Trigger** (if needed):
```bash
# Run /init in TUI to force full recomputation
# Or restart TUI to trigger cache reload with geometry
```

**Verification**:
```bash
uv run gaius-cli --cmd "/state" --format json | jq '.data | {has_curvature_map, has_gradient_field}'
# Should return: {"has_curvature_map": true, "has_gradient_field": true}
```

**See Also**: `docs/scratch/2025-12-03/03_iso_view_geometry_fix.md`

## Verification Test

After remediation, run full pipeline verification:

```bash
uv run python -c "
import asyncio
from gaius.core.projection import GridProjector
from gaius.core.tda import get_tda_manager
from gaius.core.geometry import GeometryComputer
import numpy as np

async def verify():
    # 1. Projection
    p = GridProjector()
    grid = p.project_kb()
    print(f'Projection: {grid.n_documents} docs -> {len(grid.document_positions)} positions')

    if grid.n_documents == 0:
        print('FAIL: No documents projected')
        return False

    # 2. TDA
    tda = get_tda_manager()
    coords = np.array([(pt.x, pt.y) for pt in grid.points])
    features = tda.compute_features(grid.raw_embeddings, coords)
    print(f'TDA: {len(features.h1_cycles)} H1 cycles, entropy={features.entropy:.3f}')

    # 3. Geometry
    gc = GeometryComputer(k_neighbors=15)
    geo = await gc.compute_features(grid.raw_embeddings, coords)
    print(f'Geometry: curvature range [{geo.curvatures.min():.3f}, {geo.curvatures.max():.3f}]')
    print(f'Computation time: {geo.computation_time:.2f}s')

    print('\\nALL CHECKS PASSED')
    return True

asyncio.run(verify())
"
```

## Orchestrator Agent Integration

This procedure can be automated by the NVIDIA Orchestrator-8B agent:

1. **Health Check Trigger**: On session start or `/init` command
2. **Diagnostic Flow**: Run checks in order, collect results
3. **Remediation Actions**: Execute fixes for detected issues
4. **Verification**: Run full pipeline test

### Agent Configuration

```yaml
agent_id: orchestrator
model: nvidia/Orchestrator-8B
capabilities:
  - system_health_check
  - dependency_verification
  - service_management
  - remediation_execution

health_check_sequence:
  - check_orchestrator_status
  - check_qdrant_connection
  - check_kb_documents
  - check_vector_search
  - check_geometry_state      # NEW: Verify curvatures computed
  - run_verification_pipeline

remediation_actions:
  missing_deps: "uv sync --extra search"
  qdrant_down: "docker-compose up -d qdrant"
  empty_index: "vs.index_kb()"
  no_geometry: "restart TUI or run /init"  # NEW: Trigger geometry computation

# Inference endpoint management
inference_endpoints:
  - reasoning: Qwen/QwQ-32B (GPUs 0,1) - complex analysis
  - coding: Qwen3-Coder-30B (GPU 2) - code generation
  - fast: Mistral-7B (GPU 3) - quick responses
  - orchestration: Orchestrator-8B (GPU 4) - task routing
  - standby: (GPU 5) - hot spare
```

**See Also**: `docs/scratch/2025-12-03/04_inference_endpoints_for_orchestrator.md` for full endpoint management guide.
