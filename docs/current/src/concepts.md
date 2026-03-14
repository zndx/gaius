# Core Concepts

Gaius integrates several conceptual pillars: **spatial representation**, **topological analysis**, **autonomous agents**, and **self-healing infrastructure**. This section introduces the foundational ideas; subsequent chapters explore each in depth.

## The Grid

At the center of Gaius is a 19x19 board. This isn't a chart or a dashboard — it's a **canvas for projection**.

High-dimensional data (embeddings, agent states, risk surfaces) gets compressed onto 361 addressable points. The compression is lossy by design: it forces salience. What survives projection is what matters.

The grid supports multiple visualization modes:
- **Point markers**: Individual data points as stones
- **Density heatmaps**: Aggregate intensity via shading
- **Topology overlays**: Death loops and persistent features
- **Agent positions**: Agent state projected from embedding space

See [The Grid Metaphor](./concepts/grid.md) for the full treatment.

## Embeddings

Modern ML represents entities as vectors in high-dimensional space. Text, images, users, documents — all become points in a geometric landscape where distance encodes similarity.

Gaius consumes these embeddings directly. Agent utterances become vectors. Domain entities become vectors. Cards, articles, and knowledge base entries occupy positions in embedding space. The relationships between them — cosine similarities, clusters, outliers — become spatial relationships on the grid.

See [Embeddings & Point Clouds](./concepts/embeddings.md) for details on how Gaius handles vector representations.

## Persistent Homology

Traditional statistics describe data's *distribution*. Topology describes its *shape*.

Persistent homology asks: as we vary the scale of observation, what features persist?

- **H0 features** (connected components): Clusters that remain distinct
- **H1 features** (loops): Cycles that don't collapse — the "death loops"
- **H2 features** (voids): Empty regions bounded by surfaces

These topological features often reveal structure invisible to statistical methods: feedback loops in systems, circular dependencies in code, liquidity traps in markets.

See [Persistent Homology](./concepts/homology.md) for the mathematical foundations and practical applications.

## Autonomous Agents

Gaius agents are not static analyzers — they evolve. Through RLVR (Reinforcement Learning with Verifiable Reward) training, agents improve their capabilities over time. The agent system includes:

- **Evolution**: Task ideation, training runs, and capability evaluation
- **Cognition**: Self-observation and action planning
- **Theta consolidation**: Memory compression inspired by hippocampal replay
- **CLT memory**: Cognitive Load Theory-based knowledge structuring

See [Agent System](./architecture/agents.md) for implementation details.

## Self-Healing

Gaius implements autonomous health monitoring based on FMEA (Failure Mode and Effects Analysis). Every failure mode has:

- A **Guru Meditation Code** for unique identification (e.g., `#DS.00000001.SVCNOTINIT`)
- An **automated fix strategy** that can diagnose, repair, and verify
- An **escalation path** to ACP (Agent Client Protocol) when self-healing fails

Errors are never silenced. The system either fixes itself or tells you exactly what's wrong and how to fix it.

See [Fail-Fast & Self-Healing](./concepts/fail-fast.md) for the design principles.

## Putting It Together

A typical Gaius session:

1. **Launch** the TUI: `uv run gaius`
2. **Observe** the grid state — entity positions projected from embedding space
3. **Navigate** (`hjkl`): Explore regions of interest
4. **Overlay** (`o`): See topology, risk, or agent state
5. **Command** (`/`): Run slash commands for deeper analysis
6. **Monitor** (`/health`): Check system health, let self-healing handle issues

The grid becomes a living map of your domain's complexity — updated as agents explore and topology reveals hidden structure.
