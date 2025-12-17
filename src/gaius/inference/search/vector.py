"""Vector search over KB using Qdrant with ColNomic multi-vector embeddings.

GPU-accelerated multimodal vector search using ColNomic (nomic-ai/colnomic-embed-multimodal-7b).
Supports text and image embeddings in a unified 128-dim space.

ColNomic Architecture:
    - One 128-dim vector per token (vs single vector for entire document)
    - Late interaction via MaxSim scoring at search time
    - GPU-accelerated via colpali-engine (requires CUDA)
    - Unified text+image embedding space
    - Separate "agg" vector for UMAP/TDA projection

NO CPU FALLBACK: This module requires GPU. If GPU is unavailable or unhealthy,
operations will fail explicitly rather than silently degrading to CPU.

Usage:
    vector_search = get_vector_search()
    vector_search.index_kb()  # Index all KB documents with ColNomic

    results = vector_search.search("distributed consensus", top_k=5)
    for r in results:
        print(f"{r.path}: {r.score:.3f}")

    # Image search
    results = vector_search.search_by_image("path/to/image.png")
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


def get_vector_search(
    kb_root: Path | str | None = None,
    device: str | None = None,
) -> VectorSearchMulti:
    """Get or create multi-vector search singleton.

    Uses ColNomic (GPU-accelerated) for multimodal embeddings.
    This provides late-interaction retrieval with MaxSim scoring.

    Args:
        kb_root: KB root directory
        device: GPU device (e.g., "cuda:0")

    Returns:
        VectorSearchMulti instance

    Raises:
        RuntimeError: If GPU is not available
    """
    return get_vector_search_multi(kb_root, device=device)
