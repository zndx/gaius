# Differential Geometry TDA System: Design Summary

**Date:** 2025-12-03  
**Status:** Planning Phase  
**Related:** Full plan at `~/.claude/plans/snuggly-swimming-duck-agent-e3c0cafc.md`

## Overview

Comprehensive architectural plan to transform Gaius's TDA system from discrete persistent homology (H0/H1/H2) to a **differential geometry-based approach** using Ricci curvature on semantic embedding manifolds.

## Core Design Decisions

### 1. Curvature as Foundation

**Decision:** Use Ollivier-Ricci curvature on k-NN graph instead of k-NN distance (current "risk")

**Rationale:**
- k-NN distance measures isolation (topological stability)
- Ricci curvature measures how semantic relationships **change** (geometric flow)
- Negative curvature = semantic boundaries (where different topics meet)
- Positive curvature = cluster interiors (homogeneous regions)

**Library:** `GraphRicciCurvature` (MIT license, Python 3.12 compatible)

### 2. Iso View Elevation Mapping

**Current:** Elevation = k-NN distance (isolation metric)

**New:** Elevation = abs(curvature), with sign determining topology
```
κ < 0 (boundary) → high elevation (peaks, ridges)
κ > 0 (interior) → low elevation (valleys, basins)
κ ≈ 0 (flat)     → mid-elevation (plains)
```

**Visual Effect:** Semantic boundaries become "mountain ranges", cluster interiors become "valleys"

### 3. Four-Category Overlay System

**Old:** NONE / RISK / H1 / H2 / AGENTS / TEMPORAL

**New:** NONE / TOPOLOGY / GEOMETRY / DYNAMICS / AGENTS

1. **TOPOLOGY:** Persistent homology (H0, H1, H2) - keep existing
2. **GEOMETRY:** Curvature heatmap (replaces RISK)
3. **DYNAMICS:** Gradient vector field (new)
4. **AGENTS:** Agent positions (unchanged)

### 4. Tenuki Algorithm

**Goal:** Jump to most interesting unexplored high-curvature region

**Scoring function:**
```
score = |κ| × distance_factor × novelty_factor
```

Where:
- `|κ|`: Absolute curvature (high = interesting)
- `distance_factor`: Prefer 5-10 cells from cursor
- `novelty_factor`: Penalize previously visited regions

**Keybinding:** `t` (tenuki - Go term for strategic abandonment)

### 5. Multi-Vector Curvature

**Challenge:** ColQwen embeddings = multiple 128-dim vectors per document

**Strategy:**
1. Compute Ricci curvature on **aggregated** vectors (mean pooling)
2. Compute **consensus divergence** from multi-vector variance
3. Combined metric: `curvature + 0.3 × consensus_divergence`

**Interpretation:**
- High consensus divergence = multi-faceted concept (token vectors disagree)
- Acts as additional "complexity penalty" on top of geometric curvature

### 6. /explain Command

**Implementation:** New module `inference/llm.py`

**Flow:**
1. Gather context: cursor position, curvature, nearby documents, TDA metrics
2. Build prompt with geometric interpretation guidelines
3. Query local LLM via optillm → vLLM
4. Stream response to Think panel

**Prompt template:**
```
Position: (x, y), Curvature: κ (sign: +/-/0)
Nearby: [doc titles]

The Iso view shows Ricci curvature as elevation:
- Positive (blue hills) = cluster interiors
- Negative (red valleys) = semantic boundaries
- Flat (white) = uniform regions

Explain in 2-3 sentences:
1. What does this curvature mean semantically?
2. What role does this location play?
3. What to explore next?
```

## Diatom/Turbulence Analogy

**Biological observation:**
- Turbulent stream flow → complex colonial diatom structures (Fragilaria, Synedra)
- Calm pond water → simple single-cell diatoms (Navicula)

**Translation to knowledge space:**
- High curvature (turbulent) → complex biomorphic patterns in Iso view
- Low curvature (calm) → simple, uniform patterns

**Mechanism:**
```
Steep semantic gradients (high |κ|)
  ↓
Rapid change in relationships
  ↓
Complex structure in 2D projection
  ↓
"Colonial diatom" appearance
```

## Mathematical Foundation

### Ollivier-Ricci Curvature

For edge (x, y) in k-NN graph:

```
κ(x,y) = 1 - W₁(μₓ, μᵧ) / d(x,y)
```

Where:
- `W₁(μₓ, μᵧ)` = Wasserstein-1 distance between neighborhood distributions
- `μₓ` = probability distribution on x's k-nearest neighbors
- `μᵧ` = probability distribution on y's k-nearest neighbors
- `d(x,y)` = graph distance

**Geometric meaning:**
- `κ > 0`: Geodesics converge → positive curvature → cluster interior
- `κ = 0`: Geodesics parallel → flat → uniform region
- `κ < 0`: Geodesics diverge → negative curvature → saddle point, boundary

### Gradient Field

**Approach:** Estimate gradient via local linear regression

For each embedding point:
1. Find k-nearest neighbors in embedding space
2. Fit linear map: `f: embedding → grid_position`
3. Gradient = `∇f` (direction of steepest change)

**Rendering:** Unicode arrows (→ ↗ ↑ ↖ ← ↙ ↓ ↘) colored by magnitude

## Implementation Phases

### Phase 1: Core Geometry (Week 1)
- Create `core/geometry.py` module
- Implement Ricci curvature computation
- Implement gradient field computation
- Unit tests

### Phase 2: Overlays (Week 1)
- Update `core/state.py` (new fields, OverlayMode enum)
- Update `widgets/grid.py` (GEOMETRY, DYNAMICS rendering)
- Update `core/minigrids.py` (curvature-based Iso view)

### Phase 3: Tenuki (Week 2)
- Implement tenuki algorithm
- Add keybinding
- Test high-curvature detection

### Phase 4: /explain (Week 2)
- Create `inference/llm.py`
- Implement prompt templates
- Wire up to Think panel

### Phase 5: Multi-Vector (Week 3)
- Consensus divergence metric
- Test with ColQwen embeddings

### Phase 6: Polish (Week 3)
- Caching (GeometryManager)
- Async computation
- Performance optimization

## Critical Files

### New Files
1. `/home/rch/local/src/zndx/gaius/src/gaius/core/geometry.py` - Core curvature/gradient module
2. `/home/rch/local/src/zndx/gaius/src/gaius/inference/llm.py` - /explain command

### Modified Files
3. `/home/rch/local/src/zndx/gaius/src/gaius/core/state.py` - Add geometry fields
4. `/home/rch/local/src/zndx/gaius/src/gaius/core/minigrids.py` - Curvature-based Iso view
5. `/home/rch/local/src/zndx/gaius/src/gaius/widgets/grid.py` - New overlay rendering
6. `/home/rch/local/src/zndx/gaius/src/gaius/app.py` - Wire up geometry, tenuki, /explain
7. `/home/rch/local/src/zndx/gaius/pyproject.toml` - Add GraphRicciCurvature dependency

## Performance Targets

**Computational complexity:** O(n log n) for n documents
- k-NN graph: O(n log n) with cKDTree
- Ricci curvature: O(n·k²) = O(225n) for k=15
- Gradient: O(n·k) = O(15n)

**Expected timing:**
- 500 docs: <1 second
- 1000 docs: ~2 seconds
- 5000 docs: ~10 seconds

## Dependencies

Add to `[project.optional-dependencies.tda]`:
```toml
tda = [
    "numpy>=1.24.0",
    "scikit-learn>=1.3.0",
    "networkx>=3.0",
    "GraphRicciCurvature>=0.5.3",  # NEW: Ricci curvature
    "ripser>=0.6.12",  # Optional: fast persistent homology
]
```

## Key Design Insights

1. **Curvature reveals structure:** Negative curvature = where topics meet (most interesting)
2. **Multi-vector consensus:** Token disagreement = conceptual complexity
3. **Tenuki as exploration:** Strategic jumps to high-curvature = efficient navigation
4. **LLM as interpreter:** Local model explains geometric features in domain context
5. **Diatom metaphor:** Visual complexity emerges from underlying geometric turbulence

## Next Steps

1. Review plan with user
2. Confirm library choices (GraphRicciCurvature vs alternatives)
3. Begin Phase 1 implementation (core geometry module)
4. Iterate on Iso view curvature mapping (may need tuning)
5. Test /explain prompt templates (user feedback critical)

---

**Full detailed plan:** See `~/.claude/plans/snuggly-swimming-duck-agent-e3c0cafc.md` (72KB)
