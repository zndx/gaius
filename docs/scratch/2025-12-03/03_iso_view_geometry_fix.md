# Iso View Geometry Fix

**Date**: 2025-12-03
**Issue**: Iso mini-grid showing empty despite valid cache
**Resolution**: Added geometry computation to cache loading path

## Problem Statement

The Iso (isometric) mini-grid in the TUI was showing empty cells even when the main grid had documents loaded from cache. The Embed mini-grid worked correctly.

## Root Cause Analysis

The Iso view requires `state.curvatures_raw` to be populated with per-point Ricci curvature values. This data was only computed during the `/init` command flow, not when loading from cache on startup.

### Data Flow

```
TUI Startup
    └── _load_test_data()
        └── _try_load_cached_state()
            ├── Loads grid_data (positions, embeddings) ✓
            ├── Loads tda_features (H0/H1/H2, entropy) ✓
            └── Geometry computation ✗ (was missing)
```

### Mini-grid Requirements

| View | Data Source | Status Before Fix |
|------|-------------|-------------------|
| Embed | `grid_data.raw_embeddings` | Working |
| Iso | `state.curvatures_raw` | Empty (not computed) |

## Fix Applied

**File**: `src/gaius/app.py`

### 1. Cache Loading Path (lines 425-447)

```python
# Compute geometry from cached embeddings (for Iso view)
if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 15:
    try:
        import asyncio
        import numpy as np
        from .core.geometry import GeometryComputer

        grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
        gc = GeometryComputer(k_neighbors=min(15, len(grid_data.raw_embeddings) - 1))

        # Run async geometry computation
        loop = asyncio.new_event_loop()
        geom_features = loop.run_until_complete(
            gc.compute_features(grid_data.raw_embeddings, grid_coords)
        )
        loop.close()

        # Populate geometry state
        if geom_features:
            self._populate_geometry_state(geom_features, grid_data)
    except Exception as e:
        # Geometry failed - Iso view will be empty but app still works
        pass
```

### 2. Real Grid Data Path (lines 514-530)

Same pattern added to `_try_load_real_grid_data()` for cases where cache is invalid but Qdrant has data.

## Geometry Computation Details

### Ricci Curvature Interpretation

The Iso view displays Ollivier-Ricci curvature (κ) as elevation:

| Curvature | Interpretation | Elevation | Visual |
|-----------|---------------|-----------|--------|
| κ < -0.3 | Strong boundary | 0.9 (high) | █ bright |
| -0.3 ≤ κ < 0 | Weak boundary | 0.5-0.9 | ▓ medium |
| 0 ≤ κ < 0.3 | Weak interior | 0.1-0.5 | ░ dim |
| κ ≥ 0.3 | Strong interior | 0.1 (low) | · faint |

### Biomorphic Analogy

Inspired by "Environmental randomness underlies morphological complexity of colonial diatoms":

- **Negative curvature** (boundaries) ~ turbulent stream flow → complex colonial structures
- **Positive curvature** (interiors) ~ calm water → simple single-cell forms

## Performance Impact

- Geometry computation adds ~1.5-2.5 seconds to TUI startup
- Uses fallback Ricci implementation (GraphRicciCurvature library not callable)
- Computation is synchronous (blocks startup)

## Future Improvements

### For Orchestrator Agent

1. **Async Startup**: Move geometry computation to background task after UI renders
2. **Geometry Caching**: Add geometry to cache alongside TDA features
3. **Progressive Loading**: Show Embed view immediately, Iso view when ready

### Cache Enhancement

```python
# Proposed cache structure
build/dev/.cache/
├── state.json      # Metadata
├── grid.pkl        # Grid projections
├── tda.pkl         # TDA features
└── geometry.pkl    # NEW: Curvatures, gradients, divergence
```

### Health Check Integration

Add to orchestrator health check sequence:

```yaml
iso_view_check:
  - verify: state.curvatures_raw is not empty
  - verify: len(curvatures_raw) == n_documents
  - remediation: recompute geometry if missing
```

## Verification Commands

### Check Geometry State via CLI

```bash
uv run gaius-cli --cmd "/state" --format json | jq '.data.has_curvature_map'
```

### Test Geometry Computation Directly

```python
from gaius.core.cache import load_cached_state
from gaius.core.geometry import GeometryComputer
import asyncio
import numpy as np

grid_data, _, _ = load_cached_state('build/dev')
if grid_data and grid_data.raw_embeddings is not None:
    gc = GeometryComputer(k_neighbors=15)
    coords = np.array([(p.x, p.y) for p in grid_data.points])
    geom = asyncio.run(gc.compute_features(grid_data.raw_embeddings, coords))
    print(f"Curvatures: {len(geom.curvatures)}, range [{geom.curvatures.min():.3f}, {geom.curvatures.max():.3f}]")
```

## Related Files

- `src/gaius/app.py` - Main TUI application (fix location)
- `src/gaius/core/geometry.py` - GeometryComputer class
- `src/gaius/core/minigrids.py` - get_iso_view() function
- `src/gaius/widgets/minigrid.py` - MiniGrid widget
- `src/gaius/core/cache.py` - Cache management (future: add geometry)
