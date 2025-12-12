"""ColBERT multi-vector embedder using fastembed.

Uses fastembed's LateInteractionTextEmbedding for ColBERT-style embeddings:
- Multi-vector per document (one 128-dim vector per token)
- Late interaction for high-quality retrieval
- CPU-based ONNX runtime (no GPU conflicts)

Models:
- colbert-ir/colbertv2.0: 128-dim, 0.44 GB (default)
- answerdotai/answerai-colbert-small-v1: 96-dim, 0.13 GB (multilingual)
- jinaai/jina-colbert-v2: 128-dim, 8K context (requires fastembed >= 0.4)

Usage:
    embedder = ColBERTEmbedder()

    # Query embedding (multi-vector)
    query_vecs = embedder.embed_query("What is Python?")
    # Shape: (num_query_tokens, 128)

    # Document embedding (multi-vector)
    doc_vecs = embedder.embed_document("Python is a programming language.")
    # Shape: (num_doc_tokens, 128)

    # Aggregated single vector for UMAP/TDA
    agg_vec = embedder.aggregate(doc_vecs)
    # Shape: (128,)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np


# Lazy import to avoid loading fastembed unless used
_LateInteractionTextEmbedding = None


def _ensure_fastembed():
    """Lazy import fastembed."""
    global _LateInteractionTextEmbedding
    if _LateInteractionTextEmbedding is None:
        try:
            from fastembed import LateInteractionTextEmbedding
            _LateInteractionTextEmbedding = LateInteractionTextEmbedding
        except ImportError as e:
            raise ImportError(
                "fastembed not installed. Install with: uv add fastembed"
            ) from e


class AggregationMethod(str, Enum):
    """Method for aggregating multi-vectors to single vector."""
    MEAN = "mean"   # Average all token vectors
    MAX = "max"     # Max pooling across tokens
    FIRST = "first" # First token (CLS-style)


@dataclass
class EmbeddingResult:
    """Result from encoding text."""
    multi_vectors: np.ndarray    # (n_tokens, dim) - for MaxSim search
    aggregated_vector: np.ndarray  # (dim,) - for UMAP/TDA projection
    source_type: str             # "query" or "document"
    metadata: dict[str, Any] | None = None


class ColBERTEmbedder:
    """Multi-vector embedder using ColBERT via fastembed.

    Stores both multi-vectors (for search quality) and aggregated single vectors
    (for grid projection and TDA).

    Architecture:
    - Model: ColBERT v2 (BERT-based with projection layer)
    - Output: Multiple 128-dim vectors per document (ColBERT-style)
    - Runtime: ONNX (CPU-based, no GPU conflicts)
    - Aggregation: Configurable (mean/max/first) for single-vector tasks

    Memory usage:
    - colbert-ir/colbertv2.0: ~440 MB
    - answerdotai/answerai-colbert-small-v1: ~130 MB
    """

    # Default ColBERT model
    DEFAULT_MODEL = "colbert-ir/colbertv2.0"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        aggregation: str | AggregationMethod = AggregationMethod.MEAN,
        batch_size: int = 32,
    ):
        """Initialize ColBERT embedder.

        Args:
            model_name: fastembed model identifier
            aggregation: Method for aggregating multi-vectors
            batch_size: Batch size for encoding
        """
        _ensure_fastembed()

        self.model_name = model_name
        self.aggregation = (
            AggregationMethod(aggregation)
            if isinstance(aggregation, str)
            else aggregation
        )
        self.batch_size = batch_size

        # Lazy initialization
        self._model = None

    @property
    def model(self):
        """Get or create fastembed model."""
        if self._model is None:
            self._model = _LateInteractionTextEmbedding(self.model_name)
        return self._model

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension (128 for ColBERT v2)."""
        # ColBERT v2 uses 128-dim embeddings
        return 128

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a query to multi-vectors.

        Args:
            query: Query text

        Returns:
            Multi-vectors: (num_tokens, dim)
        """
        embeddings = list(self.model.query_embed(query))
        return embeddings[0] if embeddings else np.zeros((1, self.embedding_dim))

    def embed_document(self, text: str) -> np.ndarray:
        """Embed a document to multi-vectors.

        Args:
            text: Document text

        Returns:
            Multi-vectors: (num_tokens, dim)
        """
        embeddings = list(self.model.passage_embed(text))
        return embeddings[0] if embeddings else np.zeros((1, self.embedding_dim))

    def embed_documents(self, texts: list[str]) -> list[np.ndarray]:
        """Embed multiple documents to multi-vectors.

        Args:
            texts: List of document texts

        Returns:
            List of multi-vectors, each (num_tokens, dim)
        """
        return list(self.model.passage_embed(texts))

    def aggregate(self, multi_vectors: np.ndarray) -> np.ndarray:
        """Aggregate multi-vectors to single vector.

        Args:
            multi_vectors: (num_tokens, dim)

        Returns:
            Aggregated vector: (dim,)
        """
        if self.aggregation == AggregationMethod.MEAN:
            agg = np.mean(multi_vectors, axis=0)
        elif self.aggregation == AggregationMethod.MAX:
            agg = np.max(multi_vectors, axis=0)
        elif self.aggregation == AggregationMethod.FIRST:
            agg = multi_vectors[0]
        else:
            raise ValueError(f"Unknown aggregation: {self.aggregation}")

        # Normalize to unit length (for cosine similarity)
        norm = np.linalg.norm(agg)
        if norm > 0:
            agg = agg / norm

        return agg

    def encode_text(self, text: str, is_query: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """Encode text to multi-vectors and aggregated single vector.

        Args:
            text: Text to embed
            is_query: If True, use query embedding; else document embedding

        Returns:
            (multi_vectors, aggregated_vector)
        """
        if is_query:
            multi_vecs = self.embed_query(text)
        else:
            multi_vecs = self.embed_document(text)

        agg_vec = self.aggregate(multi_vecs)
        return multi_vecs, agg_vec

    def encode_batch(self, texts: list[str], is_query: bool = False) -> list[EmbeddingResult]:
        """Encode batch of texts.

        Args:
            texts: List of texts
            is_query: If True, use query embedding

        Returns:
            List of EmbeddingResult
        """
        results = []

        if is_query:
            # Query embed one by one (different handling)
            for text in texts:
                multi_vecs = self.embed_query(text)
                agg_vec = self.aggregate(multi_vecs)
                results.append(EmbeddingResult(
                    multi_vectors=multi_vecs,
                    aggregated_vector=agg_vec,
                    source_type="query",
                ))
        else:
            # Document embed in batch
            multi_vecs_list = self.embed_documents(texts)
            for multi_vecs in multi_vecs_list:
                agg_vec = self.aggregate(multi_vecs)
                results.append(EmbeddingResult(
                    multi_vectors=multi_vecs,
                    aggregated_vector=agg_vec,
                    source_type="document",
                ))

        return results

    def compute_maxsim(
        self,
        query_vecs: np.ndarray,
        doc_vecs: np.ndarray,
    ) -> float:
        """Compute MaxSim score between query and document.

        MaxSim (maximum similarity) is the ColBERT late-interaction scoring:
        For each query token, find max similarity with any document token,
        then sum across query tokens.

        Args:
            query_vecs: (num_query_tokens, dim)
            doc_vecs: (num_doc_tokens, dim)

        Returns:
            MaxSim score (higher = more similar)
        """
        # Compute pairwise similarities: (q_tokens, d_tokens)
        similarities = np.dot(query_vecs, doc_vecs.T)

        # For each query token, take max similarity with any doc token
        max_sims = np.max(similarities, axis=1)

        # Sum across query tokens
        return float(np.sum(max_sims))


# Module-level singleton
_embedder: ColBERTEmbedder | None = None


def get_colbert_embedder(
    model_name: str | None = None,
    aggregation: str | AggregationMethod = AggregationMethod.MEAN,
) -> ColBERTEmbedder:
    """Get or create ColBERT embedder singleton.

    Args:
        model_name: Override model name
        aggregation: Aggregation method

    Returns:
        ColBERTEmbedder instance
    """
    global _embedder
    if _embedder is None:
        _embedder = ColBERTEmbedder(
            model_name=model_name or ColBERTEmbedder.DEFAULT_MODEL,
            aggregation=aggregation,
        )
    return _embedder
