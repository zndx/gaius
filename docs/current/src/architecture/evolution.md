# Evolution

The evolution subsystem optimizes agent system prompts using APO (Automatic Prompt Optimization) during GPU idle periods. It generates candidate prompts, evaluates them against held-out tasks, and promotes winners.

## Evolution Cycle

```
1. Wait for GPU idle (<30% utilization)
2. Select next agent (round-robin)
3. Generate candidate prompts
4. Evaluate against held-out tasks
5. Promote best if improved
6. Record lineage
```

## Optimization Methods

| Method | Description |
|--------|-------------|
| APO | Automatic Prompt Optimization (Zhou et al., 2023) |
| GEPA | Genetic Evolution of Prompt Architectures |

## Model Merging

Agent versions can be combined using parameter-space merging:

| Method | Description |
|--------|-------------|
| Linear | Weighted average of parameters |
| TIES | Resolves sign conflicts between models |
| DARE | Drop and rescale for sparse merging |

## Agent Versioning

Each evolution cycle produces a new agent version with tracked lineage:

```python
# Check evolution status
uv run gaius-cli --cmd "/evolve status" --format json

# View agent versions
uv run gaius-cli --cmd "/evolve versions leader" --format json

# Promote a specific version
uv run gaius-cli --cmd "/evolve promote leader v3" --format json
```

## Configuration

```hocon
evolution {
    enabled = true
    idle_threshold = 60    # seconds of GPU idle before triggering
    cycle_interval = 3600  # minimum seconds between cycles
}
```

The daemon runs in the engine process and activates only during GPU idle periods to avoid competing with interactive inference.
