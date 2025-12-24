# Phase Portrait Situational Awareness

**Date:** 2024-12-24
**Status:** Design complete, implementation partial

## Core Insight

SITREP is not a summary - it's a **phase portrait** of organizational cognition.

The observer sees:
- Where consensus IS (position)
- Where consensus is GOING (velocity/drift)
- What's being IGNORED (floating evidence)
- What WOULD change if we took dissent seriously (counterfactual)

## New Terminology

| Term | Definition |
|------|------------|
| **Phase Portrait** | The dynamical state of the semantic space - attractors, trajectories, stability |
| **Floating Evidence** | KB content that swarm agents mention but never integrate into consensus |
| **Dissent Energy** | Coherent deviation from consensus - when agents pull the same direction |
| **Well Depth** | 1/variance - how entrenched a conclusion is |
| **Orphaned Attractor** | A stable state with no inflow from current trajectories |
| **Earned Stability** | Consensus achieved by integrating evidence |
| **Artificial Stability** | Consensus achieved by ignoring evidence |
| **Katrina Mode** | High tempo, information flood, fast drift, multiple destabilizing attractors |
| **Columbia Mode** | Normal tempo, suspicious stability, floating evidence, dissent being damped |

## Crisis Mode Detection

```python
def assess_mode(drift: DriftMetrics, floating: list[Evidence]) -> str:
    if drift.drift_magnitude > HIGH_TEMPO:
        return "katrina"
    if drift.well_depth > SUSPICIOUSLY_STABLE and len(floating) > 0:
        return "columbia"
    return "normal"
```

## What's Implemented Now

### Available via CLI

```bash
# Topology dynamics
/topology status                    # Service status
/topology drift <domain>            # Drift velocity, well depth, Lyapunov
/topology history <domain>          # Snapshot history
/topology well-depth <domain>       # Entrenchment measurement
/topology attractors <domain>       # Named stable states

# NG-RC forward prediction
/ngrc status                        # Model status
/ngrc train <domain>                # Train on snapshots
/ngrc predict <domain> N            # Predict N steps ahead
```

### Available via TUI

Currently the TUI shows:
- Grid position (MainGrid)
- Agent positions after swarm run
- CLT embeddings projected to grid

### NOT YET IMPLEMENTED

1. **Floating Evidence Tracker** - needs schema + tracking in swarm runs
2. **Dissent Energy Metric** - needs computation in TopologyService
3. **Counterfactual Runner** - needs swarm invocation with forced context
4. **Columbia/Katrina Mode Detection** - needs assessment function
5. **Enhanced SITREP** - needs ThetaAgent integration with topology
6. **TUI Phase Portrait Overlay** - needs visualization of:
   - Drift vectors (arrows showing consensus movement)
   - Attractor basins (colored regions)
   - Floating evidence markers
   - Predicted trajectory (NG-RC output)

## Experiment Path (What You Can Do Now)

### 1. Populate snapshots via swarm runs
```bash
# Run swarms to generate trajectory data
/swarm "analyze pension risk tolerance"
/swarm "evaluate retirement timing"
# Each run persists a snapshot automatically
```

### 2. Check topology state
```bash
/topology drift pension
/topology well-depth pension
```

### 3. Train NG-RC when you have 50+ snapshots
```bash
/ngrc train pension
/ngrc predict pension 10
```

### 4. View in TUI
- Swarm overlay shows agent positions
- Temporal overlay (when implemented) would show drift vectors

## Next Implementation Steps

Priority order for making this experimentable:

1. **UnintegratedEvidence table + tracking** (database + TopologyService)
2. **Dissent energy computation** (add to snapshot persistence)
3. **Mode assessment function** (katrina/columbia/normal)
4. **Enhanced /sitrep** with phase portrait sections
5. **TUI overlay: drift vectors** (visual arrows on grid)
6. **TUI overlay: predicted trajectory** (NG-RC path visualization)

## The Columbia Test

When implementation is complete, we should be able to:

1. Load a domain with "foam strike" evidence
2. Run swarms that consistently mention it but don't integrate it
3. See `/sitrep` show:
   - "Floating evidence: foam-strike (4 runs, never integrated)"
   - "Dissent energy: HIGH"
   - "Mode: COLUMBIA"
4. Trigger counterfactual: "assume foam damaged TPS"
5. See consensus shift to different attractor
6. System recommends: "Resolve before decision"

That's the phase portrait saving Columbia.
