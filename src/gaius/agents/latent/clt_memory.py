"""CLT-enhanced latent working memory for interpretable agent collaboration.

Extends the standard latent memory with Cross-Layer Transcoder (CLT) features,
enabling interpretable sparse feature storage and retrieval.

Instead of dense 768-dim Nomic vectors, agents communicate via:
- Sparse features (~115 active per layer from 20,480 feature space)
- Interpretable feature indices that can be traced to semantic concepts
- Cross-layer attribution graphs for understanding influence paths

This implements LatentMAS with CLT for interpretable multi-agent collaboration.

References:
- BluelightAI Qwen3 CLT: https://bluelightai.com/blog/qwen3-explorer
- Cross-Layer Transcoders: arXiv:2406.11944
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .memory import LatentWorkingMemory, LatentThought, EMBEDDING_DIM

logger = logging.getLogger(__name__)

# CLT feature configuration
CLT_FEATURES_PER_LAYER = 20_480
CLT_L0_SPARSITY = 115  # Expected active features per position
CLT_NUM_LAYERS = 28  # Qwen3-1.7B


@dataclass
class SparseFeatureSet:
    """A sparse set of CLT features for a single position.

    Attributes:
        layer_idx: Transformer layer index
        position: Token position in sequence
        active_features: Dict mapping feature_idx -> activation magnitude
        top_k: Number of features stored
    """
    layer_idx: int
    position: int
    active_features: dict[int, float] = field(default_factory=dict)

    @property
    def top_k(self) -> int:
        return len(self.active_features)

    def to_dense(self) -> np.ndarray:
        """Convert to dense vector (for Qdrant storage)."""
        dense = np.zeros(CLT_FEATURES_PER_LAYER)
        for idx, val in self.active_features.items():
            if 0 <= idx < CLT_FEATURES_PER_LAYER:
                dense[idx] = val
        return dense

    @classmethod
    def from_dense(cls, layer_idx: int, position: int, dense: np.ndarray, threshold: float = 0.0) -> "SparseFeatureSet":
        """Create from dense vector."""
        active = {i: float(v) for i, v in enumerate(dense) if v > threshold}
        return cls(layer_idx=layer_idx, position=position, active_features=active)

    def jaccard_similarity(self, other: "SparseFeatureSet") -> float:
        """Compute Jaccard similarity based on active feature overlap."""
        self_features = set(self.active_features.keys())
        other_features = set(other.active_features.keys())

        intersection = len(self_features & other_features)
        union = len(self_features | other_features)

        if union == 0:
            return 0.0
        return intersection / union

    def weighted_similarity(self, other: "SparseFeatureSet") -> float:
        """Compute weighted similarity using activation magnitudes."""
        common_features = set(self.active_features.keys()) & set(other.active_features.keys())

        if not common_features:
            return 0.0

        # Weighted overlap: sum of min activations for shared features
        weighted_overlap = sum(
            min(self.active_features[f], other.active_features[f])
            for f in common_features
        )

        # Normalize by total activation mass
        total_self = sum(self.active_features.values())
        total_other = sum(other.active_features.values())

        if total_self + total_other == 0:
            return 0.0

        return 2 * weighted_overlap / (total_self + total_other)


@dataclass
class CLTLatentThought(LatentThought):
    """A thought stored with CLT sparse features for interpretable collaboration.

    Extends LatentThought with:
    - Aggregated sparse features across all positions
    - Layer-wise feature breakdowns
    - Attribution graph edges (optional)

    The sparse features enable:
    - Interpretable similarity (which features are shared)
    - Feature-based consensus (average active features across agents)
    - Circuit tracing (how features influence outputs)
    """

    # Aggregated sparse features (summed across positions)
    aggregated_features: dict[int, float] = field(default_factory=dict)

    # Per-layer feature sets (for detailed analysis)
    layer_features: list[SparseFeatureSet] = field(default_factory=list)

    # Total active features count
    total_active: int = 0

    # CLT model used
    clt_model: str = "qwen3-1.7b"

    @classmethod
    def from_clt_result(
        cls,
        agent_role: str,
        content: str,
        features: list[dict],  # From CLTExtractResponse
        domain: str = "",
        temporal_slice: str = "",
        metadata: dict | None = None,
        clt_model: str = "qwen3-1.7b",
    ) -> "CLTLatentThought":
        """Create from CLT extraction result.

        Args:
            agent_role: Role of generating agent
            content: Original text content
            features: List of sparse features from CLT extraction
            domain: Domain context
            temporal_slice: Time period identifier
            metadata: Optional metadata
            clt_model: CLT model used
        """
        # Aggregate features across positions
        aggregated: dict[int, float] = {}
        layer_sets: dict[tuple[int, int], dict[int, float]] = {}

        for f in features:
            layer_idx = f.get("layer_idx", 0)
            position = f.get("position", 0)
            feature_idx = f.get("feature_idx", 0)
            activation = f.get("activation", 0.0)

            # Aggregate by feature index
            aggregated[feature_idx] = aggregated.get(feature_idx, 0.0) + activation

            # Track per layer-position
            key = (layer_idx, position)
            if key not in layer_sets:
                layer_sets[key] = {}
            layer_sets[key][feature_idx] = activation

        # Convert to SparseFeatureSets
        layer_feature_list = [
            SparseFeatureSet(
                layer_idx=layer_idx,
                position=position,
                active_features=feats,
            )
            for (layer_idx, position), feats in sorted(layer_sets.items())
        ]

        # Create embedding from top aggregated features (for Qdrant compatibility)
        # Project sparse features to 768-dim for backward compatibility
        embedding = cls._sparse_to_embedding(aggregated)

        return cls(
            id=str(uuid.uuid4()),
            agent_role=agent_role,
            content_summary=content[:200] + ("..." if len(content) > 200 else ""),
            embedding=embedding,
            domain=domain,
            temporal_slice=temporal_slice,
            metadata=metadata or {},
            aggregated_features=aggregated,
            layer_features=layer_feature_list,
            total_active=len(aggregated),
            clt_model=clt_model,
        )

    @staticmethod
    def _sparse_to_embedding(aggregated: dict[int, float]) -> np.ndarray:
        """Project sparse features to 768-dim embedding.

        Uses a simple hash-based projection for Qdrant compatibility.
        The real similarity computation uses feature overlap, not this.
        """
        embedding = np.zeros(EMBEDDING_DIM)

        for feature_idx, activation in aggregated.items():
            # Hash feature index to embedding dimension
            target_dim = feature_idx % EMBEDDING_DIM
            embedding[target_dim] += activation

        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

    def feature_similarity(self, other: "CLTLatentThought") -> float:
        """Compute similarity based on shared sparse features.

        More interpretable than dense embedding similarity.
        """
        self_features = set(self.aggregated_features.keys())
        other_features = set(other.aggregated_features.keys())

        intersection = self_features & other_features
        union = self_features | other_features

        if not union:
            return 0.0

        # Jaccard with activation weighting
        intersection_weight = sum(
            min(self.aggregated_features[f], other.aggregated_features[f])
            for f in intersection
        )

        union_weight = sum(
            max(self.aggregated_features.get(f, 0), other.aggregated_features.get(f, 0))
            for f in union
        )

        if union_weight == 0:
            return 0.0

        return intersection_weight / union_weight

    def get_top_features(self, k: int = 20) -> list[tuple[int, float]]:
        """Get top-k most activated features."""
        sorted_features = sorted(
            self.aggregated_features.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_features[:k]

    def shared_features(self, other: "CLTLatentThought") -> list[tuple[int, float, float]]:
        """Get features shared with another thought.

        Returns:
            List of (feature_idx, self_activation, other_activation)
        """
        shared = set(self.aggregated_features.keys()) & set(other.aggregated_features.keys())
        return [
            (f, self.aggregated_features[f], other.aggregated_features[f])
            for f in sorted(shared, key=lambda x: self.aggregated_features[x], reverse=True)
        ]


class CLTLatentMemory(LatentWorkingMemory):
    """CLT-enhanced working memory with interpretable sparse features.

    Extends LatentWorkingMemory to use CLT sparse features instead of
    (or in addition to) dense Nomic embeddings.

    Key capabilities:
    - Store agent outputs as sparse feature sets
    - Retrieve similar contexts via feature overlap
    - Compute interpretable consensus (shared features)
    - Enable circuit-level debugging of agent collaboration
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6339,
        collection_name: str = "gaius_clt_latent_thoughts",
        clt_model: str = "qwen3-1.7b",
    ):
        """Initialize CLT-enhanced memory.

        Args:
            host: Qdrant server host
            port: Qdrant server port
            collection_name: Qdrant collection name
            clt_model: CLT model name for feature extraction
        """
        super().__init__(host=host, port=port, collection_name=collection_name)
        self.clt_model = clt_model
        self._clt_client = None

    async def _get_clt_client(self):
        """Get or create CLT gRPC client."""
        if self._clt_client is None:
            from ...client import get_client
            self._clt_client = await get_client()
        return self._clt_client

    async def extract_features(self, text: str) -> list[dict]:
        """Extract CLT sparse features from text.

        Routes through Engine for model access.

        Args:
            text: Input text

        Returns:
            List of sparse feature dicts
        """
        client = await self._get_clt_client()

        result = await client.call(
            "CLT", "extract",
            {
                "text": text,
                "model_name": self.clt_model,
                "top_k": CLT_L0_SPARSITY,
            }
        )

        if not result.get("success", False):
            error = result.get("error", "Unknown error")
            raise RuntimeError(f"CLT extraction failed: {error}")

        return result.get("features", [])

    async def store_clt(self, thought: CLTLatentThought) -> str:
        """Store a CLT thought in working memory.

        Stores both the dense embedding (for Qdrant search) and
        sparse features (in payload for interpretability).

        Args:
            thought: CLTLatentThought to store

        Returns:
            ID of stored thought
        """
        await self._ensure_collection()

        from qdrant_client import models

        client = self._get_client()

        # Build payload with sparse features
        payload = {
            "agent_role": thought.agent_role,
            "content_summary": thought.content_summary,
            "domain": thought.domain,
            "temporal_slice": thought.temporal_slice,
            "created_at": thought.created_at.isoformat(),
            # CLT-specific fields
            "clt_model": thought.clt_model,
            "total_active": thought.total_active,
            # Store aggregated features as JSON (Qdrant handles dicts)
            "aggregated_features": {
                str(k): v for k, v in thought.aggregated_features.items()
            },
            **thought.metadata,
        }

        # Upsert point
        client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=thought.id,
                    vector=thought.embedding.tolist(),
                    payload=payload,
                )
            ],
        )

        logger.debug(f"Stored CLT thought {thought.id} from {thought.agent_role} ({thought.total_active} features)")
        return thought.id

    async def store_from_content(
        self,
        agent_role: str,
        content: str,
        domain: str = "",
        metadata: dict | None = None,
    ) -> CLTLatentThought:
        """Extract features and store thought in one operation.

        Args:
            agent_role: Role of generating agent
            content: Text content to process
            domain: Domain context
            metadata: Optional metadata

        Returns:
            Stored CLTLatentThought
        """
        # Extract features
        features = await self.extract_features(content)

        # Create thought
        thought = CLTLatentThought.from_clt_result(
            agent_role=agent_role,
            content=content,
            features=features,
            domain=domain,
            metadata=metadata,
            clt_model=self.clt_model,
        )

        # Store
        await self.store_clt(thought)

        return thought

    async def retrieve_similar_clt(
        self,
        query_features: dict[int, float],
        limit: int = 5,
        threshold: float = 0.1,
        exclude_agent: str | None = None,
        domain: str | None = None,
    ) -> list[CLTLatentThought]:
        """Retrieve thoughts with similar CLT features.

        Uses Qdrant for initial retrieval, then reranks by feature overlap.

        Args:
            query_features: Aggregated feature dict
            limit: Maximum results
            threshold: Minimum similarity threshold
            exclude_agent: Agent to exclude
            domain: Domain filter

        Returns:
            List of similar CLTLatentThoughts, ranked by feature overlap
        """
        await self._ensure_collection()

        # Create query embedding from features
        query_embedding = CLTLatentThought._sparse_to_embedding(query_features)

        # Use parent's retrieve_similar for initial candidates
        candidates = await self.retrieve_similar(
            query_embedding=query_embedding,
            limit=limit * 3,  # Over-retrieve for reranking
            threshold=0.0,  # Rerank by features
            exclude_agent=exclude_agent,
            domain=domain,
        )

        # Reconstruct as CLTLatentThoughts and rerank by feature similarity
        clt_thoughts = []
        for thought in candidates:
            # Reconstruct aggregated features from payload
            aggregated = {}
            if hasattr(thought, "metadata") and "aggregated_features" in thought.metadata:
                agg = thought.metadata["aggregated_features"]
                aggregated = {int(k): v for k, v in agg.items()}

            clt_thought = CLTLatentThought(
                id=thought.id,
                agent_role=thought.agent_role,
                content_summary=thought.content_summary,
                embedding=thought.embedding,
                domain=thought.domain,
                temporal_slice=thought.temporal_slice,
                created_at=thought.created_at,
                metadata=thought.metadata,
                aggregated_features=aggregated,
                total_active=len(aggregated),
            )

            # Compute feature similarity
            query_thought = CLTLatentThought(
                id="query",
                agent_role="query",
                content_summary="",
                embedding=query_embedding,
                domain="",
                aggregated_features=query_features,
            )

            sim = clt_thought.feature_similarity(query_thought)
            if sim >= threshold:
                clt_thoughts.append((clt_thought, sim))

        # Sort by feature similarity and return top-k
        clt_thoughts.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in clt_thoughts[:limit]]

    async def compute_feature_consensus(
        self,
        domain: str,
        limit: int = 10,
        min_agents: int = 2,
    ) -> dict[int, float]:
        """Compute consensus features across agents.

        Features that appear in multiple agents' outputs with high
        activation are considered "consensus" features.

        Args:
            domain: Domain to compute consensus for
            limit: Max thoughts to include
            min_agents: Minimum agents sharing a feature for consensus

        Returns:
            Dict of feature_idx -> consensus activation score
        """
        await self._ensure_collection()

        from qdrant_client import models

        client = self._get_client()

        # Get recent thoughts for domain
        results = client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="domain",
                        match=models.MatchValue(value=domain),
                    )
                ]
            ),
            limit=limit,
            with_vectors=False,
            with_payload=True,
        )

        points = results[0]

        if len(points) < min_agents:
            return {}

        # Aggregate features across agents
        feature_counts: dict[int, int] = {}  # feature -> num agents
        feature_activations: dict[int, list[float]] = {}  # feature -> activations

        for p in points:
            payload = p.payload or {}
            agg = payload.get("aggregated_features", {})

            for feat_str, activation in agg.items():
                feat = int(feat_str)
                feature_counts[feat] = feature_counts.get(feat, 0) + 1
                if feat not in feature_activations:
                    feature_activations[feat] = []
                feature_activations[feat].append(activation)

        # Compute consensus: features appearing in >= min_agents
        consensus = {}
        for feat, count in feature_counts.items():
            if count >= min_agents:
                # Consensus score = mean activation * agent coverage
                mean_activation = np.mean(feature_activations[feat])
                coverage = count / len(points)
                consensus[feat] = mean_activation * coverage

        return consensus

    async def get_clt_stats(self) -> dict:
        """Get CLT-specific memory statistics."""
        base_stats = await self.get_stats()

        return {
            **base_stats,
            "clt_model": self.clt_model,
            "features_per_layer": CLT_FEATURES_PER_LAYER,
            "expected_sparsity": CLT_L0_SPARSITY,
        }


# Module-level singleton
_clt_memory: CLTLatentMemory | None = None


def get_clt_memory() -> CLTLatentMemory:
    """Get or create CLT latent memory singleton."""
    global _clt_memory
    if _clt_memory is None:
        _clt_memory = CLTLatentMemory()
    return _clt_memory
