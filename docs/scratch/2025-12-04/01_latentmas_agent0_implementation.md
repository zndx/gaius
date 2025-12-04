# LatentMAS + Agent0 Implementation Summary

## Overview

Implemented two complementary systems for agent self-improvement:

1. **LatentMAS-style Latent Collaboration**: Agents share 768-dim Nomic embeddings via Qdrant working memory instead of full text (70-90% token reduction)

2. **Agent0-style Background Evolution**: GPU-idle-triggered self-improvement with curriculum agent proposing tasks at ~70% success rate (zone of proximal development)

## Files Created

### Latent Module (`src/gaius/agents/latent/`)

- `__init__.py` - Module exports
- `memory.py` - `LatentWorkingMemory` class with Qdrant backend
  - `LatentThought` dataclass (id, agent_role, content_summary, embedding, domain)
  - `store()` / `retrieve_similar()` / `get_consensus()` / `clear_domain()`

### Evolution Module (`src/gaius/agents/evolution/`)

- `__init__.py` - Module exports
- `preemption.py` - `PreemptedError` and `PreemptionManager` for yield-on-demand
- `daemon.py` - `EvolutionDaemon` with GPU idle detection
  - Monitors utilization, runs when below threshold (default 20%)
  - Rate-limited (default 10 cycles/hour)
  - Immediate preemption for interactive requests
- `curriculum.py` - `CurriculumAgent` for task generation
  - `EvolutionTask` dataclass with category, difficulty, evaluation criteria
  - Targets 70% success rate for optimal learning
- `collector.py` - `TrainingCollector` for gathering examples
  - Sources: high-scoring swarm outputs, cognition thoughts, research outputs

## Files Modified

### `src/gaius/agents/swarm.py`

Added `LatentSwarmManager` extending `SwarmManager`:
- Two-phase execution: first batch (Leader, Risk, Optimizer) populates working memory
- Second batch retrieves latent context from embeddings
- `run_latent_swarm_round()` convenience function

### `src/gaius/agents/__init__.py`

Added exports:
- `LatentSwarmManager`, `get_latent_swarm_manager`, `run_latent_swarm_round`
- `get_latent_memory()`, `get_evolution_daemon()` lazy imports

### `src/gaius/mcp_server.py`

Added 7 MCP tools:
- `evolution_status` - Daemon status and metrics
- `trigger_evolution` - Manual optimization cycle
- `start_evolution_daemon` / `stop_evolution_daemon`
- `latent_memory_stats` - Qdrant collection stats
- `run_latent_swarm` - Execute latent-enabled swarm
- `clear_latent_memory` - Clear domain thoughts

### `config/base.conf`

Added configuration sections:
```hocon
evolution {
  enabled = true
  idle_threshold = 20      # GPU %
  min_idle_duration = 30   # seconds
  strategy = "gepa"        # apo, gepa, hybrid
  agents = ["leader", "risk", "optimizer", "critic", "synthesizer"]
}

latent {
  enabled = true
  collection = "gaius_latent_thoughts"
  max_thoughts_per_domain = 100
  similarity_threshold = 0.5
  clear_on_run = true
}
```

## Key Design Decisions

1. **Qdrant for persistence** - Already integrated, 768-dim Nomic embeddings, cosine similarity
2. **Full preemptive daemon** - Background evolution yields immediately for interactive requests
3. **Two-phase swarm execution** - First batch generates, second batch retrieves context
4. **Zone of proximal development** - Target 70% success rate for curriculum difficulty

## Usage

```python
# Start evolution daemon
from gaius.agents import get_evolution_daemon
daemon = get_evolution_daemon()
await daemon.start()

# Run latent-enabled swarm
from gaius.agents import run_latent_swarm_round
result = await run_latent_swarm_round("pension analysis", "retirement planning context")

# Get latent memory stats
from gaius.agents import get_latent_memory
memory = get_latent_memory()
stats = await memory.get_stats()
```

## Verification

All modules verified to import correctly:
- `gaius.agents.latent` - OK
- `gaius.agents.evolution` - OK
- `gaius.agents.swarm.LatentSwarmManager` - OK
- HOCON config parsing - OK
- MCP server syntax - OK

## References

- Agent0 paper: arXiv:2511.16043 "Unleashing Self-Evolving Agents from Zero Data"
- LatentMAS paper: arXiv:2511.20639 "Latent Space Collaboration"
- Research saved to KB: `current/research/agent0_latentmas_2025.md`
