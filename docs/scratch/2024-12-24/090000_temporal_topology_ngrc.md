# Temporal Topology Tracking with NG-RC Forward Dynamics

**Date:** 2024-12-24
**Status:** Complete

## Overview

Implemented temporal topology tracking for swarm dynamics, enabling:
1. **Drift detection**: How consensus positions change over time (dx/dt)
2. **Well depth**: Entrenchment measurement (1/variance)
3. **NG-RC integration**: Forward dynamics prediction without LLM calls
4. **Non-autonomous dynamics**: dx/dt = f(x, KB(t)) where KB is growing

## Key Philosophical Concepts

- Every swarm run is a snapshot of a living topology
- KB growth raises the floor of old potential wells
- Productive instability prevents ossification
- Ontological drift: terms change meaning over time

## Components Implemented

### 1. Database Schema (`db/migrations/20251224000001_swarm_temporal_topology.sql`)

Five new tables in `meta` schema:
- `swarm_snapshots`: Point-in-time capture of swarm state
- `swarm_agent_positions`: Individual agent positions within snapshots
- `topology_drift`: Drift metrics over time
- `ngrc_models`: NG-RC trained model storage
- `semantic_attractors`: Named stable states tracking

### 2. TopologyService (`engine/services/topology_service.py`)

Core service for temporal topology tracking:
- `save_snapshot()`: Persist swarm state after CLT processing
- `compute_drift()`: Calculate drift velocity, well depth, Lyapunov exponent
- `get_snapshot_history()`: Retrieve historical snapshots
- `register_attractor()` / `update_attractor()`: Track semantic attractors
- `get_training_data()`: Extract time series for NG-RC training
- `save_ngrc_model()` / `load_ngrc_model()`: Persist trained models

### 3. NGRCPredictor (`engine/services/ngrc.py`)

Next-Generation Reservoir Computing for forward dynamics:
- Uses polynomial features of time-delay embeddings
- Learns dx/dt = f(x) from trajectory data
- No reservoir - direct polynomial regression
- Tracks KB growth for retraining triggers

Key hyperparameters:
- `n_delays`: Number of time steps in delay embedding (default: 5)
- `poly_degree`: Polynomial feature degree (default: 2)
- `ridge_alpha`: L2 regularization (default: 1e-4)

### 4. CLI Commands

**Topology Commands:**
```bash
/topology status           # Service status
/topology drift <domain>   # Show drift metrics
/topology history <domain> # Snapshot history
/topology well-depth <domain> # Entrenchment
/topology attractors <domain> # Named stable states
```

**NG-RC Commands:**
```bash
/ngrc status              # Model status for all domains
/ngrc train <domain>      # Train on domain snapshots
/ngrc predict <domain> N  # Predict N steps ahead
/ngrc model <domain>      # Model details
```

### 5. Integration Points

- SwarmStream in `gaius_servicer.py` now persists snapshots after CLT processing
- ServiceRegistry extended with `topology_service`
- Engine startup initializes TopologyService with asyncpg pool

## Usage Example

```python
# After swarm run, snapshot is automatically saved
# To predict future trajectory:

predictor = NGRCPredictor()
model_weights = await topology_service.load_ngrc_model("pension")
predictor.load(model_weights)

current_state = await topology_service.get_snapshot_history("pension", limit=1)
prediction = predictor.predict(current_state[0].consensus_embedding, n_steps=10)

print(f"Predicted trajectory: {prediction.grid_trajectory}")
print(f"Reliable steps: {prediction.reliable_steps}")
```

## Key Metrics

- **Drift Magnitude**: Rate of change in semantic space
- **Well Depth**: 1/variance - high means stable but potentially stuck
- **Lyapunov Exponent**: Negative = stable, positive = chaotic
- **Forecast Horizon**: Reliable prediction steps before error grows

## Non-Autonomous Dynamics

The flow field is parameterized by KB state:
```
dx/dt = f(x, KB(t))
```

As KB grows:
- Old attractors may become less stable
- New attractors may emerge
- Model needs periodic retraining

The `needs_retraining()` method tracks KB growth and signals when the model should be retrained.

## Files Changed

- `db/migrations/20251224000001_swarm_temporal_topology.sql` (new)
- `src/gaius/engine/services/topology_service.py` (new)
- `src/gaius/engine/services/ngrc.py` (new)
- `src/gaius/engine/services/__init__.py` (updated exports)
- `src/gaius/engine/grpc/server.py` (added topology_service)
- `src/gaius/engine/server.py` (initialization)
- `src/gaius/engine/grpc/servicers/gaius_servicer.py` (snapshot persistence)
- `src/gaius/cli.py` (topology and ngrc commands)
