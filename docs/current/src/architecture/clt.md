# CLT Memory

Cross-Layer Transcoder (CLT) memory extracts sparse features from model activations, providing interpretable representations of agent state.

## How It Works

The CLTService extracts sparse features from inference activations using circuit-tracer:

```python
state = await clt.extract_features(
    agent_id="critic",
    content="The risk model has issues...",
)
# state.features.active_indices — which features activated
```

## Swarm Features

CLT features can be computed across a swarm to find consensus:

```python
swarm_result = await clt.compute_swarm_features(domain="pension")
# swarm_result.consensus_features — features active across multiple agents
```

## Integration with Topology

The TopologyService consumes CLT features to detect semantic attractors — regions in embedding space where agent attention converges:

```
CLTService → extract features → TopologyService → detect attractors → grid overlay
```

## Qdrant Collections

CLT features are stored in dedicated Qdrant collections:

| Collection | Purpose |
|------------|---------|
| `gaius_clt_memory` | Cross-Layer Transcoder feature history |
| `gaius_latent_memory` | Latent working memory for swarm coordination |

## CLI Commands

```bash
# Extract CLT features
uv run gaius-cli --cmd "/clt extract" --format json

# CLT memory statistics
uv run gaius-cli --cmd "/clt stats" --format json
```
