# Origins: Pliny, the Go Board, and the Swarm

This page keeps the founding framing of Gaius. It is history and design intent, not the current architecture; for what runs today start at the [Introduction](../introduction.md). Where a capability below is still live, the page that owns it is linked; where it is retired, it says so.

Gaius was named after Gaius Plinius Secundus (Pliny the Elder), whose *Naturalis Historia* catalogued the natural world across 37 books. The first product was a terminal interface for navigating high-dimensional embedding spaces: it computed persistent homology and Ollivier–Ricci curvature on the original embeddings, projected the results onto a discrete 19×19 lattice via UMAP, and rendered topological and geometric features as interactive overlays.

## The founding capabilities

1. **Lattice projection** — UMAP (cosine metric, k=15 neighbours, min_dist=0.1) maps embedding vectors to continuous 2D coordinates, quantised to a 19×19 integer lattice by rounding and clipping to [0, 18]. Two 9×9 orthographic mini-grids follow the cursor: an **Embed** view of the local cosine-similarity neighbourhood and an **Iso** view rendering scalar fields (curvature, total persistence, complexity) as elevation maps via inverse-distance-weighted interpolation (power=2). *Live in the TUI* ([The Grid Metaphor](./grid.md), [Embeddings](./embeddings.md)); the vectors are ColBERT-Zero `agg` vectors, 128-d.

2. **Persistent homology (H₀–H₂)** — Ripser computes a Vietoris–Rips filtration over the cosine distance matrix of the original embeddings, producing barcodes for dimensions 0 through 2; intervals with persistence > 0.1 are marked significant (a heuristic threshold, no stability analysis). *Live* ([Persistent Homology](./homology.md)).

3. **Ollivier–Ricci curvature** — discrete Ricci curvature on a k-nearest-neighbour graph (k=15, cosine) with the OTD method, α=0.5; per-node curvature is the mean of incident edge curvatures; curvature, gradient and divergence fields project to the Iso mini-grid. *Live* ([Grammar Engine](../architecture/grammar.md)).

4. **Multi-agent exploration** — seven agents (Leader, Risk, Optimizer, Planner, Critic, Executor, Adversary) navigated the lattice with role-specific positioning: Leader sought cluster centroids, Risk sat at semantic boundaries, Adversary sampled uniformly. Training used the RASE framework, where constraints compose declaratively (AllOf/AnyOf/Not) and a ground-truth oracle produces verifiable rewards. *RASE is live* ([RASE Metamodel](../architecture/rase.md)); *the swarm and its 768-d latent working memory are on the retirement list* — they predate ColBERT-Zero and the cognition cycle.

5. **Modal interface** — vim-style navigation (`hjkl`, slash commands, overlay toggles) over the lattice and the gRPC service graph. *Live* ([The TUI](../guide/tui.md)).

## The founding pipeline

Embed → Project → Filtration → Curvature → Exploration → Rendering. Embed, Project, Filtration, Curvature and Rendering (LuxCore) are current; Exploration by the swarm is not. The lattice was conceived as both a visualisation surface and a discrete approximation of the data manifold, and that reading still holds for the TUI.

## What changed

The peer described in the Introduction grew around this core: a thinking lane and a cognition cycle instead of a swarm; ColBERT-Zero instead of the 2025 single-vector embedders; the Signals lattice (Airflow clock, YuniKorn admission, Metaflow flows, the shared warehouse) instead of an in-engine scheduler running everything in one process. "37 services in one daemon" was the 2025 shape; today the engine coordinates and yields execution.
