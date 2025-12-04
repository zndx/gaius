# Mini-Grid Import and State Fixes

**Date:** 2025-12-02
**Context:** Continuing from previous session implementing real mini-grid projections

## Issues Encountered

### 1. Import Error: GridData from wrong module
```
ImportError: cannot import name 'GridData' from 'gaius.core.state'
```

**Root Cause:** `src/gaius/core/minigrids.py` was importing `GridData` from `state.py`, but it's actually defined in `projection.py`.

**Fix:** Changed import from `from .state import GridData` to `from .projection import GridData` in `minigrids.py:15`

### 2. AttributeError: AppState missing grid_data and tda_features
```
AttributeError: 'AppState' object has no attribute 'grid_data'
```

**Root Cause:** The mini-grid functions were trying to access `self.state.grid_data` and `self.state.tda_features`, but `AppState` doesn't store these. Instead, they're managed by singleton managers:
- `GridDataManager` (via `get_grid_manager()`)
- `TDAManager` (via `get_tda_manager()`)

**Architecture Discovery:**
- `get_grid_manager()` returns `GridDataManager` with `.get_grid_data()` method
- `get_tda_manager()` returns `TDAManager` with `._cached_features` attribute
- Both use module-level singletons for caching

## Fixes Applied

### Fix 1: `_update_minigrids()` in app.py (lines 1617-1644)
```python
def _update_minigrids(self) -> None:
    """Update mini-grids based on cursor position with real TDA/UMAP data."""
    from .core.minigrids import get_real_minigrid_data
    from .core.projection import get_grid_manager
    from .core.tda import get_tda_manager

    # Get grid data and TDA features from managers
    try:
        grid_data = get_grid_manager().get_grid_data()
        tda_manager = get_tda_manager()
        tda_features = tda_manager._cached_features  # May be None if not computed yet
    except Exception:
        # If grid data not available, fall back to empty mini-grids
        return

    # Use real data from grid projection and TDA
    data = get_real_minigrid_data(
        grid_data=grid_data,
        tda_features=tda_features,
        cursor_x=self.state.cursor_x,
        cursor_y=self.state.cursor_y,
    )

    # Update each mini-grid
    if "right" in data:
        self.query_one("#minigrid-top", MiniGrid).update_data(data["right"])
    if "top" in data:
        self.query_one("#minigrid-bottom", MiniGrid).update_data(data["top"])
```

### Fix 2: `_explain_grid_view()` in app.py (lines 1231-1303)
Added same manager access pattern:
```python
# Get grid data and TDA features from managers
try:
    grid_data = get_grid_manager().get_grid_data()
    tda_manager = get_tda_manager()
    tda_features = tda_manager._cached_features  # May be None
except Exception as e:
    content.show_file("error.txt", f"Failed to get grid data: {e}")
    think.clear_active()
    return
```

## Testing

TUI now starts without errors:
```bash
timeout 2 uv run gaius  # No errors
```

## Status

✅ Import error fixed
✅ AppState attribute errors fixed
✅ Mini-grids properly wired to real GridDataManager
✅ /explain command properly wired to managers
✅ TUI starts successfully

## Next Steps

- Test mini-grid updates when moving cursor (hjkl)
- Test /explain command with local LLM
- Verify Embed view shows semantic similarity correctly
- Verify Iso view shows TDA risk elevation correctly
