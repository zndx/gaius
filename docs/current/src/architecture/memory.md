# Vector Memory

Vector Memory is the persistent substrate from which all analysis emerges. It stores embeddings, enables semantic retrieval, and provides the point cloud for topological analysis.

## Core Data Structure

```python
class DomainVectorMemory:
    def __init__(self):
        self.utterances: List[tuple[int, str, np.ndarray]] = []
        self.graph: List[tuple[int, int, float]] = []
```

Each utterance is a triple:
- **agent_id**: Which agent produced this
- **text**: The raw response
- **embedding**: 1536-dimensional vector

## Embedding Pipeline

When an agent responds, the text is embedded with domain context:

```python
async def add(self, agent_id: int, text: str, domain: str):
    emb = np.array(embedder.embed_query(f"{domain}: {text}"))
    self.utterances.append((agent_id, text, emb))
```

Prepending the domain to the text biases the embedding toward domain-specific semantics. "Risk" in pension analysis embeds differently than "Risk" in cybersecurity.

## Scene Graph Construction

The scene graph connects semantically related utterances:

```python
def build_scene_graph(self, domain_prompt: str, threshold: float = 0.7):
    embs = np.stack([u[2] for u in self.utterances])

    # Cosine similarity
    sim = np.dot(embs, embs.T) / (norms + 1e-8)

    # Domain keyword boosting
    domain_keywords = set(domain_prompt.lower().split())
    for i in range(len(self.utterances)):
        for j in range(i+1, len(self.utterances)):
            overlap = keyword_overlap(text_i, text_j, domain_keywords)
            sim[i, j] *= (1 + overlap)

    # Threshold to edges
    edges = [(i, j, sim[i,j]) for i, j in pairs if sim[i,j] > threshold]
    return edges
```

The resulting graph reveals which utterances are related—useful for clustering analysis and attention routing.

## Point Cloud Generation

For visualization and TDA, utterances are projected to a dense point cloud:

```python
def to_point_cloud(self) -> np.ndarray:
    if not self.utterances:
        return np.random.randn(20, 50)  # Seed cloud

    embs = np.stack([u[2] for u in self.utterances])
    pca = PCA(n_components=50)
    return pca.fit_transform(embs)
```

The 50-dimensional intermediate representation balances:
- **Preservation**: Enough dimensions to capture structure
- **Efficiency**: Low enough for fast TDA computation

## Semantic Search

Retrieve utterances by meaning:

```python
def search(self, query: str, k: int = 5) -> List[tuple]:
    query_emb = embedder.embed_query(query)
    similarities = [
        (i, cosine_sim(query_emb, u[2]))
        for i, u in enumerate(self.utterances)
    ]
    return sorted(similarities, key=lambda x: -x[1])[:k]
```

This enables slash commands like `/recall inflation` to surface relevant past analysis.

## Temporal Indexing

Utterances are stored in chronological order. This enables:

- **History replay**: See how understanding evolved
- **Temporal queries**: "What did Risk say in round 3?"
- **Drift detection**: Track how agent positions change over time

## Memory Lifecycle

```
Domain Set/Changed
       │
       ▼
  Memory Cleared
       │
       ▼
  Swarm Round 1
       │
       ▼
  Utterances Stored ──► Point Cloud Generated ──► TDA Computed
       │
       ▼
  Swarm Round 2
       │
       ▼
  Utterances Appended ──► Cloud Updated ──► TDA Recomputed
       │
       ▼
     ...
```

Memory accumulates within a domain session. Domain changes trigger a fresh start.

## Persistence (Future)

Currently, memory is ephemeral—lost when the application exits. Planned enhancements:

- **SQLite backend**: Persist utterances with timestamps
- **Session management**: Resume previous analysis sessions
- **Export**: Dump memory to JSON for external analysis
- **Import**: Seed memory from prior analyses or external data

## Integration Points

### With TDA
```python
cloud = memory.to_point_cloud()
tda_result = run_tda(cloud)
```

### With Swarm
```python
await memory.add(agent_id, response, domain)
memory.build_scene_graph(domain)
```

### With Board
```python
# Cloud → 2D projection → grid positions
x_grid, y_grid = project_to_grid(memory.to_point_cloud())
```

## Performance Characteristics

| Operation | Complexity | Notes |
|-----------|------------|-------|
| Add utterance | O(1) | Append to list |
| Build scene graph | O(n²) | Pairwise similarity |
| Search | O(n) | Linear scan (optimize with FAISS for scale) |
| To point cloud | O(n × d) | PCA fit_transform |

For typical sessions (< 1000 utterances), all operations are interactive-speed.
