# MCP Server Remediation Plan

**Date**: 2025-12-01
**Status**: 10 of 27 tools working (37%) → **17+ tools after fixes** (63%+)

## Fixes Applied

| Fix | Status |
|-----|--------|
| Add `einops` dependency | ✅ Done |
| Add `asyncpg` dependency | ✅ Done |
| Add `model` param to `InferenceClient.complete()` | ✅ Done |
| Implement `ActivityTracker.get_stats()` | ✅ Done |
| Add `DailySummaryAgent.generate_summary()` alias | ✅ Done |
| Fix `run_swarm` to use actual API | ✅ Done |

**Note**: MCP server restart required to pick up changes.

## Priority 1: Missing Dependencies (Quick Fixes)

### P1.1: Add `einops` for Nomic embeddings
```bash
uv add einops
```
**Fixes**: `embed_text`, `embed_texts`

### P1.2: Add `asyncpg` for database operations
```bash
uv add asyncpg
```
**Fixes**: `list_agent_versions`, `get_active_config`, `get_best_agent_version`, `rollback_agent`, `save_agent_version`, `optimize_agent`

---

## Priority 2: Missing Methods (Implementation Required)

### P2.1: ActivityTracker.get_stats()
**File**: `src/gaius/core/activity.py`
**Issue**: `get_stats` method doesn't exist
**Fix**: Implement method to query activity logs and return statistics

```python
def get_stats(self, days: int = 7) -> dict:
    """Get activity statistics for the past N days."""
    # Query activity_log table
    # Return: event counts by type, domain breakdown, daily trends
```

### P2.2: DailySummaryAgent.generate_summary()
**File**: `src/gaius/agents/daily_summary.py`
**Issue**: `generate_summary` method doesn't exist
**Fix**: Implement method to synthesize daily activity into summary

```python
async def generate_summary(self, date: str = None) -> dict:
    """Generate or retrieve daily summary."""
    # Get activities for date
    # Synthesize with LLM
    # Cache result
```

---

## Priority 3: Missing Modules (New Files Required)

### P3.1: gaius.search module
**File**: `src/gaius/search.py` (new)
**Issue**: Semantic search module doesn't exist
**Fix**: Create module with vector DB integration

```python
# src/gaius/search.py
class SemanticSearchEngine:
    def __init__(self, collection: str = "kb"):
        self.embedder = NomicEmbedder()
        # Initialize vector store (ChromaDB or similar)

    async def search(self, query: str, limit: int = 10) -> list:
        # Embed query
        # Search vector store
        # Return results with scores
```

### P3.2: gaius.tda module
**File**: `src/gaius/tda.py` (new)
**Issue**: TDA computation module doesn't exist
**Fix**: Create wrapper for giotto-tda

```python
# src/gaius/tda.py
class TDAComputer:
    def compute_persistent_homology(self, data: np.ndarray) -> dict:
        # Use giotto-tda for persistence diagrams
        pass

    def compute_mapper(self, data: np.ndarray) -> dict:
        # Use giotto-tda for mapper graphs
        pass
```

---

## Priority 4: API Fixes

### P4.1: InferenceClient.complete() signature
**File**: `src/gaius/core/inference.py`
**Issue**: `model` parameter not supported in `complete()` method
**Fix**: Update API to accept model override

```python
async def complete(
    self,
    prompt: str,
    model: str = None,  # Add this parameter
    **kwargs
) -> str:
    model = model or self.default_model
    # ...
```

### P4.2: Export get_swarm function
**File**: `src/gaius/agents/swarm.py`
**Issue**: `get_swarm` function not exported
**Fix**: Add function or update import

```python
# Either add the function:
def get_swarm(num_agents: int = 7):
    return SwarmOrchestrator(num_agents=num_agents)

# Or fix the import in mcp_server.py
```

---

## Implementation Order

1. **Quick wins** (P1): Add dependencies - immediate 8 more tools working
2. **Method stubs** (P2): Implement missing methods - 2 more tools
3. **API fixes** (P4): Fix signature issues - 2 more tools
4. **New modules** (P3): Create search and TDA modules - 2 more tools

**Expected outcome**: 24 of 27 tools working (89%)

---

## Testing Checklist

After fixes, verify each tool:

- [ ] `embed_text` - Nomic text embedding
- [ ] `embed_texts` - Batch embedding
- [ ] `semantic_search` - Vector search
- [ ] `list_agent_versions` - DB query
- [ ] `get_active_config` - DB query
- [ ] `get_best_agent_version` - DB query
- [ ] `rollback_agent` - DB write
- [ ] `save_agent_version` - DB write
- [ ] `optimize_agent` - APO/GEPA run
- [ ] `get_activity_stats` - Stats query
- [ ] `get_daily_summary` - Summary generation
- [ ] `ask_reasoning` - QwQ-32B inference
- [ ] `run_swarm` - Multi-agent swarm
- [ ] `compute_tda` - TDA computation
