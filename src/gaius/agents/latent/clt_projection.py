"""CLT-to-ColNomic projection bridge for unified agent/document grid space.

Maps CLT sparse features to ColNomic embedding space, enabling:
1. Agent positions derived from thought content (not random placement)
2. Agents and KB documents cohabiting the same projected grid
3. Exploration beyond KB bounds (agents can occupy novel positions)
4. Time-delay embedding of traces for expanded representational capacity

Architecture:
    CLT Sparse Features (20,480-dim)
            ↓ learned projection / dimensionality reduction
    Bridge Embedding (128-dim compatible with ColNomic)
            ↓ shared UMAP projector (fitted on KB documents)
    Grid Coordinates (19×19)

The projection layer is learned via contrastive alignment:
- When we have both CLT features AND ColNomic embeddings for the same text,
  we minimize the distance between their projected representations.
- This grounds agent "thoughts" in the same semantic space as documents.

Time-Delay Embedding (NVAR/NG-RC style):
    For a sequence of agent thoughts T_1, T_2, ..., T_n with delays τ:
    Trace state = concat([T_t, T_{t-τ}, T_{t-2τ}, ...])

    This expands the effective dimensionality of the representable manifold,
    allowing trace dynamics (exploration patterns) to be visualized.

References:
- NVAR (Nonlinear Vector AutoRegression): arXiv:2012.14572
- NG-RC (Next-Generation Reservoir Computing): arXiv:2108.10784
- Cross-Layer Transcoders: arXiv:2406.11944
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .clt_memory import CLTLatentThought, SparseFeatureSet

logger = logging.getLogger(__name__)

# Architecture constants
CLT_FEATURE_DIM = 20_480  # CLT sparse feature space
COLNOMIC_DIM = 128        # ColNomic aggregated embedding dimension
BRIDGE_HIDDEN_DIM = 512   # Intermediate projection dimension


@dataclass
class TraceState:
    """Time-delay embedded trace state for an agent.

    Captures not just current thought but recent history, enabling
    visualization of exploration dynamics on the grid.

    Following NVAR/NG-RC, we concatenate delayed observations:
        state = [T_t, T_{t-τ}, T_{t-2τ}, ..., T_{t-kτ}]

    This embeds the trajectory in a higher-dimensional space where
    attractor dynamics become visible (e.g., oscillations, convergence).
    """
    agent_role: str
    current_embedding: np.ndarray  # (COLNOMIC_DIM,) - current position
    delayed_embeddings: list[np.ndarray] = field(default_factory=list)  # History
    delay_steps: int = 3  # Number of τ delays

    @property
    def full_state(self) -> np.ndarray:
        """Get full time-delay embedded state.

        Returns:
            (COLNOMIC_DIM * (1 + delay_steps),) - expanded state vector
        """
        components = [self.current_embedding]
        for emb in self.delayed_embeddings[:self.delay_steps]:
            components.append(emb)
        # Pad with zeros if history is shorter than delay_steps
        while len(components) < 1 + self.delay_steps:
            components.append(np.zeros(COLNOMIC_DIM))
        return np.concatenate(components)

    @property
    def effective_dimension(self) -> int:
        """Effective dimension of time-delay embedded space."""
        return COLNOMIC_DIM * (1 + self.delay_steps)

    def push(self, new_embedding: np.ndarray) -> None:
        """Push new embedding, shifting history.

        Args:
            new_embedding: New (COLNOMIC_DIM,) embedding to add
        """
        self.delayed_embeddings.insert(0, self.current_embedding.copy())
        if len(self.delayed_embeddings) > self.delay_steps:
            self.delayed_embeddings = self.delayed_embeddings[:self.delay_steps]
        self.current_embedding = new_embedding


class CLTProjectionBridge:
    """Projects CLT sparse features into ColNomic embedding space.

    Enables agents to be positioned in the same grid space as KB documents.

    Projection Methods:
    1. Hash Projection (default): Deterministic hash-based dimensionality reduction
       - Fast, no training required
       - Less accurate but immediately usable

    2. Learned Projection (future): Neural network trained via contrastive loss
       - Requires paired (CLT features, ColNomic embedding) data
       - More accurate semantic alignment

    3. PCA/SVD Projection: Fitted on corpus of CLT feature vectors
       - Captures principal variations in feature space
       - Good for visualization without ColNomic pairing
    """

    def __init__(
        self,
        method: str = "hash",
        projection_matrix: np.ndarray | None = None,
    ):
        """Initialize projection bridge.

        Args:
            method: Projection method ("hash", "pca", "learned")
            projection_matrix: Pre-computed projection matrix for PCA/learned
        """
        self.method = method
        self._projection_matrix = projection_matrix

        # For hash projection: random projection matrix (fixed seed for reproducibility)
        if method == "hash":
            rng = np.random.RandomState(42)
            # Sparse random projection following Johnson-Lindenstrauss
            # Each output dim gets ~sqrt(input_dim) non-zero entries
            self._hash_matrix = self._create_sparse_random_projection(
                CLT_FEATURE_DIM, COLNOMIC_DIM, rng
            )

    def _create_sparse_random_projection(
        self,
        input_dim: int,
        output_dim: int,
        rng: np.random.RandomState,
        density: float = 0.01,  # ~1% non-zero for large sparse inputs
    ) -> np.ndarray:
        """Create sparse random projection matrix.

        Uses sparse random projections for efficiency with high-dim sparse inputs.
        """
        # Number of non-zeros per row
        nnz_per_row = max(1, int(input_dim * density))

        matrix = np.zeros((output_dim, input_dim))

        for i in range(output_dim):
            indices = rng.choice(input_dim, nnz_per_row, replace=False)
            values = rng.choice([-1, 1], nnz_per_row) / np.sqrt(nnz_per_row)
            matrix[i, indices] = values

        return matrix

    def project_sparse_features(
        self,
        sparse_features: dict[int, float],
    ) -> np.ndarray:
        """Project CLT sparse features to ColNomic-compatible embedding.

        Args:
            sparse_features: Dict mapping feature_idx -> activation

        Returns:
            (COLNOMIC_DIM,) embedding compatible with ColNomic space
        """
        if self.method == "hash":
            return self._hash_project(sparse_features)
        elif self.method == "pca" and self._projection_matrix is not None:
            return self._matrix_project(sparse_features)
        elif self.method == "learned" and self._projection_matrix is not None:
            return self._matrix_project(sparse_features)
        else:
            # Fallback to hash
            return self._hash_project(sparse_features)

    def _hash_project(self, sparse_features: dict[int, float]) -> np.ndarray:
        """Hash-based sparse projection.

        For a sparse input x with non-zeros at indices I:
            output[j] = sum_{i in I} hash_matrix[j, i] * x[i]

        This is efficient because we only iterate over non-zero features.
        """
        output = np.zeros(COLNOMIC_DIM)

        for feature_idx, activation in sparse_features.items():
            if 0 <= feature_idx < CLT_FEATURE_DIM:
                # Add contribution to all output dimensions
                output += self._hash_matrix[:, feature_idx] * activation

        # L2 normalize to match ColNomic embedding convention
        norm = np.linalg.norm(output)
        if norm > 0:
            output = output / norm

        return output

    def _matrix_project(self, sparse_features: dict[int, float]) -> np.ndarray:
        """Matrix-based projection (PCA or learned).

        Uses pre-computed projection matrix.
        """
        # Convert sparse to dense (only at non-zero indices)
        dense = np.zeros(CLT_FEATURE_DIM)
        for idx, val in sparse_features.items():
            if 0 <= idx < CLT_FEATURE_DIM:
                dense[idx] = val

        # Project
        output = self._projection_matrix @ dense

        # L2 normalize
        norm = np.linalg.norm(output)
        if norm > 0:
            output = output / norm

        return output

    def project_thought(
        self,
        thought: "CLTLatentThought",
    ) -> np.ndarray:
        """Project a CLTLatentThought to ColNomic-compatible embedding.

        Args:
            thought: CLTLatentThought with aggregated_features

        Returns:
            (COLNOMIC_DIM,) embedding
        """
        return self.project_sparse_features(thought.aggregated_features)

    def project_to_grid(
        self,
        sparse_features: dict[int, float],
        projector,  # GridProjector with fitted UMAP
    ) -> tuple[int, int]:
        """Project CLT features directly to grid coordinates.

        Uses the same UMAP/PCA projector fitted on KB documents,
        ensuring agents occupy the same semantic space.

        Args:
            sparse_features: CLT sparse features
            projector: GridProjector instance (must be fitted)

        Returns:
            (x, y) grid coordinates in [0, 18] range
        """
        # First project to ColNomic space
        embedding = self.project_sparse_features(sparse_features)

        # Then use GridProjector's UMAP
        if projector._fitted and projector._projector is not None:
            coords_2d = projector._projector.transform([embedding])
            grid_coords = projector._normalize_to_grid(coords_2d)
            return (int(grid_coords[0, 0]), int(grid_coords[0, 1]))
        else:
            # Projector not fitted - return center
            logger.warning("GridProjector not fitted, defaulting to center")
            return (9, 9)


class TraceEmbedder:
    """Time-delay embedder for agent exploration traces.

    Implements NVAR-style delay embedding to capture trajectory dynamics.
    This expands the representational aperture beyond static positions.

    Example:
        If agent visits positions [A, B, C, D] over 4 steps with τ=1:
        - Step 1: state = [A, 0, 0]           (no history)
        - Step 2: state = [B, A, 0]           (1 step history)
        - Step 3: state = [C, B, A]           (full history)
        - Step 4: state = [D, C, B]           (sliding window)

    The full_state captures not WHERE the agent is, but its TRAJECTORY.
    """

    def __init__(
        self,
        delay_steps: int = 3,
        delay_tau: int = 1,  # Steps between delays (can subsample for longer memory)
    ):
        """Initialize trace embedder.

        Args:
            delay_steps: Number of delayed copies to include
            delay_tau: Sampling interval between delays
        """
        self.delay_steps = delay_steps
        self.delay_tau = delay_tau
        self._traces: dict[str, TraceState] = {}  # agent_role -> trace

    def get_trace(self, agent_role: str) -> TraceState:
        """Get or create trace state for an agent."""
        if agent_role not in self._traces:
            self._traces[agent_role] = TraceState(
                agent_role=agent_role,
                current_embedding=np.zeros(COLNOMIC_DIM),
                delay_steps=self.delay_steps,
            )
        return self._traces[agent_role]

    def update(
        self,
        agent_role: str,
        embedding: np.ndarray,
    ) -> TraceState:
        """Update agent trace with new embedding.

        Args:
            agent_role: Agent identifier
            embedding: New (COLNOMIC_DIM,) embedding

        Returns:
            Updated TraceState
        """
        trace = self.get_trace(agent_role)
        trace.push(embedding)
        return trace

    def get_all_traces(self) -> dict[str, TraceState]:
        """Get all agent traces."""
        return self._traces.copy()

    def project_traces_to_grid(
        self,
        projector,  # GridProjector with fitted UMAP
    ) -> dict[str, tuple[int, int]]:
        """Project all trace current positions to grid.

        Returns:
            Dict of agent_role -> (x, y) grid coordinates
        """
        positions = {}

        for role, trace in self._traces.items():
            if np.any(trace.current_embedding != 0):
                # Use UMAP to project
                if projector._fitted and projector._projector is not None:
                    coords_2d = projector._projector.transform([trace.current_embedding])
                    grid_coords = projector._normalize_to_grid(coords_2d)
                    positions[role] = (int(grid_coords[0, 0]), int(grid_coords[0, 1]))
                else:
                    positions[role] = (9, 9)

        return positions

    def clear(self, agent_role: str | None = None) -> None:
        """Clear trace history.

        Args:
            agent_role: If provided, clear only that agent. Otherwise clear all.
        """
        if agent_role:
            if agent_role in self._traces:
                del self._traces[agent_role]
        else:
            self._traces.clear()


class AgentStateDecoder:
    """Decodes agent states (CLT features) back to text.

    This completes the bidirectional latent channel:
    - Encode: text → CLT sparse features (via CLTModel.extract_features)
    - Decode: CLT sparse features → text (via CLTModel.decode_features_to_text)

    Agents can "think" in feature space and produce text output only when needed,
    with the decoded text naturally flowing through the embedding pipeline.

    The decoding process:
    1. Given aggregated sparse features from agent state
    2. Optionally provide context (e.g., query, previous outputs)
    3. Decode to text via CLT decoder + LLM generation
    4. The text can then be embedded via ColNomic for grid positioning

    This enables exploration visualization where:
    - Agent position on grid reflects conceptual territory
    - Agent "speech bubbles" show decoded thoughts when hovered
    - Trace history shows evolution of thought patterns
    """

    def __init__(self, clt_model: str = "qwen3-1.7b"):
        """Initialize agent state decoder.

        Args:
            clt_model: CLT model name for decoding
        """
        self.clt_model = clt_model
        self._client = None

    async def _get_client(self):
        """Get or create Engine client."""
        if self._client is None:
            from ...client import get_client
            self._client = await get_client()
        return self._client

    async def decode_state(
        self,
        sparse_features: dict[int, float],
        context: str = "",
        max_tokens: int = 50,
    ) -> dict:
        """Decode agent state to text via Engine.

        Args:
            sparse_features: Aggregated CLT sparse features
            context: Optional context for generation
            max_tokens: Maximum tokens to generate

        Returns:
            Dict with generated_text, feature_summary, top_features
        """
        client = await self._get_client()

        # Convert feature dict to serializable format
        features_list = [
            {"feature_idx": idx, "activation": val}
            for idx, val in sorted(
                sparse_features.items(),
                key=lambda x: abs(x[1]),
                reverse=True
            )[:50]  # Top 50 features
        ]

        result = await client.call(
            "CLT", "decode",
            {
                "features": features_list,
                "context": context,
                "max_tokens": max_tokens,
                "model_name": self.clt_model,
            }
        )

        return result

    async def decode_trace(
        self,
        trace: "TraceState",
        context: str = "",
    ) -> list[dict]:
        """Decode a full trace history to text.

        Produces text for current position and historical positions,
        enabling visualization of thought evolution.

        Args:
            trace: TraceState with current and delayed embeddings
            context: Optional context for generation

        Returns:
            List of decoded states (most recent first)
        """
        # This would require inverse projection from ColNomic back to CLT features
        # For now, we store features separately in the trace
        # This is a placeholder for the full implementation

        logger.warning(
            "decode_trace requires stored CLT features per trace step. "
            "Currently only current state can be decoded directly."
        )
        return []

    def summarize_features(self, sparse_features: dict[int, float]) -> str:
        """Create a local text summary of features.

        This is a lightweight summary without LLM generation,
        useful for quick visualization labels.

        Args:
            sparse_features: Feature dict

        Returns:
            Brief text summary
        """
        if not sparse_features:
            return "neutral"

        sorted_feats = sorted(
            sparse_features.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )[:5]

        # Simple pattern description
        total_activation = sum(abs(v) for v in sparse_features.values())
        density = len(sparse_features)

        if density > 100:
            pattern = "complex"
        elif density > 50:
            pattern = "moderate"
        else:
            pattern = "focused"

        if total_activation > 10:
            intensity = "high"
        elif total_activation > 3:
            intensity = "medium"
        else:
            intensity = "low"

        return f"{pattern}/{intensity} ({density} features)"


# Module-level singletons
_bridge: CLTProjectionBridge | None = None
_trace_embedder: TraceEmbedder | None = None
_decoder: AgentStateDecoder | None = None


def get_clt_projection_bridge() -> CLTProjectionBridge:
    """Get or create CLT projection bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = CLTProjectionBridge(method="hash")
    return _bridge


def get_trace_embedder() -> TraceEmbedder:
    """Get or create trace embedder singleton."""
    global _trace_embedder
    if _trace_embedder is None:
        _trace_embedder = TraceEmbedder(delay_steps=3)
    return _trace_embedder


def get_agent_state_decoder() -> AgentStateDecoder:
    """Get or create agent state decoder singleton."""
    global _decoder
    if _decoder is None:
        _decoder = AgentStateDecoder()
    return _decoder
