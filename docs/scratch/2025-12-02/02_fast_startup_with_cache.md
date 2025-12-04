# Fast TUI Startup with State Caching

## Problem

TUI startup was slow (or failed to start) due to expensive operations:
- Loading KB embeddings from Qdrant
- UMAP projection (1664 points, 768-dim → 2D)
- TDA computation with giotto-tda (Vietoris-Rips persistence)

These operations can take 2-5 minutes with large KBs.

## Solution

**Pre-compute and cache** the initial state:
1. Run full pipeline once: `/init`
2. Cache results to `build/dev/.cache/`
3. Startup loads cached state (instant)
4. Regenerate when model/config changes

## Architecture

### Cache Files

```
build/dev/.cache/
├── state.json     # Metadata (model, method, stats)
├── grid.pkl       # GridData with projections
└── tda.pkl        # TDAFeatures (H0/H1/H2, risk)
```

### Cache Validation

Cache is invalidated if:
- Embedding model changes (e.g., MiniLM → Nomic)
- Projection method changes (PCA ↔ UMAP)
- User runs `/init` or manually deletes cache

### Startup Flow

```
__init__()
  ↓
_load_test_data()
  ↓
_try_load_cached_state() ← Instant if cache valid
  ├── Yes → Load grid + TDA from cache
  └── No  → Use static fallback data
```

## Commands

| Command | Purpose | Duration |
|---------|---------|----------|
| `/init` | Full pipeline: index + project + TDA + cache | 2-5 min |
| `/reindex` | Refresh from current embeddings, update cache | 2-5 min |
| (startup) | Load from cache | < 1 sec |

## Usage

### First Time Setup

```bash
uv run gaius
/init
# Wait 2-5 minutes for full pipeline
# Press 'o' to cycle overlays: RISK → H1 → H2
```

### After Model Change

```bash
# Edit config/base.conf
embedding_model = "some-other-model"

uv run gaius
/init  # Regenerate cache with new model
```

### Normal Usage

```bash
uv run gaius
# TUI starts instantly, loads from cache
```

## Implementation

**New Files:**
- `src/gaius/core/cache.py` - Cache save/load/validation
- `src/gaius/core/state.py` - Added `BackgroundTask` dataclass

**Modified:**
- `src/gaius/app.py`:
  - `_load_test_data()` - Try cache first
  - `_try_load_cached_state()` - Load from cache
  - `_run_full_init()` - Full pipeline + cache save
  - `_refresh_from_embeddings()` - Update cache on reindex
  - Added `/init` command

## Performance

| Operation | Time (1664 docs, 768-dim) |
|-----------|---------------------------|
| UMAP projection | ~60-90 sec |
| giotto-tda (VR persistence) | ~60-120 sec |
| Cache save | ~1 sec |
| Cache load | < 1 sec |
| **Total /init** | **2-5 min** |
| **Startup (cached)** | **< 1 sec** |

## Future: Background Tasks UI

The `BackgroundTask` dataclass in state.py is ready for displaying long-running operations in the ThinkPanel (graph-think panel). This will show:
- Current operation progress
- Background indexing/TDA status
- Agent workflow states

This allows the TUI to start immediately and run heavy operations in the background while displaying progress.
