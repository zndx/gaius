# Async Operations with Progress in ThinkPanel

## Problem

`/reindex` and `/init` commands were blocking the TUI event loop for 2-5 minutes, making the interface appear frozen during:
- UMAP projection (60-90 seconds)
- giotto-tda computation (60-120 seconds)
- Embedding loading from Qdrant

Users couldn't interact with the TUI while operations ran.

## Solution

**Async execution with real-time progress display in ThinkPanel:**

1. Run long operations in thread pool (`loop.run_in_executor`)
2. Track progress via `BackgroundTask` in AppState
3. Display live progress in ThinkPanel with:
   - Progress bar (█████░░░░░)
   - Status messages per step
   - Running/completed/failed indicators
4. Keep UI responsive throughout

## Implementation

### BackgroundTask Dataclass
```python
@dataclass
class BackgroundTask:
    id: str
    name: str
    status: str  # "pending", "running", "completed", "failed"
    progress: float = 0.0  # 0-1
    message: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
```

### Async Wrappers

**`_async_refresh_from_embeddings()`** - For `/reindex`:
- Step 1/4: Loading embeddings from Qdrant (10%)
- Step 2/4: Projecting to 19x19 grid (30%)
- Step 3/4: Computing TDA features (60%)
- Step 4/4: Saving to cache (90%)

**`_async_full_init()`** - For `/init`:
- Step 1/5: Indexing KB documents (10%)
- Step 2/5: Loading embeddings (25%)
- Step 3/5: Projecting to 19x19 grid (40%)
- Step 4/5: Computing TDA (65%)
- Step 5/5: Saving to cache (90%)

### ThinkPanel Updates

**Now displays background tasks** in top section:
```
Background Tasks
────────────────────────────────────
⚙ Reindexing KB
██████████████░░░░░░░░░░░░░░░░░░ 60%
  Step 3/4: Computing TDA features...
```

**Auto-refreshes** every 0.5s when tasks are active.

**Indicators:**
- ⚙ Running (yellow)
- ✓ Completed (green)
- ✗ Failed (red)

## Files Changed

| File | Change |
|------|--------|
| `core/state.py` | Added `BackgroundTask` dataclass |
| `app.py` | Added `_async_refresh_from_embeddings()` and `_async_full_init()` |
| `app.py` | Updated `/reindex` and `/init` handlers to use async |
| `widgets/think_panel.py` | Display background tasks with progress bars |
| `widgets/think_panel.py` | Auto-refresh while tasks active |

## Usage

### /reindex (async)
```bash
uv run gaius
/reindex
# UI stays responsive!
# Press 'g' to toggle ThinkPanel and watch progress
# Takes 2-5 minutes in background
```

### /init (async)
```bash
uv run gaius
/init
# UI stays responsive!
# Watch progress in ThinkPanel
# Takes 2-5 minutes for full pipeline
```

### Visual Progress

```
┌─ Think ──────────────────────┐
│ Background Tasks             │
│ ────────────────────────────  │
│ ⚙ Platform Init              │
│ ████████████░░░░░░░░░░░░░ 40%│
│   Step 3/5: Projecting...    │
│                              │
│ Recent Traces                │
│ ────────────────────────────  │
│ 20:15 search: node (5src)    │
│ 20:10 synthesis: seismic    │
└──────────────────────────────┘
```

## Benefits

1. **Responsive UI** - Navigate, view panels, cycle overlays during processing
2. **Progress visibility** - Know what's happening and how long left
3. **Better UX** - No more "frozen" appearance
4. **ThinkPanel utility** - Now shows real-time system activity

## Next: Safetensors Requirement

User requested that all model downloads use safetensors format for security.

**Implementation:**
```python
# In sentence-transformers model loading
SentenceTransformer(
    model_name,
    trust_remote_code=True,
    use_safetensors=True,  # Force safetensors only
)
```

This prevents loading pickle-based model files which can execute arbitrary code.
