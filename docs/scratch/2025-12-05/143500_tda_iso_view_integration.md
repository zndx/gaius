# TDA + Multi-Vector Iso View Integration

## Summary

Implemented a comprehensive integration of Topological Data Analysis (TDA) with multi-vector embeddings to create a rich, toggleable Iso mini-grid visualization. The Iso view now serves as the centerpiece interface for exploring the high-dimensional topology of the knowledge space.

## Features Implemented

### Four Iso Modes (toggled via `i` key or `/iso` command)

| Mode | Symbol | Source | Interpretation |
|------|--------|--------|----------------|
| **Curvature** | κ | Ollivier-Ricci on k-NN graph | Semantic boundaries (negative κ = high) |
| **Persistence** | π | Total persistence from per-doc H0+H1+H2 | Topological complexity of document |
| **Complexity** | σ | Variance of token embeddings | Semantic diversity within document |
| **Boundary** | β | Cocycle contribution to neighborhood H1 | Documents forming semantic loops |

### Files Created/Modified

1. **`src/gaius/core/iso_features.py`** (NEW)
   - `IsoFeatures` dataclass with all four feature arrays
   - `DocumentTopology` dataclass for per-document TDA results
   - `IsoFeatureComputer` class:
     - Runs ripser for H0+H1+H2 persistent homology
     - Computes per-document topology on token embeddings
     - Cocycle-based boundary attribution
     - Farthest-point sampling for large point clouds
   - `ISO_MODE_SYMBOLS` mapping modes to Greek letters

2. **`src/gaius/core/state.py`**
   - Added `IsoMode` enum with four modes
   - Extended `AppState` with:
     - `iso_mode: IsoMode = IsoMode.CURVATURE`
     - `iso_features: IsoFeatures | None = None`
     - `cycle_iso_mode() -> IsoMode` method

3. **`src/gaius/core/minigrids.py`**
   - Updated `get_iso_view()` to support mode switching
   - Added `iso_mode` and `iso_features` parameters
   - Mode-specific elevation mapping
   - Graceful density fallback when features unavailable

4. **`src/gaius/core/cache.py`**
   - Added `get_cache_iso_path()` for iso.pkl
   - Updated `save_cached_state()` to include `iso_features`
   - Updated `load_cached_state()` to return 4-tuple with `iso_features`
   - Bumped `CACHE_VERSION` to 2

5. **`src/gaius/app.py`**
   - Added `Binding("i", "cycle_iso", "Iso Mode")`
   - Added `action_cycle_iso()` action handler
   - Added `/iso` command with full subcommand support
   - Updated `_update_minigrids()` to pass iso parameters

6. **`src/gaius/cli.py`**
   - Added `/iso` CLI command with:
     - `/iso` - show current mode
     - `/iso <mode>` - set mode
     - `/iso cycle` - cycle to next mode
     - `/iso info` - detailed feature statistics

## Technical Details

### TDA Computation Pipeline

```
Per-Document TDA (~15ms per document with H2):
1. Subsample to 150 tokens using farthest-point sampling
2. Compute cosine distance matrix
3. Run ripser with maxdim=2, do_cocycles=True
4. Extract Betti numbers, total persistence, persistence entropy
5. Store persistence diagrams for detailed analysis
```

### Boundary Score Attribution (Cocycle-based)

```
1. Pool representative tokens from all documents
2. Run ripser H1 with cocycles
3. For each H1 feature, identify participating documents via cocycle
4. Weight contribution by persistence / number of participants
5. Normalize to [0, 1]
```

### Dependencies

Added `ripser` package for persistent homology computation:
```
uv add ripser
```

## Testing

All modes verified working:
- Curvature mode: Uses Ricci curvature or grid-based density estimate
- Persistence mode: Shows per-document topological complexity
- Complexity mode: Shows semantic diversity within documents
- Boundary mode: Shows documents forming semantic loops

## Usage

```bash
# TUI
# Press 'i' to cycle modes: κ → π → σ → β → κ

# CLI
gaius-cli --cmd "/iso"                    # Show current mode
gaius-cli --cmd "/iso persistence"        # Set mode
gaius-cli --cmd "/iso cycle"              # Cycle mode
gaius-cli --cmd "/iso info"               # Show feature statistics
```

## Questions for TDA Experts

The implementation enables discussion of:

1. **Stability**: How stable are persistence diagrams for ~150 token embeddings?
2. **Vectorization**: Is total persistence the right summary statistic, or should we use persistence landscapes/images?
3. **Cocycle attribution**: Does cocycle membership accurately reflect which documents form semantic loops?
4. **H2 interpretation**: What do 2-voids mean in the context of token embeddings?
5. **Metric choice**: Is cosine distance appropriate, or should we use a different metric for TDA?
