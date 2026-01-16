# Cross-Layer Transcoders + LatentMAS Research

## Overview

This document explores integrating BluelightAI's Cross-Layer Transcoders (CLTs) with a true LatentMAS implementation for Gaius. The key insight is that CLTs provide the infrastructure to operate on **interpretable latent features** rather than raw embeddings, enabling genuine latent-space agent communication.

## References

- [BluelightAI Qwen3 Explorer](https://bluelightai.com/blog/qwen3-explorer)
- [Cross-Layer Transcoders LessWrong Post](https://www.lesswrong.com/posts/cW9AdDm2DZtbXBnvt/cross-layer-transcoders-for-the-qwen3-llm-family)
- [Transcoders Find Interpretable LLM Feature Circuits (arXiv:2406.11944)](https://arxiv.org/abs/2406.11944)
- [Circuit Tracing Methods (Anthropic)](https://transformer-circuits.pub/2025/attribution-graphs/methods.html)
- [circuit-tracer GitHub](https://github.com/safety-research/circuit-tracer)
- [BluelightAI CLT Feature Explorer](https://qwen3.bluelightai.com/)

## Model: bluelightai/clt-qwen3-1.7b-base-20k

**Key Specifications:**
- Base model: Qwen3-1.7B-Base
- Features per layer: 20,480 (20x expansion)
- Total features: ~573,000 across all layers
- L0 sparsity: ~115 active features per layer
- Training: 750M tokens (web, books, code, math)

**Loading:**
```python
import torch
from circuit_tracer import ReplacementModel

model_name = "Qwen/Qwen3-1.7B-Base"
transcoder_name = "bluelightai/clt-qwen3-1.7b-base-20k"
clt = ReplacementModel.from_pretrained(model_name, transcoder_name, dtype=torch.bfloat16)
```

## How Cross-Layer Transcoders Work

### Architecture

1. **Encoder**: Maps MLP layer inputs → sparse feature activations (20,480 features)
   - Uses JumpReLU activation for sparsity
   - Each layer has its own encoder

2. **Decoder**: Reconstructs MLP outputs from features
   - **Cross-layer**: Features at layer ℓ can decode to ALL subsequent layers
   - Shape: `(d_latent, n_out_layers, d_model)`

3. **Attribution**: Edge weight A_{s→t} = a_s × w_{s→t}
   - a_s = source feature activation
   - w_{s→t} = virtual weight from CLT decoder

### Why Cross-Layer Matters

Traditional single-layer transcoders require tracing through every layer sequentially. Cross-layer transcoders allow:
- Direct feature influence across multiple layers
- Shorter, more interpretable circuits
- Reduced redundancy in feature representations

## True LatentMAS Architecture Proposal

### Current Problem

The existing "LatentMAS" in Gaius is not truly latent:
- Agents produce text → embed to 768-dim Nomic vector
- Other agents receive **text summaries** of stored thoughts
- Embeddings only used for retrieval, not communication

### CLT-Based LatentMAS

With CLTs, we can implement genuine latent communication:

```
Agent A                          Agent B
   │                                │
   ▼                                │
[Qwen3-1.7B + CLT]                  │
   │                                │
   ▼                                │
Sparse Features (L0≈115)────────────┤
   │                                ▼
   │                       [CLT Decoder]
   │                                │
   │                                ▼
   │                       [Qwen3-1.7B continues]
   │                                │
   ▼                                ▼
Output A                       Output B
```

### Key Operations

1. **Feature Extraction** (Agent A output)
   ```python
   # Get sparse features from CLT encoder
   features = clt.encode(hidden_states)  # Shape: (seq_len, 20480), sparse
   active_features = features.nonzero()  # Only ~115 active per position
   ```

2. **Feature Message** (Latent communication)
   ```python
   @dataclass
   class LatentMessage:
       source_agent: str
       layer_idx: int
       active_features: list[int]      # Feature indices
       activations: list[float]        # Activation magnitudes
       semantic_labels: list[str]      # From BluelightAI dashboard
   ```

3. **Feature Injection** (Agent B receives)
   ```python
   # Inject features into Agent B's computation
   injected = clt.decode_features(message.active_features, message.activations)
   # Continue Qwen3 forward pass with injected features
   ```

### TDA Integration (Cobalt)

BluelightAI uses Cobalt (TDA) for feature visualization:
- Neighborhoods of similar features clustered at multiple resolutions
- Weighted graphs from encoder/decoder vectors
- Coactivation patterns reveal feature relationships

This aligns perfectly with Gaius's existing TDA infrastructure!

## Implementation Roadmap

### Phase 1: Infrastructure (1-2 weeks)

1. **Install dependencies**
   ```bash
   uv add circuit-tracer transformers torch
   # May need patched transformer-lens for Qwen3
   ```

2. **CLT Model Loading**
   - Create `gaius.models.clt` module
   - Load `bluelightai/clt-qwen3-1.7b-base-20k`
   - Validate with feature extraction test

3. **Feature Registry**
   - Map feature indices → semantic labels
   - Integrate BluelightAI dashboard data
   - Store in KB for ThetaAgent to reference

### Phase 2: Latent Message Protocol (1-2 weeks)

1. **LatentMessage dataclass**
   - Sparse feature representation
   - Provenance tracking (which agent, which layer)
   - Semantic annotations

2. **LatentChannel**
   - Replace Qdrant embedding storage with feature storage
   - Similarity via feature overlap, not cosine similarity
   - Feature-based consensus (union/intersection of active features)

3. **Feature Injection API**
   - Inject messages into running Qwen3 inference
   - Multiple injection points (different layers)
   - Attention to injected features

### Phase 3: CLT-Based Swarm (2-3 weeks)

1. **LatentSwarm reimplementation**
   - Agents share sparse features, not embeddings
   - Cross-agent feature influence tracking
   - Circuit graphs across agent boundaries

2. **Consensus via Feature Voting**
   - Each agent votes on feature importance
   - Consensus = weighted feature intersection
   - Disagreement = feature divergence analysis

3. **Attribution Graphs for Multi-Agent**
   - Extend circuit-tracer to track inter-agent edges
   - Visualize which features influenced which agents

### Phase 4: TDA Integration (1-2 weeks)

1. **Feature Topology**
   - Apply Gaius TDA to feature activation space
   - Persistent homology on feature coactivation graphs
   - Mapper graphs for feature clustering

2. **Theta-Mediated Consolidation**
   - ThetaAgent monitors feature drift across time
   - NVAR operates on feature centroids, not embeddings
   - Subsumption inferred from feature hierarchies

## GPU Requirements

- Qwen3-1.7B: ~4GB VRAM
- CLT encoder/decoder: ~2GB additional
- Multiple agents: Need model parallelism or separate GPUs

With Gaius's battery of GPUs, we can run:
- 1 GPU: Base Qwen3 model
- 1 GPU: CLT encoder/decoder
- Remaining: Parallel agent instances or larger models

## Open Questions

1. **Feature stability across contexts**: Do the same features activate for the same concepts across different prompts?

2. **Injection layer selection**: Which layer(s) are best for injecting external features?

3. **Feature vocabulary alignment**: Can features transfer between Qwen3-0.6B and Qwen3-1.7B CLTs?

4. **Latency**: What's the overhead of CLT encoding/decoding per token?

5. **Training data for feature labels**: How to systematically annotate all 573K features?

## Connection to Gunnar Carlsson's Work

BluelightAI (Gunnar Carlsson's company) brings deep TDA expertise:
- Cobalt uses mapper-style algorithms for feature graphs
- Multi-resolution clustering echoes persistent homology
- Feature neighborhoods = topological proximity

This creates a natural bridge between:
- Gaius's TDA infrastructure (giotto-tda, UMAP projections)
- CLT feature topology (Cobalt graphs)
- ThetaAgent's temporal consolidation (NVAR on feature space)

## Next Steps

1. **Validate setup**: Load CLT model, extract features from test prompt
2. **Feature exploration**: Use BluelightAI dashboard to understand key features
3. **Prototype injection**: Inject features from Agent A into Agent B's context
4. **Measure fidelity**: Does feature-based communication preserve semantic intent?
