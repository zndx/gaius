"""
Differential geometry computations for knowledge manifolds.

Provides Ollivier-Ricci curvature, gradient fields, and divergence
analysis on embedding spaces for biomorphic visualization.

Inspired by "Environmental randomness underlies morphological complexity
of colonial diatoms" - curvature reveals semantic "turbulence".
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree
from sklearn.metrics import pairwise_distances

logger = logging.getLogger(__name__)


@dataclass
class GeometricFeatures:
    """Geometric analysis results for embedding manifold."""

    curvatures: np.ndarray  # (n,) Ricci curvature per point
    gradients: np.ndarray  # (n, 2) Semantic gradient vectors (2D projected)
    divergence: np.ndarray  # (n,) Divergence at each point
    knn_graph: nx.Graph  # k-NN graph structure
    computation_time: float = 0.0  # Seconds


class GeometryComputer:
    """
    Compute differential geometry features on discrete embedding manifolds.

    Uses Ollivier-Ricci curvature to measure semantic boundary strength
    and gradient fields to show direction of semantic change.

    Mathematical Background:
    ------------------------
    Ollivier-Ricci curvature: κ(x, y) = 1 - W(μₓ, μᵧ) / d(x, y)
    where W is Wasserstein distance and μₓ is neighborhood distribution.

    Interpretation:
    - κ > 0: Positive curvature (cluster interior)
    - κ < 0: Negative curvature (semantic boundary)
    - κ ≈ 0: Flat geometry (uniform region)

    Biomorphic Analogy:
    -------------------
    Negative curvature (boundaries) ~ turbulent stream flow
      → complex colonial diatom structures
    Positive curvature (interiors) ~ calm water
      → simple single-cell diatoms
    """

    def __init__(
        self,
        k_neighbors: int = 15,
        metric: str = "cosine",
        use_ricci_library: bool = True,
    ):
        """
        Initialize geometry computer.

        Args:
            k_neighbors: Number of nearest neighbors for graph construction
            metric: Distance metric ('cosine', 'euclidean', 'manhattan')
            use_ricci_library: Try GraphRicciCurvature if available
        """
        self.k = k_neighbors
        self.metric = metric
        self.use_ricci_library = use_ricci_library

    async def compute_features(
        self,
        embeddings: np.ndarray,
        grid_positions: Optional[np.ndarray] = None,
    ) -> GeometricFeatures:
        """
        Compute all geometric features for embeddings.

        Args:
            embeddings: (n, d) array of high-dimensional embeddings
            grid_positions: (n, 2) optional 2D grid coordinates for gradients

        Returns:
            GeometricFeatures with curvatures, gradients, divergence, graph
        """
        import time

        start_time = time.time()

        n_points = len(embeddings)
        logger.info(f"Computing geometry for {n_points} points with k={self.k}")

        # 1. Build k-NN graph
        knn_graph, distances = self._build_knn_graph(embeddings)
        logger.debug(f"Built k-NN graph: {knn_graph.number_of_nodes()} nodes, "
                     f"{knn_graph.number_of_edges()} edges")

        # 2. Compute Ricci curvature
        curvatures = self._compute_ricci_curvature(knn_graph, embeddings)
        logger.debug(f"Curvature range: [{curvatures.min():.3f}, {curvatures.max():.3f}]")

        # 3. Compute gradient field (in 2D grid space if provided)
        if grid_positions is not None:
            gradients = self._compute_gradients_2d(
                grid_positions, curvatures, knn_graph
            )
        else:
            # Gradient in embedding space (first 2 dims for visualization)
            gradients = self._compute_gradients_embedding(embeddings, knn_graph)

        # 4. Compute divergence
        divergence = self._compute_divergence(gradients, knn_graph)

        computation_time = time.time() - start_time
        logger.info(f"Geometry computation complete in {computation_time:.2f}s")

        return GeometricFeatures(
            curvatures=curvatures,
            gradients=gradients,
            divergence=divergence,
            knn_graph=knn_graph,
            computation_time=computation_time,
        )

    def _build_knn_graph(
        self, embeddings: np.ndarray
    ) -> tuple[nx.Graph, np.ndarray]:
        """
        Build k-NN graph from embeddings using fast spatial indexing.

        Args:
            embeddings: (n, d) array

        Returns:
            (graph, distances) where graph is networkx.Graph and
            distances is (n, k) array of neighbor distances
        """
        n_points = len(embeddings)

        # Compute pairwise distances
        if self.metric == "cosine":
            # Cosine distance = 1 - cosine_similarity
            # Normalize first for numerical stability
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1  # Avoid division by zero
            normalized = embeddings / norms
            distances_matrix = pairwise_distances(
                normalized, metric="cosine", n_jobs=-1
            )
        else:
            distances_matrix = pairwise_distances(
                embeddings, metric=self.metric, n_jobs=-1
            )

        # Build graph
        G = nx.Graph()
        G.add_nodes_from(range(n_points))

        # For each point, connect to k nearest neighbors
        distances_out = np.zeros((n_points, self.k))

        for i in range(n_points):
            # Get k+1 nearest (including self), then exclude self
            # Clamp kth to valid range (must be < n_points for argpartition)
            dists = distances_matrix[i]
            kth = min(self.k + 1, n_points - 1)
            nearest_indices = np.argpartition(dists, kth)[: kth + 1]
            nearest_indices = nearest_indices[nearest_indices != i][: self.k]

            for j, neighbor_idx in enumerate(nearest_indices):
                dist = dists[neighbor_idx]
                G.add_edge(i, neighbor_idx, weight=dist)
                if j < self.k:
                    distances_out[i, j] = dist

        return G, distances_out

    def _compute_ricci_curvature(
        self, graph: nx.Graph, embeddings: np.ndarray
    ) -> np.ndarray:
        """
        Compute Ollivier-Ricci curvature using GraphRicciCurvature library
        or fallback to variance-based approximation.

        Args:
            graph: k-NN graph
            embeddings: (n, d) original embeddings

        Returns:
            (n,) array of per-node curvatures
        """
        n_points = graph.number_of_nodes()
        node_curvatures = np.zeros(n_points)

        if self.use_ricci_library:
            try:
                from GraphRicciCurvature.OllivierRicci import OllivierRicci

                logger.debug("Using GraphRicciCurvature library for Ricci curvature")

                # Compute Ollivier-Ricci curvature on graph
                # alpha=0.5 is standard, method="OTD" is fastest
                orc = OllivierRicci(graph, alpha=0.5, method="OTD", verbose="ERROR")
                orc.compute_ricci_curvature()

                # Extract node curvatures (average of incident edges)
                for node in graph.nodes():
                    edge_curvatures = [
                        orc.G[node][neighbor].get("ricciCurvature", 0.0)
                        for neighbor in graph.neighbors(node)
                    ]
                    if edge_curvatures:
                        node_curvatures[node] = np.mean(edge_curvatures)

                return node_curvatures

            except ImportError:
                logger.warning("GraphRicciCurvature not available, using fallback")
            except Exception as e:
                logger.warning(f"GraphRicciCurvature failed: {e}, using fallback")

        # Fallback: variance-based approximation
        logger.debug("Using variance-based curvature approximation")
        return self._compute_curvature_fallback(graph, embeddings)

    def _compute_curvature_fallback(
        self, graph: nx.Graph, embeddings: np.ndarray
    ) -> np.ndarray:
        """
        Fallback curvature using local variance.

        High variance in neighborhood distances → negative curvature (boundary)
        Low variance → positive curvature (interior)

        Args:
            graph: k-NN graph
            embeddings: (n, d) embeddings

        Returns:
            (n,) curvature approximation
        """
        n_points = len(embeddings)
        curvatures = np.zeros(n_points)

        for node in range(n_points):
            neighbors = list(graph.neighbors(node))
            if len(neighbors) < 2:
                continue

            # Get distances from node to all neighbors
            neighbor_dists = [
                graph[node][neighbor]["weight"] for neighbor in neighbors
            ]

            # Compute variance (normalize by mean to make scale-invariant)
            mean_dist = np.mean(neighbor_dists)
            if mean_dist > 0:
                variance = np.var(neighbor_dists)
                # Map variance to curvature: low var → positive, high var → negative
                # Empirical scaling: variance/mean² in [0, 1] maps to κ in [-1, 1]
                normalized_var = variance / (mean_dist**2)
                curvatures[node] = 1.0 - 2.0 * np.clip(normalized_var, 0, 1)

        return curvatures

    def _compute_gradients_2d(
        self,
        positions: np.ndarray,
        scalar_field: np.ndarray,
        graph: nx.Graph,
    ) -> np.ndarray:
        """
        Compute gradient field in 2D grid space.

        Args:
            positions: (n, 2) grid coordinates
            scalar_field: (n,) values (e.g., curvature, distance)
            graph: k-NN graph for neighbors

        Returns:
            (n, 2) gradient vectors
        """
        n_points = len(positions)
        gradients = np.zeros((n_points, 2))

        for node in range(n_points):
            neighbors = list(graph.neighbors(node))
            if not neighbors:
                continue

            # Finite difference: grad ≈ Σ (f(neighbor) - f(node)) * (pos_neighbor - pos_node) / dist²
            grad_x, grad_y = 0.0, 0.0
            weight_sum = 0.0

            for neighbor in neighbors:
                delta_f = scalar_field[neighbor] - scalar_field[node]
                delta_pos = positions[neighbor] - positions[node]
                dist_sq = np.dot(delta_pos, delta_pos)

                if dist_sq > 0:
                    weight = 1.0 / dist_sq
                    grad_x += weight * delta_f * delta_pos[0]
                    grad_y += weight * delta_f * delta_pos[1]
                    weight_sum += weight

            if weight_sum > 0:
                gradients[node] = [grad_x / weight_sum, grad_y / weight_sum]

        return gradients

    def _compute_gradients_embedding(
        self, embeddings: np.ndarray, graph: nx.Graph
    ) -> np.ndarray:
        """
        Compute gradient in high-dim embedding space, project to 2D.

        Args:
            embeddings: (n, d) embeddings
            graph: k-NN graph

        Returns:
            (n, 2) gradient vectors (first 2 principal components)
        """
        n_points = len(embeddings)
        dim = embeddings.shape[1]

        # Compute gradients in embedding space
        gradients_full = np.zeros((n_points, dim))

        for node in range(n_points):
            neighbors = list(graph.neighbors(node))
            if not neighbors:
                continue

            # Average direction to neighbors (simple gradient approximation)
            neighbor_vecs = embeddings[neighbors] - embeddings[node]
            gradients_full[node] = np.mean(neighbor_vecs, axis=0)

        # Project to 2D using first 2 PCA components
        from sklearn.decomposition import PCA

        pca = PCA(n_components=2)
        gradients_2d = pca.fit_transform(gradients_full)

        return gradients_2d

    def _compute_divergence(
        self, gradients: np.ndarray, graph: nx.Graph
    ) -> np.ndarray:
        """
        Compute divergence of gradient field.

        Div(F) = ∂Fx/∂x + ∂Fy/∂y (in 2D)

        Positive divergence → source (emanating paths)
        Negative divergence → sink (converging paths)

        Args:
            gradients: (n, 2) gradient vectors
            graph: k-NN graph

        Returns:
            (n,) divergence at each point
        """
        n_points = len(gradients)
        divergence = np.zeros(n_points)

        for node in range(n_points):
            neighbors = list(graph.neighbors(node))
            if len(neighbors) < 2:
                continue

            # Finite difference for divergence
            div_sum = 0.0
            count = 0

            for neighbor in neighbors:
                # Gradient difference
                delta_grad = gradients[neighbor] - gradients[node]

                # Direction from node to neighbor (normalized)
                # Divergence contribution: dot product of gradient change with direction
                # This is a discrete approximation of ∇·F

                div_sum += np.sum(delta_grad)  # Simple sum of gradient changes
                count += 1

            if count > 0:
                divergence[node] = div_sum / count

        return divergence
