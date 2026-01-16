# CLT→ColNomic Projection Bridge: Unified Agent/Document Grid Space

## Overview

This document describes the architecture for projecting CLT (Cross-Layer Transcoder) sparse features into the same embedding space as KB documents, enabling agents to be positioned semantically on the 19×19 grid alongside knowledge base content.

## Problem Statement

Previously, agent positions on the swarm grid were **randomized** based on `projection_behavior` (center/peripheral/random). This meant:

1. Agent positions had no semantic meaning
2. Agents occupied a different "space" than KB documents
3. Exploration dynamics were invisible
4. Feature consensus wasn't reflected spatially

## Architecture

### The Bidirectional Latent Channel

```
Text Input → CLT Encoder → Sparse Features (20,480-dim interpretable)
                               ↓
                    [Agent reasoning in latent space]
                               ↓
Sparse Features → CLT Decoder → Text Output (when needed)
                               ↓
Sparse Features → CLT→ColNomic Bridge → 128-dim embedding → UMAP → Grid (x,y)
                                        ↑
                              [Same space as KB documents]
```

### Key Components

1. **CLTProjectionBridge** (`agents/latent/clt_projection.py`)
   - Projects 20,480-dim sparse features to 128-dim ColNomic-compatible embeddings
   - Uses hash-based sparse random projection (Johnson-Lindenstrauss)
   - L2 normalized output for compatibility with KB embeddings

2. **TraceEmbedder** (same file)
   - Implements NVAR/NG-RC style time-delay embedding
   - Captures exploration trajectory, not just current position
   - `delay_steps=3` gives `(1+3) * 128 = 512` effective dimensions

3. **CLTLatentSwarmManager._update_positions** (`agents/swarm.py`)
   - Overrides random positioning with semantic projection
   - Uses KB's fitted UMAP projector for coordinate mapping
   - Falls back to random if projector not fitted

### Projection Pipeline

```python
# 1. Extract CLT sparse features from agent response
features = await clt_memory.extract_features(response.content)
# → {100: 0.5, 203: 0.8, 500: 0.3, ...}  ~115 active features

# 2. Project to ColNomic embedding space
bridge = get_clt_projection_bridge()
embedding = bridge.project_sparse_features(features)
# → (128,) normalized vector

# 3. Update trace history
trace_embedder.update(agent_role, embedding)
# → Stores [current, t-1, t-2, t-3] for trajectory

# 4. Project to grid via KB's UMAP
coords_2d = projector._projector.transform([embedding])
grid_coords = projector._normalize_to_grid(coords_2d)
# → (x, y) in [0, 18] range
```

## Semantic Implications

### Agents in KB Space

- **Near a KB document**: Agent is "thinking about" concepts similar to that document
- **Cluster of agents**: Agreement on conceptual territory
- **Agent far from documents**: Exploring novel concepts outside KB

### Time-Delay Traces

The `TraceState` captures exploration history:

```python
@dataclass
class TraceState:
    current_embedding: np.ndarray      # Where agent is NOW
    delayed_embeddings: list           # [t-1, t-2, t-3]

    @property
    def full_state(self) -> np.ndarray:
        return concat([current, t-1, t-2, t-3])  # (512,)
```

This enables:
- **Trajectory visualization**: Draw trails on grid showing where agent has been
- **Attractor detection**: Identify when agents converge/oscillate
- **Expanded manifold**: The 512-dim state captures dynamics beyond static position

## Visualization

### Current Implementation

Agents are positioned semantically (CLT→ColNomic→UMAP→Grid), with exploration traces showing recent positions:

```
Grid Markers:
  ● (bold)   - Current agent position
  ◉ (normal) - t-1 position (previous step)
  ○ (dim)    - t-2 position (two steps ago)
  · (very dim) - t-3+ positions (older history)
```

Trace colors match the agent's role color, with fading intensity for older positions.

### State Integration

```python
# AppState fields for trace visualization
state.agent_positions: list  # [(name, x, y, color), ...]
state.agent_traces: dict     # {agent_name: [(x, y), ...], ...}

# CLI command updates state after CLT swarm
result = await manager.run_round(domain, context)
state.agent_positions = manager.get_agent_positions()
state.agent_traces = manager.get_agent_traces()
```

### Usage

```bash
# Run CLT swarm (updates state with positions and traces)
uv run gaius-cli --cmd "/swarm clt pension" --format json

# View in TUI (press 'v' to cycle to SWARM mode)
uv run gaius
```

### Future Enhancements
- **Exploration edges**: Lines between agent and KB documents it relates to
- **Feature consensus heatmap**: Overlay showing which grid regions have agent agreement
- **Time-delay projection**: Alternative view using full trace state for UMAP
- **Decoded tooltips**: Show decoded feature summaries on agent hover

## Bidirectional Latent Channel

The architecture supports a complete bidirectional channel where agents can:
1. **Think in latent space** (CLT sparse features)
2. **Decode to text** only when output is needed
3. **Project to grid** for visualization

### AgentStateDecoder

```python
from gaius.agents.latent import get_agent_state_decoder

decoder = get_agent_state_decoder()

# Local summary (fast, no LLM)
summary = decoder.summarize_features(sparse_features)
# → "complex/high (127 features)"

# Full text decode (via Engine/CLT)
result = await decoder.decode_state(
    sparse_features=thought.aggregated_features,
    context="What is the agent considering?",
    max_tokens=50,
)
# → {"generated_text": "The agent is analyzing...", ...}
```

### End-to-End Flow

```
User Query
    ↓
Agent receives query
    ↓
CLT encodes context → sparse features (20,480-dim)
    ↓
Agent "thinks" in feature space
    ↓
┌─────────────────────────────────────┐
│ Bidirectional Options:              │
│                                     │
│  → Project to grid (visualization)  │
│    CLT→ColNomic→UMAP→(x,y)         │
│                                     │
│  → Decode to text (output)         │
│    CLT features→decoder→text       │
│                                     │
│  → Embed for storage               │
│    decoded text→ColNomic→Qdrant    │
└─────────────────────────────────────┘
```

The decoded text naturally flows through the embedding pipeline:
- Decoded text can be embedded via ColNomic
- Those embeddings project to the same grid space
- This creates a coherent loop where thoughts, documents, and outputs share coordinates

## References

- Cross-Layer Transcoders: arXiv:2406.11944
- LatentMAS: Multi-agent communication via latent representations
- NVAR/NG-RC: arXiv:2012.14572, arXiv:2108.10784
- BluelightAI Qwen3 CLT: https://bluelightai.com/blog/qwen3-explorer
