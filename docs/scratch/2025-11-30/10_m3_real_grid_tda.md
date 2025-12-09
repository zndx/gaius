# M3: Real Grid Data + TDA Integration

## Summary

Completed Milestone 3 of the Gaius v1.0 roadmap, implementing the projection pipeline
and TDA integration to replace static test data with real embedding-driven grid visualization.

## Deliverables Completed

### 1. Projection Pipeline (`src/gaius/core/projection.py`)

**GridProjector class:**
- Retrieves embeddings from Qdrant via VectorSearch
- Projects to 2D using UMAP or PCA (configurable)
- Normalizes coordinates to 19x19 grid range
- Produces GridData with document positions and allocations

**GridData dataclass:**
- `document_positions`: Set of (x, y) tuples for KB documents
- `cluster_centers`: Cluster center positions
- `allocations`: 19x19 density array (0-100)
- `points`: Full GridPoint list with metadata
- `coverage`: Fraction of grid cells with documents

**GridDataManager:**
- Caches projection results
- `reindex_and_project()` for KB updates
- `project_query()` to show where a search query would land

### 2. TDA Integration (`src/gaius/core/tda.py`)

**TDAComputer class:**
- Uses giotto-tda for persistent homology computation
- Falls back to DBSCAN-based approximation if giotto-tda unavailable
- Computes H0 (components), H1 (loops), H2 (voids)
- Generates BoundingBox objects for visualization

**TDAFeatures dataclass:**
- `death_loops`: List of BoundingBox for H1 features
- `voids`: List of BoundingBox for H2 features
- `entropy`: Persistence entropy
- `h0_count`, `h1_count`, `h2_count`: Feature counts

**TDAManager:**
- Caches TDA results
- `get_death_loops_as_tuples()` for legacy compatibility
- `get_metrics()` for status display

### 3. Background TDA Worker (`src/gaius/workers/processing/tda.py`)

**TDAWorker class:**
- Scheduled background computation (default: hourly from config)
- `run_once()` for manual trigger
- `run_scheduled()` for continuous operation
- Caches results in managers

### 4. App Integration (`src/gaius/app.py`)

**Grid data loading:**
- `_try_load_real_grid_data()`: Attempts to load from Qdrant embeddings
- Falls back to static test data if unavailable
- Applies document positions, allocations, and TDA features to state

**New commands:**
- `/reindex`: Reindex KB embeddings and refresh grid
- `/tda`: Display TDA metrics (H0, H1, H2, entropy, death loops)

## Files Created/Modified

| File | Type | Description |
|------|------|-------------|
| `src/gaius/core/projection.py` | NEW | Embedding projection pipeline |
| `src/gaius/core/tda.py` | NEW | TDA computation wrapper |
| `src/gaius/workers/processing/tda.py` | NEW | Background TDA worker |
| `src/gaius/workers/processing/__init__.py` | Modified | Export TDA worker |
| `src/gaius/core/__init__.py` | Modified | Export projection and TDA |
| `src/gaius/app.py` | Modified | Real grid data loading, /reindex, /tda |

## Usage

```bash
# Run with real grid data (requires Qdrant)
uv run gaius

# Commands
/reindex     # Reindex KB and refresh grid
/tda         # Show TDA metrics
```

## Configuration

HOCON settings in `config/base.conf`:

```hocon
gaius {
  tda {
    enabled = true
    compute_interval_minutes = 60
    projection_method = "umap"  # or "pca"
  }
}
```

## Data Flow

```
KB Documents → VectorSearch → Qdrant Embeddings
                                    ↓
                             GridProjector
                                    ↓
                              UMAP/PCA 2D
                                    ↓
                            19x19 Grid Coords
                                    ↓
                              TDAComputer
                                    ↓
                    GridData + TDAFeatures → AppState
```

## Graceful Degradation

The system degrades gracefully when dependencies are missing:

1. **No Qdrant**: Falls back to static test data
2. **No giotto-tda**: Uses DBSCAN-based TDA approximation
3. **No UMAP**: Falls back to PCA
4. **No numpy/sklearn**: Returns empty GridData

## Next Steps (M4)

M4: DeepAgents Swarm includes:
1. Agent role definitions
2. Swarm manager with parallel execution
3. Model router for phase-based model selection
4. Agent positions projected to grid
