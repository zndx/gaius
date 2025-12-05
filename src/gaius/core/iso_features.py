"""Iso view features computed from TDA on multi-vector embeddings.

Computes four feature arrays for the toggleable Iso mini-grid visualization:
- Curvature (κ): Ollivier-Ricci on k-NN graph (semantic boundaries)
- Persistence (π): Total persistence from per-doc H0+H1+H2
- Complexity (σ): Variance of token embeddings (semantic diversity)
- Boundary (β): Cocycle contribution to neighborhood H1 (loop participation)

These features are computed at index time and cached for smooth UI navigation.
The Iso view becomes the centerpiece interface for exploring the high-dimensional
topology of the knowledge space.
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

# Import IsoMode from state to avoid duplication
from .state import IsoMode

if TYPE_CHECKING:
    from .projection import GridData


# Symbols for each mode (Greek letters)
ISO_MODE_SYMBOLS = {
    IsoMode.CURVATURE: "κ",
    IsoMode.PERSISTENCE: "π",
    IsoMode.COMPLEXITY: "σ",
    IsoMode.BOUNDARY: "β",
}


@dataclass
class DocumentTopology:
    """Per-document TDA results from persistent homology on token embeddings.

    Computed by running ripser on the multi-vector embeddings (n_tokens × 128)
    of each document. Captures the intrinsic topological structure of the
    semantic space within each document.
    """
    b0: int                     # Betti-0: Connected components
    b1: int                     # Betti-1: 1-cycles (loops)
    b2: int                     # Betti-2: 2-cycles (voids)
    total_persistence: float    # Sum of all (death - birth) for finite features
    persistence_entropy: float  # Shannon entropy of lifetimes (complexity measure)
    diagram: dict               # Raw persistence diagrams: {h0: [(b,d)...], h1: [...], h2: [...]}


@dataclass
class IsoFeatures:
    """Pre-computed features for all four Iso view modes.

    Arrays are indexed by document position in the grid projection.
    All values are normalized to [0, 1] range for consistent visualization.
    """
    curvatures: np.ndarray      # (n,) Ricci κ values, normalized
    persistence: np.ndarray     # (n,) Total persistence per doc, normalized
    complexity: np.ndarray      # (n,) Multi-vector variance, normalized
    boundary: np.ndarray        # (n,) H1 boundary scores, normalized

    # Per-document persistence diagrams (for detailed analysis)
    diagrams: list[dict] = field(default_factory=list)

    # Metadata
    computation_time: float = 0.0
    embedding_type: str = "single"  # "single" or "multi"
    n_documents: int = 0


class IsoFeatureComputer:
    """Computes IsoFeatures from grid data and multi-vector embeddings.

    Designed for pre-computation at index time. The computation pipeline:
    1. For each document, run ripser on its token embeddings (H0+H1+H2)
    2. Aggregate per-document topology into persistence and complexity arrays
    3. Compute Ricci curvature on the document-level k-NN graph
    4. Compute boundary scores via cocycle attribution on neighborhood topology

    All computations use cosine distance and subsample large point clouds
    for performance (ripser scales ~O(n^3)).
    """

    # Performance tuning
    MAX_TOKENS_PER_DOC = 150    # Subsample if more tokens
    MAX_NEIGHBORHOOD_TOKENS = 500  # For boundary computation

    def __init__(self, use_cocycles: bool = True):
        """Initialize the feature computer.

        Args:
            use_cocycles: Whether to compute cocycles for boundary attribution.
                         Slightly slower but enables precise loop membership.
        """
        self.use_cocycles = use_cocycles
        self._ripser_available = None

    @property
    def ripser_available(self) -> bool:
        """Check if ripser is available for TDA computation."""
        if self._ripser_available is None:
            try:
                import ripser
                self._ripser_available = True
            except ImportError:
                self._ripser_available = False
        return self._ripser_available

    def compute_all(
        self,
        grid_data: "GridData",
        multi_vectors: list[np.ndarray] | None = None,
        existing_curvatures: np.ndarray | None = None,
    ) -> IsoFeatures:
        """Compute all four feature arrays.

        Args:
            grid_data: Grid projection with document positions
            multi_vectors: Per-document multi-vector embeddings [(n_tokens, dim), ...]
                          If None, complexity and persistence use fallbacks
            existing_curvatures: Pre-computed Ricci curvatures (from GeometryComputer)

        Returns:
            IsoFeatures with all four arrays populated
        """
        start_time = time.time()
        n = grid_data.n_documents

        # Initialize arrays
        curvatures = np.zeros(n)
        persistence = np.zeros(n)
        complexity = np.zeros(n)
        boundary = np.zeros(n)
        diagrams = []

        # Use existing curvatures if provided
        if existing_curvatures is not None and len(existing_curvatures) == n:
            curvatures = self._normalize(existing_curvatures)
        else:
            # Compute curvatures from grid structure
            curvatures = self._compute_curvatures_from_grid(grid_data)

        # Compute per-document features
        if multi_vectors is not None and len(multi_vectors) == n:
            for i, mv in enumerate(multi_vectors):
                if mv is not None and len(mv) > 0:
                    topo = self._compute_document_topology(mv)
                    persistence[i] = topo.total_persistence
                    complexity[i] = self._compute_token_variance(mv)
                    diagrams.append(topo.diagram)
                else:
                    diagrams.append({'h0': [], 'h1': [], 'h2': []})

            # Normalize after all documents processed
            persistence = self._normalize(persistence)
            complexity = self._normalize(complexity)

            # Compute boundary scores using cocycles
            if self.ripser_available and self.use_cocycles:
                boundary = self._compute_boundary_scores(grid_data, multi_vectors)
        else:
            # Fallback: use distance-based complexity
            if grid_data.raw_embeddings is not None:
                complexity = self._compute_distance_complexity(grid_data)
            # Leave persistence and boundary as zeros (will use density fallback)

        computation_time = time.time() - start_time

        return IsoFeatures(
            curvatures=curvatures,
            persistence=persistence,
            complexity=complexity,
            boundary=boundary,
            diagrams=diagrams,
            computation_time=computation_time,
            embedding_type="multi" if multi_vectors else "single",
            n_documents=n,
        )

    def _compute_document_topology(self, token_embeddings: np.ndarray) -> DocumentTopology:
        """Compute H0+H1+H2 persistent homology on document's token cloud.

        Args:
            token_embeddings: (n_tokens, dim) array of token embeddings

        Returns:
            DocumentTopology with Betti numbers, persistence, and diagrams
        """
        if not self.ripser_available:
            return DocumentTopology(
                b0=1, b1=0, b2=0,
                total_persistence=0.0,
                persistence_entropy=0.0,
                diagram={'h0': [], 'h1': [], 'h2': []},
            )

        import ripser

        # Subsample if too many tokens (ripser performance)
        embeddings = token_embeddings
        if len(embeddings) > self.MAX_TOKENS_PER_DOC:
            indices = self._farthest_point_sampling(embeddings, self.MAX_TOKENS_PER_DOC)
            embeddings = embeddings[indices]

        # Need at least 4 points for meaningful H2
        maxdim = 2 if len(embeddings) >= 4 else 1

        try:
            # Run ripser with cocycles for H2
            # Use cosine distance converted from embeddings
            # ripser expects a distance matrix or point cloud
            # For cosine, we compute distances manually
            distances = self._cosine_distance_matrix(embeddings)

            result = ripser.ripser(
                distances,
                maxdim=maxdim,
                distance_matrix=True,
                do_cocycles=self.use_cocycles,
            )

            diagrams = result['dgms']

            # Count finite features (exclude infinite persistence at birth)
            b0 = len([p for p in diagrams[0] if np.isfinite(p[1])])
            b1 = len([p for p in diagrams[1] if np.isfinite(p[1])]) if len(diagrams) > 1 else 0
            b2 = len([p for p in diagrams[2] if np.isfinite(p[1])]) if len(diagrams) > 2 else 0

            # Total persistence (sum of lifetimes for finite features)
            total_persistence = 0.0
            for dim_dgm in diagrams:
                for birth, death in dim_dgm:
                    if np.isfinite(death):
                        total_persistence += (death - birth)

            # Persistence entropy (Shannon entropy of normalized lifetimes)
            entropy = self._compute_persistence_entropy(diagrams)

            return DocumentTopology(
                b0=b0,
                b1=b1,
                b2=b2,
                total_persistence=total_persistence,
                persistence_entropy=entropy,
                diagram={
                    'h0': diagrams[0].tolist() if len(diagrams) > 0 else [],
                    'h1': diagrams[1].tolist() if len(diagrams) > 1 else [],
                    'h2': diagrams[2].tolist() if len(diagrams) > 2 else [],
                },
            )

        except Exception:
            # Fallback on ripser error
            return DocumentTopology(
                b0=1, b1=0, b2=0,
                total_persistence=0.0,
                persistence_entropy=0.0,
                diagram={'h0': [], 'h1': [], 'h2': []},
            )

    def _compute_boundary_scores(
        self,
        grid_data: "GridData",
        multi_vectors: list[np.ndarray],
    ) -> np.ndarray:
        """Compute boundary contribution using cocycle representatives.

        Documents that participate in H1 cycles (semantic loops) get higher
        boundary scores. This reveals bridge documents connecting different
        semantic regions.

        Args:
            grid_data: Grid with document positions
            multi_vectors: Per-document token embeddings

        Returns:
            Normalized boundary scores array
        """
        if not self.ripser_available:
            return np.zeros(len(multi_vectors))

        import ripser

        n = len(multi_vectors)
        boundary_scores = np.zeros(n)

        # Pool representative tokens from each document
        # Use mean + extreme tokens to capture diversity
        pooled_tokens = []
        doc_indices = []  # Which document each pooled token belongs to

        for doc_idx, mv in enumerate(multi_vectors):
            if mv is None or len(mv) == 0:
                continue

            # Take mean + 2 most distant tokens per document
            mean_token = mv.mean(axis=0)
            pooled_tokens.append(mean_token)
            doc_indices.append(doc_idx)

            if len(mv) >= 3:
                # Find tokens most distant from mean
                distances = np.linalg.norm(mv - mean_token, axis=1)
                extreme_indices = np.argsort(distances)[-2:]
                for idx in extreme_indices:
                    pooled_tokens.append(mv[idx])
                    doc_indices.append(doc_idx)

        if len(pooled_tokens) < 4:
            return boundary_scores

        pooled_array = np.array(pooled_tokens)
        doc_indices = np.array(doc_indices)

        # Subsample if needed
        if len(pooled_array) > self.MAX_NEIGHBORHOOD_TOKENS:
            indices = self._farthest_point_sampling(pooled_array, self.MAX_NEIGHBORHOOD_TOKENS)
            pooled_array = pooled_array[indices]
            doc_indices = doc_indices[indices]

        try:
            # Compute distances and run ripser with cocycles
            distances = self._cosine_distance_matrix(pooled_array)

            result = ripser.ripser(
                distances,
                maxdim=1,  # Only need H1 for boundary detection
                distance_matrix=True,
                do_cocycles=True,
            )

            # Attribute H1 features to documents via cocycles
            cocycles = result.get('cocycles', [[], []])
            h1_dgm = result['dgms'][1] if len(result['dgms']) > 1 else []

            if len(cocycles) > 1 and len(h1_dgm) > 0:
                for cycle_idx, cocycle in enumerate(cocycles[1]):
                    if cycle_idx >= len(h1_dgm):
                        break

                    birth, death = h1_dgm[cycle_idx]
                    if not np.isfinite(death):
                        continue

                    persistence = death - birth

                    # Cocycle contains simplices (edges) forming the loop
                    # Each edge is an index pair into the point cloud
                    participating_docs = set()
                    for simplex in cocycle:
                        # simplex might be (vertex_idx, coeff) or similar structure
                        if hasattr(simplex, '__len__') and len(simplex) >= 1:
                            vertex_idx = int(simplex[0]) if hasattr(simplex, '__getitem__') else int(simplex)
                            if vertex_idx < len(doc_indices):
                                participating_docs.add(doc_indices[vertex_idx])

                    # Weight by persistence and distribute among participating docs
                    if participating_docs:
                        weight = persistence / len(participating_docs)
                        for doc_idx in participating_docs:
                            boundary_scores[doc_idx] += weight

        except Exception:
            pass  # Leave as zeros on error

        return self._normalize(boundary_scores)

    def _compute_curvatures_from_grid(self, grid_data: "GridData") -> np.ndarray:
        """Compute curvatures from grid structure when not pre-provided.

        Uses a simplified discrete curvature based on local density variation.
        Not as accurate as full Ollivier-Ricci but fast to compute.
        """
        # Use raw_embeddings length as n if n_documents not set
        if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) > 0:
            n = len(grid_data.raw_embeddings)
        else:
            n = grid_data.n_documents

        curvatures = np.zeros(n)

        if n == 0 or grid_data.raw_embeddings is None or len(grid_data.raw_embeddings) == 0:
            return curvatures

        # Build position-to-index mapping
        pos_to_idx = {}
        for (x, y), idx in grid_data.grid_to_embedding.items():
            pos_to_idx[(x, y)] = idx

        # For each point, estimate curvature from neighborhood density
        for (x, y), idx in grid_data.grid_to_embedding.items():
            # Count neighbors at distance 1 and 2
            n1 = 0  # Direct neighbors
            n2 = 0  # Distance-2 neighbors

            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue
                    dist = abs(dx) + abs(dy)  # Manhattan distance
                    if (x + dx, y + dy) in pos_to_idx:
                        if dist <= 1:
                            n1 += 1
                        elif dist <= 2:
                            n2 += 1

            # Curvature estimate: negative when surrounded (interior),
            # positive when sparse (boundary)
            # This is inverse of typical Ricci convention, so we negate
            expected_n1 = 4  # Max direct neighbors
            expected_n2 = 8  # Max distance-2 neighbors

            density = (n1 / expected_n1 + n2 / expected_n2) / 2
            curvatures[idx] = density - 0.5  # Center around 0

        return self._normalize(curvatures)

    def _compute_token_variance(self, token_embeddings: np.ndarray) -> float:
        """Compute variance of token embeddings (semantic diversity)."""
        if len(token_embeddings) < 2:
            return 0.0

        # Use trace of covariance matrix as scalar variance measure
        centered = token_embeddings - token_embeddings.mean(axis=0)
        variance = np.sum(centered ** 2) / len(token_embeddings)
        return variance

    def _compute_distance_complexity(self, grid_data: "GridData") -> np.ndarray:
        """Fallback complexity using aggregated embedding distances."""
        n = grid_data.n_documents
        complexity = np.zeros(n)

        if grid_data.raw_embeddings is None:
            return complexity

        embeddings = grid_data.raw_embeddings

        # For each point, compute mean distance to k nearest neighbors
        k = min(5, n - 1)
        if k < 1:
            return complexity

        for i in range(n):
            distances = np.linalg.norm(embeddings - embeddings[i], axis=1)
            distances[i] = np.inf  # Exclude self
            knn_distances = np.partition(distances, k)[:k]
            complexity[i] = np.mean(knn_distances)

        return self._normalize(complexity)

    def _compute_persistence_entropy(self, diagrams: list) -> float:
        """Compute Shannon entropy of normalized persistence lifetimes."""
        lifetimes = []
        for dim_dgm in diagrams:
            for birth, death in dim_dgm:
                if np.isfinite(death) and death > birth:
                    lifetimes.append(death - birth)

        if not lifetimes:
            return 0.0

        # Normalize to probabilities
        total = sum(lifetimes)
        if total == 0:
            return 0.0

        probs = [lt / total for lt in lifetimes]

        # Shannon entropy
        entropy = -sum(p * np.log(p + 1e-10) for p in probs)
        return entropy

    def _cosine_distance_matrix(self, embeddings: np.ndarray) -> np.ndarray:
        """Compute pairwise cosine distance matrix."""
        # Normalize rows
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normalized = embeddings / norms

        # Cosine similarity matrix
        similarity = np.dot(normalized, normalized.T)

        # Convert to distance (1 - similarity), clipped to [0, 2]
        distance = np.clip(1 - similarity, 0, 2)

        # Ensure diagonal is exactly zero
        np.fill_diagonal(distance, 0)

        return distance

    def _farthest_point_sampling(self, points: np.ndarray, n_samples: int) -> np.ndarray:
        """Topology-preserving subsampling via farthest point sampling.

        Greedily selects points that are maximally distant from already-selected
        points. This preserves the overall shape better than random sampling.
        """
        n = len(points)
        if n_samples >= n:
            return np.arange(n)

        # Start with first point (or random)
        selected = [0]
        min_distances = np.full(n, np.inf)

        for _ in range(n_samples - 1):
            # Update min distances to selected set
            last_selected = selected[-1]
            distances = np.linalg.norm(points - points[last_selected], axis=1)
            min_distances = np.minimum(min_distances, distances)

            # Select farthest point
            min_distances[selected] = -np.inf  # Exclude already selected
            next_idx = np.argmax(min_distances)
            selected.append(next_idx)

        return np.array(selected)

    def _normalize(self, values: np.ndarray) -> np.ndarray:
        """Normalize array to [0, 1] range."""
        if len(values) == 0:
            return values

        min_val = np.min(values)
        max_val = np.max(values)

        if max_val - min_val < 1e-10:
            return np.zeros_like(values)

        return (values - min_val) / (max_val - min_val)
