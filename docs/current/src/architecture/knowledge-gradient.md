# The Knowledge Gradient: Optimal Learning in Gaius

*A compute-centric architecture for sequential decision-making under uncertainty*

## 1. Introduction: From Sequential Decisions to Spatial Intelligence

### The Universal Resource Challenge

Every entity that engages in knowledge work faces the same fundamental constraint: finite cognitive and computational resources must be allocated across infinite possibilities. Whether you're operating an IoT sensor network, a personal workstation, an enterprise GPU cluster, an HPC center, or a nascent space-based data center, the question remains constant:

**What should I compute next?**

This is a sequential decision problem under uncertainty. Each observation updates our beliefs. Each computation consumes resources. The challenge is allocating those resources optimally across the exploration-exploitation frontier.

### The Knowledge Gradient Framework

Warren B. Powell's Knowledge Gradient (KG) for Optimal Learning (2010) provides a principled answer. The KG measures the expected value of information from taking an action—not just its immediate reward, but its contribution to improved future decisions.

Formally, for a belief state *S* and measurement decision *x*:

```
KG(x | S) = E[ max_x' μ^{n+1}(x') - max_x' μ^n(x') | S^n, x^n = x ]
```

Where:
- μ^n(x') is our current estimate of the value of alternative x'
- μ^{n+1}(x') is our updated estimate after observing the result of measuring x
- The difference captures how much the measurement improves our best option

The KG policy selects the measurement that maximizes this expected improvement. It naturally balances exploration (learning about uncertain alternatives) against exploitation (leveraging current knowledge).

### Gaius as KG Implementation

Gaius implements this framework spatially. The 19×19 grid represents a compressed belief state. Documents projected onto the grid are observations. Topological features (H0/H1/H2) reveal structure in the belief space. Curvature indicates where beliefs transition between regimes.

The human navigating the grid is implicitly solving a KG problem: "Which region should I investigate next to maximize my understanding of this domain?"

### Why Compute Costs Matter

In AI research and computational science, the connection between knowledge acquisition and resource expenditure is explicit:

- **CapEx**: GPU hardware, network infrastructure, storage systems
- **OpEx**: Electricity, cloud API calls, model hosting, inference tokens

A query to a local vLLM endpoint costs VRAM and power. A query to a cloud API costs dollars directly. The KG framework makes these costs explicit terms in the optimization:

```
KG_adjusted(x | S) = KG(x | S) - λ × cost(x)
```

Where λ trades off information value against resource consumption.

This framing applies universally:
- **IoT networks**: Edge inference constrained by battery and bandwidth
- **Personal workstations**: The Tinybox paradigm—6 GPUs, fixed electricity budget
- **Enterprise clusters**: Shared resources, contention, scheduling overhead
- **HPC centers**: Batch queues, allocation policies, utilization targets
- **Space-based systems**: Latency to ground, solar power cycles, thermal constraints

Every context requires balancing knowledge acquisition against resource consumption.

---

## 2. The 19×19 Grid as State Space

### UMAP Projection: Compressing Beliefs

The grid is not arbitrary. It results from UMAP projection of 768-dimensional document embeddings:

```python
# From src/gaius/core/projection.py:119-128
self._projector = UMAP(
    n_components=2,
    n_neighbors=15,
    min_dist=0.1,
    metric="cosine",
    random_state=42,
)
```

Key parameters:
- **n_neighbors=15**: Local neighborhood size for manifold approximation
- **min_dist=0.1**: Minimum distance between points in output (controls clumping)
- **metric="cosine"**: Semantic similarity measure appropriate for text embeddings

The projection compresses high-dimensional belief states into a 2D manifold that preserves local neighborhood structure. Points close in embedding space remain close on the grid.

### Grid Coordinates as Belief States

Each position (x, y) on the 19×19 grid represents a region in belief space. A document at position (10, 14) is semantically similar to other documents nearby.

The `GridData` structure captures this mapping (`src/gaius/core/projection.py:46-77`):

```python
@dataclass
class GridData:
    document_positions: set[tuple[int, int]]    # Occupied cells
    allocations: list[list[int]]                 # 19×19 density (0-100)
    raw_embeddings: np.ndarray | None           # 768-D preserved for TDA
    embedding_to_grid: dict[int, tuple[int, int]]  # Index → (x, y)
    grid_to_embedding: dict[tuple[int, int], int]  # (x, y) → index
```

The bidirectional mappings (`embedding_to_grid`, `grid_to_embedding`) enable navigation between the compressed 2D representation and the full high-dimensional space.

### Documents as Observations

Each document in the knowledge base is an observation that updates beliefs. When projected to the grid:

- **Clustered documents**: High confidence in that region of belief space
- **Sparse regions**: Uncertainty—either unexplored or genuinely empty
- **Uniform distribution**: Diverse domain with weak structure

The `GridPoint` structure tracks document identity (`src/gaius/core/projection.py:34-42`):

```python
@dataclass
class GridPoint:
    x: int                  # 0-18
    y: int                  # 0-18
    path: str               # KB document path
    title: str              # Document title
    embedding_id: str       # Chunk identifier
    cluster_id: int = -1    # TDA cluster assignment
```

### Coverage and Density as Uncertainty

Grid coverage quantifies belief completeness:

```python
# From src/gaius/core/projection.py:361-362
non_empty_cells = np.sum(density > 0)
grid_data.coverage = non_empty_cells / (19 * 19)
```

- **Low coverage (< 20%)**: Sparse beliefs; high uncertainty; exploration likely valuable
- **High coverage (> 60%)**: Dense beliefs; lower marginal value of additional observations
- **Uneven density**: Structure in beliefs; investigate boundaries between dense and sparse

---

## 3. Topological Data Analysis as Value Function Approximation

### Persistent Homology: Structural Invariants

TDA reveals topological features that persist across scales—the "shape" of the belief space that statistics alone cannot capture.

Gaius computes persistent homology using ripser (`src/gaius/core/tda.py:170-266`):

```python
# From src/gaius/core/tda.py:199-207
result = ripser.ripser(
    sampled_embeddings,
    maxdim=self.max_dimension,
    thresh=self.max_edge_length if self.max_edge_length != np.inf else 0,
    metric="cosine",
)
```

### Betti Numbers as Structural Indicators

The output quantifies topological structure:

- **H0 (components)**: Disconnected clusters in belief space
  - High H0 → fragmented understanding; integration may be valuable

- **H1 (cycles)**: Loops in the belief graph
  - Persistent H1 → circular reasoning, feedback structures, or coverage gaps
  - These are the "death loops" that indicate systemic patterns

- **H2 (voids)**: Cavities—regions surrounded by observations but empty within
  - H2 voids → missing connections; potentially high-value exploration targets

### Entropy as Uncertainty Quantification

Persistence entropy summarizes topological complexity (`src/gaius/core/tda.py:232-243`):

```python
persistences = np.array([i.persistence for i in intervals])
total_persistence = np.sum(persistences)
if total_persistence > 0:
    probs = persistences / total_persistence
    # Shannon entropy: -Σ p*log(p)
    features.entropy = float(-np.sum(probs * np.log(probs + 1e-10)))
```

Interpretation:
- **Low entropy**: Few dominant features; simple structure; beliefs are well-organized
- **High entropy**: Many features of similar persistence; complex or noisy structure

Entropy changes signal regime shifts. A sudden entropy spike may indicate:
- New domain area discovered
- Conflicting information introduced
- Model drift in embedding space

### Risk Scores as Information Value Proxies

Per-point risk scores estimate local topological instability (`src/gaius/core/tda.py:400-439`):

```python
# k-NN distance analysis
n_neighbors = min(10, n_points - 1)
nn = NearestNeighbors(n_neighbors=n_neighbors, metric="cosine")
nn.fit(embeddings)
distances, _ = nn.kneighbors(embeddings)

# Average distance to neighbors (skip self at index 0)
avg_distances = distances[:, 1:].mean(axis=1)

# Normalize to 0-1 range
risk = (avg_distances - min_d) / (max_d - min_d)
```

High risk scores indicate:
- Points distant from neighbors (potential outliers)
- Bridge points connecting disparate clusters
- Boundaries between semantic regions

These are precisely the points where the Knowledge Gradient is likely high—observations here would maximally update beliefs.

---

## 4. Mini-Grid Perspectives: Multi-View Observation

The 9×9 mini-grids provide orthographic views of the belief space around the cursor, enabling local inspection without losing global context.

### 4.1 Embed View: Local Similarity Structure

The Embed view shows cosine similarity in the original 768-dimensional space (`src/gaius/core/minigrids.py:40-117`):

```python
# Cosine similarity computation
dot = np.dot(cursor_embedding, embedding)
norm_cursor = np.linalg.norm(cursor_embedding)
norm_emb = np.linalg.norm(embedding)
similarity = dot / (norm_cursor * norm_emb)

# Map to mini-grid coordinates
embed_grid[my][mx] = (similarity + 1) / 2  # [-1,1] → [0,1]
```

**Interpretation**:
- **Bright center**: Cursor point has high self-similarity (always 1.0)
- **Bright neighbors**: Semantically similar documents cluster nearby
- **Scattered brightness**: Eclectic neighborhood; cursor is at a junction
- **Uniform dimness**: Isolated point; potential outlier or unexplored region

The Embed view reveals whether the UMAP 2D projection faithfully preserves high-dimensional relationships. If nearby grid points have low embedding similarity, the projection may be distorting local structure.

### 4.2 Iso View: Topological Elevation

The Iso view presents a 3D elevation map where height encodes topological features (`src/gaius/core/minigrids.py:120-256`). Four modes are available:

| Mode | Symbol | Source | Interpretation |
|------|--------|--------|----------------|
| Curvature | κ | Ricci curvature | Semantic boundaries vs interiors |
| Persistence | π | H0+H1+H2 sum | Topological complexity per document |
| Complexity | σ | Token variance | Semantic diversity within documents |
| Boundary | β | Cocycle contribution | Loop participation |

**Curvature Mode (κ)** is primary:

```python
# From src/gaius/core/minigrids.py:293-308
def _curvature_to_elevation(κ: float) -> float:
    if κ < -0.3:
        return 0.9  # High peaks (strong boundaries)
    elif κ < 0:
        return 0.5 + (-κ * 1.33)  # Linear map
    elif κ > 0.3:
        return 0.1  # Deep valleys (strong interiors)
    else:
        return 0.5 - (κ * 1.33)
```

Negative curvature (peaks) marks semantic boundaries—regions of high information value for exploration. Positive curvature (valleys) marks cluster interiors—regions where exploitation may be more valuable than exploration.

### 4.3 The Curvature Interpretation

Ricci curvature measures how geodesics (shortest paths) behave locally. The implementation uses Ollivier-Ricci curvature on the k-NN graph (`src/gaius/core/geometry.py:34-57`):

```
κ(x, y) = 1 - W(μₓ, μᵧ) / d(x, y)

where:
- W(μₓ, μᵧ) = Wasserstein-1 distance between neighborhood distributions
- μₓ = probability distribution on x's k-nearest neighbors
- d(x, y) = graph distance
```

**Geometric interpretation**:
- **κ > 0 (positive)**: Geodesics converge; cluster interior; homogeneous region
- **κ ≈ 0 (flat)**: Geodesics parallel; uniform structure
- **κ < 0 (negative)**: Geodesics diverge; boundary; heterogeneous transition zone

**Knowledge Gradient interpretation**:
- High |κ| regions are where beliefs transition between regimes
- Observations in high |κ| regions maximally discriminate between hypotheses
- The KG is typically highest at decision boundaries

---

## 5. Profile and Domain Semantics

### 5.1 Profile: Configuration Scope

A **profile** determines the configuration scope for a Gaius session:

- **KB root**: Which knowledge base to load
- **Agents**: Which swarm members are available
- **Inference settings**: Model selection, endpoints, technique chains
- **Theme**: Visual appearance

Profile selection happens at load time via `GAIUS_PROFILE` environment variable or `--profile` CLI flag.

When profile is `None`, the system uses `"default"`:

```python
# Profile loading (conceptual)
profile = os.environ.get("GAIUS_PROFILE") or cli_args.profile or "default"
```

Profiles enable different configurations for different contexts:
- **default**: General-purpose research
- **gpu-intensive**: High-compute workloads, reasoning models
- **inference-optimized**: Low-latency, fast models
- Custom profiles for specific projects or domains

### 5.2 Domain: Runtime Focus (or Absence Thereof)

A **domain** is an optional runtime constraint that filters and focuses analysis. Unlike profile (which is load-time configuration), domain can change mid-session.

When domain is `None` or `"open"`:
- **No KB filtering**: All documents are candidates
- **No agent specialization**: Swarm agents operate generically
- **Cross-domain reasoning**: Connections across topic areas are permitted

This represents the **absence of constraint**, not a special mode with specific behaviors.

The implementation defaults to an open domain (`src/gaius/core/state.py:153`):

```python
domain: str | None = None  # None = open domain (no constraint)
```

When domain is `None`, no domain filter is applied—all queries operate in "open domain" mode.

**Progressive refinement**: The system may suggest a domain based on query patterns:

1. User starts with no domain constraint
2. Queries cluster semantically (e.g., around inference, GPU allocation)
3. System suggests: "Your queries cluster around 'compute optimization'. Set this as domain?"
4. User accepts or declines

This preserves agency while providing structure when patterns emerge.

---

## 6. The Knowledge Gradient in Practice

### 6.1 Exploration: High-Curvature Navigation

The **tenuki** algorithm implements KG-guided exploration: jump to unexplored high-|κ| regions.

In Go, tenuki means "playing elsewhere"—abandoning a local situation to claim value in an uncontested area. In Gaius:

```
tenuki_score(x, y) = |κ(x, y)| × distance_factor × novelty_factor

where:
- |κ(x, y)|: Curvature magnitude (higher = more interesting boundary)
- distance_factor: Penalize positions too close to current focus
- novelty_factor: Bonus for unvisited regions
```

The tenuki command (`t` key) jumps the cursor to a high-score position, enabling rapid exploration of the belief space.

**H1 cycles as exploration targets**:
Death loops (H1 features) indicate persistent cycles in the belief graph. These represent:
- Feedback structures worth understanding
- Circular reasoning to validate or break
- Knowledge gaps where the loop fails to close

Investigating H1 cycles often yields high KG payoffs.

**H2 voids as structural absences**:
Voids surrounded by observations suggest missing connections. The observations around the void define what *should* connect; the void indicates it doesn't. High-value exploration fills these cavities.

### 6.2 Exploitation: Cluster Interior Deepening

Not all knowledge work is exploration. Within well-understood regions (low |κ|, high density):

- **Deepen existing understanding**: Read more documents in the cluster
- **Build on stable features**: High-persistence topological features indicate robust structure
- **Trust convergent agents**: When swarm positions cluster, consensus is forming

Exploitation is appropriate when:
- The current region directly serves the task at hand
- Exploration budget is exhausted
- Confidence in the region exceeds task requirements

### 6.3 The Balance: Value of Information

The Knowledge Gradient provides a principled answer to "explore or exploit?":

**Current implementation (theoretical lens)**:
- Visual cues (curvature, entropy, risk) guide human intuition
- Human makes exploration/exploitation decisions
- System provides information; human provides judgment

**Future implementation (algorithmic)**:

| Phase | Capability | Implementation |
|-------|------------|----------------|
| Near-term | Uncertainty quantification | Per-cell confidence intervals |
| Near-term | Automated tenuki | System suggests high-KG positions |
| Medium-term | Acquisition functions | Explicit KG computation over grid |
| Medium-term | Cost-aware routing | KG_adjusted with inference costs |
| Long-term | Autonomous policies | Full KG optimization loop |

The roadmap moves from human-guided to increasingly autonomous exploration while preserving human oversight for high-stakes decisions.

---

## 7. Compute Economics Across Scales

### 7.1 The Universal Compute Challenge

Gaius operates across diverse compute environments:

**IoT Networks**:
- Constraints: Battery, bandwidth, intermittent connectivity
- Strategy: Edge inference for latency-critical; cloud for complex analysis
- KG application: Prioritize observations that maximize information per joule

**Personal Workstations (Tinybox paradigm)**:
- Constraints: 6× RTX 4090 (144GB VRAM), residential power
- Strategy: Local inference for privacy and iteration speed; cloud for capability expansion
- KG application: Balance local model quality against electricity cost

**Enterprise Clusters**:
- Constraints: Shared resources, scheduling contention, utilization targets
- Strategy: Batch processing for throughput; interactive for latency
- KG application: Optimize job scheduling across priority queues

**HPC Centers**:
- Constraints: Allocation policies, queue wait times, job size limits
- Strategy: Coarse-grained parallelism; checkpoint/restart patterns
- KG application: Select compute allocation that maximizes research output per allocation-hour

**Space-Based Data Centers**:
- Constraints: Orbital mechanics (latency), solar power cycles, thermal management
- Strategy: Asynchronous processing; predictive caching; power-aware scheduling
- KG application: Compute during power-available windows; cache results for query periods

### 7.2 CapEx vs OpEx Tradeoffs

AI compute involves fundamental economic tradeoffs:

**Local Inference (High CapEx, Low Marginal Cost)**:
- Upfront: GPU hardware ($8K-$50K per card)
- Ongoing: Electricity (~$0.10-0.30 per kWh), cooling, maintenance
- Advantage: No per-token cost; privacy; low latency
- Disadvantage: Fixed capacity; depreciation; requires expertise

**Cloud API (Low CapEx, Variable OpEx)**:
- Upfront: None (pay-as-you-go)
- Ongoing: Per-token pricing ($0.01-$15 per 1M tokens depending on model)
- Advantage: Elastic capacity; latest models; no maintenance
- Disadvantage: Per-query cost; latency; vendor dependency

**Hybrid Strategies**:
The optimal strategy depends on workload characteristics:

| Workload Pattern | Recommended Approach |
|------------------|---------------------|
| High volume, predictable | Local inference |
| Bursty, variable | Cloud API |
| Latency-critical | Local inference |
| Capability-critical | Cloud (access frontier models) |
| Privacy-critical | Local inference |
| Cost-critical | Depends on volume crossover point |

### 7.3 The Lambda Labs / Cerebras Decision Framework

For models too large for local hardware, Gaius integrates cloud providers:

**Lambda Labs (GPU Rental)**:
- Pay by the hour for GPU instances
- Full control over deployment
- Cost-effective for sustained workloads
- Available via `/model add` for feasibility assessment

**Cerebras (Hosted Inference)**:
- Pay per token
- Ultra-fast inference (~2,000 tokens/sec)
- Cost-effective for bursty workloads
- Available via provider integration

The decision framework:

```
break_even_hours = hourly_rental_cost / (tokens_per_hour × token_price)

if expected_hours > break_even_hours:
    use GPU rental
else:
    use hosted inference
```

For example, if GPU rental costs $10/hour and you process 100K tokens/hour at $0.0001/token:
- API cost: 100K × $0.0001 = $0.01/hour
- Break-even: $10 / $0.01 = 1,000 hours

For sustained high-volume workloads, rental wins. For occasional bursts, API wins.

### 7.4 Optimal Agent Workflow Execution

The Knowledge Gradient applies to inference routing decisions:

**Multi-endpoint architecture** (`src/gaius/inference/client.py`):
- **Reasoning**: DeepSeek-R1 or Qwen-32B for complex analysis
- **Coding**: Specialized models for code generation
- **Fast**: Lightweight models for low-latency queries
- **Evaluation**: XAI Grok for outsider perspective

Each endpoint has different costs (latency, tokens, quality). The KG framework selects the endpoint that maximizes expected value:

```
KG_endpoint(q) = E[improvement | query q, endpoint e] - λ × cost(e)
```

**Agent evolution as compute investment**:
Background optimization cycles (`/evolve`) improve agent prompts over time. This is a long-term KG investment:
- Immediate cost: Compute for optimization
- Deferred benefit: Better agent performance on future queries

The evolution daemon runs during idle periods, maximizing resource utilization.

---

## 8. The /explain Command: Contextual Interpretation

The `/explain` command invokes local LLM interpretation of grid state (`src/gaius/core/minigrids.py:368-460`):

```python
prompt = f"""You are explaining a 19×19 grid visualization of a knowledge base to a user.

Context:
- Grid coverage: {grid_data.coverage:.1%}
- Total documents: {grid_data.n_documents}
- At cursor ({cursor_x}, {cursor_y}): {point.title}
- H0 (components): {tda_features.h0_count}
- H1 (loops): {tda_features.h1_count}
- H2 (voids): {tda_features.h2_count}
- Topological entropy: {tda_features.entropy:.3f}

Explain in 2-3 sentences:
1. What the Iso view reveals about the information domain structure
2. How the user should interpret high vs low elevation areas
3. What the relationship between grid position and semantic meaning implies
"""
```

The explanation combines:
- **TDA features**: Topological summary statistics
- **Spatial context**: Cursor position and local neighborhood
- **View state**: Current mode and overlay settings

This provides a natural language interpretation that bridges the gap between mathematical features and human understanding.

---

## 9. Implementation Details

### 9.1 Projection Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                    Knowledge Base (Markdown)                      │
└─────────────────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Vector Embeddings (768-D)                      │
│                    via Nomic / sentence-transformers              │
└─────────────────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Qdrant Storage                                 │
│                    (scroll retrieval with metadata)               │
└─────────────────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    UMAP Projection                                │
│                    n_neighbors=15, min_dist=0.1, metric=cosine    │
└─────────────────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Normalization to [0,18] × [0,18]               │
│                    Quantization to integer grid                   │
└─────────────────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GridData                                       │
│                    positions, allocations, bidirectional maps     │
│                    raw_embeddings preserved for TDA               │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 TDA Computation

```python
# From src/gaius/core/tda.py
# 1. Subsample if necessary (ripser is O(n³) worst case)
if n_points > max_points:  # default 500
    indices = np.random.choice(n_points, max_points, replace=False)
    sampled_embeddings = embeddings[indices]

# 2. Compute persistent homology
result = ripser.ripser(sampled_embeddings, maxdim=2, metric="cosine")
diagrams = result['dgms']  # [H0_diagram, H1_diagram, H2_diagram]

# 3. Extract features
for dim, diagram in enumerate(diagrams):
    for birth, death in diagram:
        if np.isfinite(death):
            intervals.append(PersistenceInterval(birth, death, dim))

# 4. Generate bounding boxes for visualization
h1_cycles = compute_bounding_boxes(intervals, grid_coords, dimension=1)
h2_voids = compute_bounding_boxes(intervals, grid_coords, dimension=2)
```

### 9.3 Geometry Pipeline

```python
# From src/gaius/core/geometry.py
# 1. Build k-NN graph
knn_graph, distances = self._build_knn_graph(embeddings)

# 2. Compute Ollivier-Ricci curvature
if GraphRicciCurvature available:
    orc = OllivierRicci(graph, alpha=0.5, method="OTD")
    orc.compute_ricci_curvature()
    # Extract per-node curvatures from edge curvatures
else:
    # Fallback: variance-based approximation
    curvatures = self._compute_curvature_fallback(graph, embeddings)

# 3. Compute gradient field (direction of semantic change)
gradients = self._compute_gradients_2d(positions, curvatures, knn_graph)

# 4. Compute divergence (sources and sinks)
divergence = self._compute_divergence(gradients, knn_graph)
```

### 9.4 State Persistence

Grid state persists to PostgreSQL for history tracking and multi-instance sharing:

```sql
-- From src/gaius/storage/grid_state.py

grid_snapshots:
  id, created_at, kb_root, embedding_model, projection_method
  n_documents, coverage, h0_count, h1_count, h2_count, entropy
  is_current, metadata

grid_points:
  snapshot_id, x, y, doc_path, doc_title, embedding_id, cluster_id

grid_embeddings:
  snapshot_id, embedding_index, vector, grid_x, grid_y

grid_tda_features:
  snapshot_id, h1_cycles, h2_voids, components, risk_scores, intervals
```

This enables:
- Historical comparison of belief states
- Recovery after session interruption
- Multi-instance coordination

---

## 10. Roadmap: From Theory to Algorithm

### 10.1 Current State

The Knowledge Gradient is currently an **interpretive framework**:

- Visual cues (curvature, entropy, risk) guide human intuition
- Manual exploration via keyboard navigation and tenuki
- Human-in-the-loop decision making for all consequential actions
- Compute costs implicit (human awareness of model selection)

### 10.2 Near-Term (Q1 2025)

| Feature | Description |
|---------|-------------|
| **Uncertainty quantification** | Per-cell confidence intervals displayed on grid |
| **Automated tenuki** | System suggests high-KG positions; human confirms |
| **Compute cost tracking** | Status bar shows inference cost per session |
| **Profile/domain refactoring** | None semantics implemented as specified |

### 10.3 Medium-Term (2025)

| Feature | Description |
|---------|-------------|
| **Acquisition functions** | Explicit KG computation over grid positions |
| **Expected improvement** | Quantified value of information per query |
| **Compute-aware routing** | KG_adjusted with explicit cost terms |
| **Multi-fidelity inference** | Adaptive model selection based on query value |

### 10.4 Long-Term

| Feature | Description |
|---------|-------------|
| **Full KG optimization loop** | Autonomous exploration with human oversight |
| **Exploration policies** | Learned policies for different domain types |
| **Portfolio optimization** | Balance across multiple research threads |
| **Cross-instance coordination** | Distributed exploration across Gaius instances |

---

## References

- Powell, W. B. (2010). "The Knowledge Gradient for Optimal Learning." In *Wiley Encyclopedia of Operations Research and Management Science*.
- Carlsson, G. (2009). "Topology and Data." *Bulletin of the American Mathematical Society*.
- McInnes, L., Healy, J., & Melville, J. (2018). "UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction."
- Ollivier, Y. (2009). "Ricci curvature of Markov chains on metric spaces." *Journal of Functional Analysis*.

---

*This document establishes the compute-centric foundation for Gaius architecture. It serves as the shared understanding for ongoing development and the basis for the technical refactoring from domain-specific exemplars to domain-agnostic infrastructure.*
