"""Vector search over KB using Qdrant with ColBERT multi-vector embeddings.

Multi-vector only implementation using ColBERT (via fastembed) for late-interaction
retrieval. Single-vector code paths have been removed - multi-vector is key for
high-quality semantic search.

ColBERT Architecture:
    - One 128-dim vector per token (vs single vector for entire document)
    - Late interaction via MaxSim scoring at search time
    - CPU-based ONNX runtime (fastembed) - no GPU conflicts
    - Separate "agg" vector for UMAP/TDA projection

Resource Management:
    ColBERT via fastembed runs entirely on CPU, so no GPU orchestration needed.
    For future GPU-based embeddings, use the engine's EmbedTexts gRPC API.

Usage:
    vector_search = get_vector_search()
    vector_search.index_kb()  # Index all KB documents with ColBERT

    results = vector_search.search("distributed consensus", top_k=5)
    for r in results:
        print(f"{r.path}: {r.score:.3f}")
"""

from pathlib import Path

# Multi-vector is the only implementation - re-export from vector_multi
from .vector_multi import (
    VectorSearchMulti,
    VectorSearchResult,
    KBChunk,
    get_vector_search_multi,
    QDRANT_HOST,
    QDRANT_PORT,
    COLLECTION_NAME,
)

# Re-export types for backward compatibility
__all__ = [
    "VectorSearch",  # Alias to VectorSearchMulti
    "VectorSearchMulti",
    "VectorSearchResult",
    "KBChunk",
    "get_vector_search",
    "QDRANT_HOST",
    "QDRANT_PORT",
    "COLLECTION_NAME",
]

# Type alias for backward compatibility
VectorSearch = VectorSearchMulti


def get_vector_search(kb_root: Path | str | None = None) -> VectorSearchMulti:
    """Get or create multi-vector search singleton.

    Multi-vector (ColBERT) is the only supported embedding type.
    This provides late-interaction retrieval with MaxSim scoring.

    Returns:
        VectorSearchMulti instance (ColBERT via fastembed)
    """
    return get_vector_search_multi(kb_root)
