# Core Concepts

Gaius integrates three conceptual pillars: **spatial representation**, **topological analysis**, and **agentic collaboration**. This section introduces the foundational ideas; subsequent chapters explore each in depth.

## The Grid

At the center of Gaius is a 19×19 board. This isn't a chart or a dashboard—it's a **canvas for projection**.

High-dimensional data (embeddings, agent states, risk surfaces) gets compressed onto 361 addressable points. The compression is lossy by design: it forces salience. What survives projection is what matters.

The grid supports multiple visualization modes:
- **Point markers**: Individual data points as stones
- **Density heatmaps**: Aggregate intensity via shading (▓▒░·)
- **Topology overlays**: Death loops and persistent features
- **Agent positions**: Swarm state projected from embedding space

See [The Grid Metaphor](./concepts/grid.md) for the full treatment.

## Embeddings

Modern ML represents entities as vectors in high-dimensional space. Text, images, users, documents—all become points in a geometric landscape where distance encodes similarity.

Gaius consumes these embeddings directly. Agent utterances become vectors. Domain entities become vectors. The relationships between them—cosine similarities, clusters, outliers—become spatial relationships on the grid.

See [Embeddings & Point Clouds](./concepts/embeddings.md) for details on how Gaius handles vector representations.

## Persistent Homology

Traditional statistics describe data's *distribution*. Topology describes its *shape*.

Persistent homology asks: as we vary the scale of observation, what features persist?

- **H0 features** (connected components): Clusters that remain distinct
- **H1 features** (loops): Cycles that don't collapse—the "death loops"
- **H2 features** (voids): Empty regions bounded by surfaces

These topological features often reveal structure invisible to statistical methods: feedback loops in systems, circular dependencies in code, liquidity traps in markets.

See [Persistent Homology](./concepts/homology.md) for the mathematical foundations and practical applications.

## Multi-Agent Swarms

Complex domains benefit from multiple analytical perspectives. Gaius instantiates specialized agents:

| Agent | Role |
|-------|------|
| Leader | Orchestrates strategy, synthesizes insights |
| Risk | Identifies threats, failure modes, tail events |
| Optimizer | Seeks opportunities, efficiency gains |
| Planner | Constructs long-term trajectories |
| Critic | Challenges assumptions, stress-tests conclusions |
| Executor | Simulates actions, projects outcomes |
| Adversary | Actively attempts to break the plan |

Each agent's outputs are embedded and projected onto the grid. Their positions reveal consensus and disagreement, convergence and divergence.

See [Multi-Agent Swarms](./architecture/swarms.md) for implementation details.

## Vector Memory

Agent utterances accumulate in a vector store. This enables:

- **Semantic search**: Find past insights by meaning, not keywords
- **Scene graphs**: Build relationship networks from embedding similarity
- **Temporal analysis**: Track how the swarm's collective understanding evolves

The memory isn't just storage—it's the substrate from which topological features emerge.

See [Vector Memory](./architecture/memory.md) for the technical architecture.

## Putting It Together

A typical Gaius session:

1. **Initialize** with a domain: `--domain "pension asset allocation"`
2. **Observe** the initial grid state—random or seeded from prior data
3. **Run a swarm round** (`s`): Agents analyze, their positions update
4. **Overlay topology** (`o`): See where death loops emerge
5. **Navigate** (`hjkl`): Explore regions of interest
6. **Query** (slash commands): Ask specific questions
7. **Iterate**: Each round refines the collective understanding

The grid becomes a living map of your domain's complexity—updated in real-time as agents explore and topology reveals hidden structure.

