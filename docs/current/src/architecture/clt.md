# CLT Memory

Cross-Layer Transcoder (CLT) memory provides interpretable, sparse representations of agent state. Where standard latent memory uses dense 768-dim Nomic embeddings, CLT memory uses sparse feature vectors in a 20,480-dimensional feature space — typically ~115 active features per layer. This enables both efficient inter-agent communication and mechanistic interpretability of what agents attend to.

## Two Collaboration Modes

| Mode | Embedding | Storage | Token Reduction | Interpretability |
|------|-----------|---------|-----------------|-----------------|
| Standard (LatentMAS) | Nomic 768-dim dense | `gaius_latent_memory` | 70-90% vs text | Opaque |
| CLT-Enhanced | CLT 20,480-dim sparse | `gaius_clt_memory` | 70-90% vs text | Sparse feature indices are interpretable |

Both modes store embeddings in Qdrant and retrieve via semantic search. The key difference: CLT sparse features can be intersected across agents to find **feature consensus** — which specific features multiple agents independently activate on.

## Standard Latent Memory (LatentMAS)

Each agent stores its output as a 768-dim Nomic embedding in Qdrant. Subsequent agents retrieve relevant context via semantic search rather than receiving full text (Guo et al., 2024).

```
Agent 1 → thinks → store embedding in Qdrant
Agent 2 → query Qdrant for relevant context → thinks → store embedding
Leader → retrieve all → synthesize
```

The collection schema includes domain, agent_id, session_id, and timestamp — enabling both within-session collaboration and longitudinal analysis.

## CLT-Enhanced Memory

The `CLTLatentMemory` extracts sparse features from model activations using circuit-tracer (from BluelightAI):

```python
thought = await clt_memory.store_from_content(
    agent_id="critic",
    content="The risk model underestimates tail events.",
    domain="pension",
)
# thought.features.active_indices — ~115 active of 20,480 total
```

**Feature consensus**: Given multiple agents' CLT features for a domain, the intersection of active feature indices reveals which features the swarm collectively attends to. High agreement ratios indicate convergent analysis; low ratios indicate diverse perspectives.

## CLT Projection Bridge

The `CLTProjectionBridge` maps sparse CLT features to the same coordinate space as dense Nomic embeddings, enabling unified visualization on the 19x19 grid:

```
CLT sparse features (20,480-dim) → learned projection → ColNomic (768-dim) → UMAP → grid position
```

This bridge also enables:
- **TraceEmbedder** — Converts agent execution traces (step, action, state hash) to grid-plottable embeddings
- **AgentStateDecoder** — Bidirectional: grid position → inferred agent focus domain and confidence

## Integration with Topology

The `TopologyService` consumes CLT features to detect **semantic attractors** — regions in embedding space where agent attention converges:

```
CLTService → extract features → TopologyService → detect attractors → grid overlay
```

Attractors appear as persistent concentrations of agent positions on the lattice, visible in the TUI's agent overlay mode.

## CLI Commands

```bash
# Extract CLT features for current context
uv run gaius-cli --cmd "/clt extract" --format json

# CLT memory statistics
uv run gaius-cli --cmd "/clt stats" --format json

# Latent memory statistics
uv run gaius-cli --cmd "/latent stats" --format json
```
