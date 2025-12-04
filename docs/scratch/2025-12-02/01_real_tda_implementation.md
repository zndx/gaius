# Real TDA Analytics Implementation

## Summary

Fixed the TDA (Topological Data Analysis) pipeline to compute on 768-dimensional KB embeddings instead of 2D grid projections. Added H2 (voids) and Risk overlay rendering to the main grid.

## Core Bug Fixed

**Before:** TDA was receiving 2D grid coordinates for analysis:
```python
features = tda_manager.compute_features(grid_coords, grid_coords)  # WRONG: 2D!
```

**After:** TDA receives original high-dimensional embeddings:
```python
features = tda_manager.compute_features(
    grid_data.raw_embeddings,  # 768-dim for real topology
    grid_coords,               # 2D for bounding box mapping
)
```

## Files Changed

| File | Change |
|------|--------|
| `core/projection.py` | Added `raw_embeddings` and `embedding_to_grid` fields to GridData |
| `core/state.py` | Added `voids` and `risk_map` fields to AppState |
| `core/tda.py` | Added `risk_scores` to TDAFeatures, `_compute_point_risk()` method |
| `app.py` | Fixed TDA data flow in `_try_load_real_grid_data()` and `_refresh_from_embeddings()`, added `_compute_risk_map()` |
| `widgets/grid.py` | Added `_render_voids()` and `_render_risk()` methods, updated overlay dispatch |

## New Features

### Risk Computation
- Uses k-NN distances as proxy for local topological instability
- Points with distant neighbors = less stable = higher risk
- Normalized to 0-1 range per embedding

### Risk Heatmap Overlay
- Press `o` to cycle overlays until RISK mode
- Color scale: green (low) -> yellow -> red (high)
- Shows stability of knowledge regions

### H2 (Voids) Overlay
- Higher-dimensional cavities in the embedding space
- Rendered as magenta diamond outlines
- Indicates gaps in knowledge coverage

## Testing

```bash
# Verify with /reindex and overlay cycling:
uv run gaius
/reindex
# Press 'o' repeatedly to cycle: NONE -> RISK -> H1 -> H2 -> AGENTS
```

## Verification Checklist

- [x] GridData preserves raw 768-dim embeddings
- [x] TDA computes on high-dim data
- [x] Risk scores computed per embedding
- [x] Risk map aggregates to 19x19 grid
- [x] H2 overlay renders voids
- [x] RISK overlay renders heatmap
- [x] All unit tests pass
