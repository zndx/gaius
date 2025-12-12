"""Multi-vector search over KB using Qdrant and ColBERT (fastembed).

Extension of vector.py for ColBERT-style multi-vector representation.
Stores both multi-vectors (for search) and aggregated single vectors (for UMAP/TDA).

Key differences from single-vector (vector_single.py):
- Uses ColBERT via fastembed (CPU-based ONNX, no GPU conflicts)
- Qdrant named vectors: "multi" for search, "agg" for projection
- MaxSim late-interaction scoring
- 128-dim per token (colbert-ir/colbertv2.0) or 96-dim (answerdotai)

Models supported:
- colbert-ir/colbertv2.0: 128-dim, 0.44 GB (default, best quality)
- answerdotai/answerai-colbert-small-v1: 96-dim, 0.13 GB (multilingual, faster)

Usage:
    vector_search = VectorSearchMulti()
    vector_search.index_kb()  # Index text documents

    results = vector_search.search("query text", top_k=5)
    for r in results:
        print(f"{r.path}: {r.score:.3f}")
"""

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np
from qdrant_client import QdrantClient, models

from .colbert import ColBERTEmbedder, get_colbert_embedder


# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6339"))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "gaius_kb")  # ColBERT multi-vector collection


@dataclass
class VectorSearchResult:
    """A vector search result with citation info."""

    path: str  # KB path
    title: str
    score: float  # MaxSim similarity score
    snippet: str
    chunk_id: str  # For precise citation
    content_type: str = "text"  # Always "text" for ColBERT
    metadata: dict = field(default_factory=dict)


@dataclass
class KBChunk:
    """A chunk of KB content for embedding (text only for ColBERT)."""

    id: str  # Unique chunk ID (hash of path + chunk_index)
    path: str  # KB file path
    title: str
    content: str  # Text chunk
    chunk_index: int
    metadata: dict = field(default_factory=dict)


class VectorSearchMulti:
    """Multi-vector search engine using Qdrant and ColBERT (fastembed).

    Indexes KB markdown files as chunks with multi-vector embeddings.
    Supports semantic search with MaxSim similarity (late interaction).

    Uses fastembed's ColBERT implementation:
    - CPU-based ONNX runtime (no GPU conflicts)
    - 128-dim per token (colbert-ir/colbertv2.0)
    - MaxSim scoring for high-quality retrieval
    """

    ALLOWED_DIRS = ("archive", "current", "scratch")
    CHUNK_SIZE = 512  # Characters per text chunk
    CHUNK_OVERLAP = 64  # Overlap between text chunks

    def __init__(
        self,
        kb_root: Path | str | None = None,
        embedder: ColBERTEmbedder | None = None,
        qdrant_host: str = QDRANT_HOST,
        qdrant_port: int = QDRANT_PORT,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initialize multi-vector search.

        Args:
            kb_root: Root of KB directory
            embedder: ColBERT embedder (None = create from config)
            qdrant_host: Qdrant server host
            qdrant_port: Qdrant server port
            collection_name: Qdrant collection name
        """
        if kb_root is None:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        self.kb_root = Path(kb_root)

        self.collection_name = collection_name

        # Lazy initialization
        self._embedder: ColBERTEmbedder | None = embedder
        self._client: QdrantClient | None = None
        self._qdrant_host = qdrant_host
        self._qdrant_port = qdrant_port

    @property
    def embedder(self) -> ColBERTEmbedder:
        """Get or create ColBERT embedder."""
        if self._embedder is None:
            self._embedder = get_colbert_embedder()
        return self._embedder

    @property
    def client(self) -> QdrantClient:
        """Get or create Qdrant client."""
        if self._client is None:
            self._client = QdrantClient(
                host=self._qdrant_host,
                port=self._qdrant_port,
            )
        return self._client

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension from embedder (128 for ColQwen)."""
        return self.embedder.embedding_dim

    def ensure_collection(self) -> None:
        """Ensure Qdrant collection exists with named vectors schema."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            # Create collection with named vectors: "multi" and "agg"
            vectors_config = {
                "multi": models.VectorParams(
                    size=self.embedding_dim,
                    distance=models.Distance.DOT,  # Dot product for MaxSim
                    # Note: Qdrant doesn't have native multi-vector support yet,
                    # so we'll store as separate points or flatten
                    # For now, store aggregated only and compute MaxSim client-side
                ),
                "agg": models.VectorParams(
                    size=self.embedding_dim,
                    distance=models.Distance.COSINE,  # Cosine for UMAP/TDA
                ),
            }

            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=vectors_config,
            )

    def index_kb(self, batch_size: int = 32) -> int:
        """Index all KB documents into Qdrant using ColBERT multi-vectors.

        Args:
            batch_size: Number of chunks to embed at once (larger batches ok for CPU)

        Returns:
            Number of chunks indexed
        """
        self.ensure_collection()

        chunks = list(self._load_chunks())
        if not chunks:
            return 0

        total_indexed = 0

        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.content for c in batch]

            # Generate document embeddings using ColBERT
            # embed_documents returns list of multi-vectors: [(n_tokens, dim), ...]
            multi_vecs_list = self.embedder.embed_documents(texts)

            # Prepare points with named vectors
            points = []
            for chunk, multi_vecs in zip(batch, multi_vecs_list):
                # Aggregate multi-vectors to single vector for UMAP/TDA
                agg_vec = self.embedder.aggregate(multi_vecs)

                point = models.PointStruct(
                    id=self._hash_to_int(chunk.id),
                    vector={
                        "agg": agg_vec.tolist(),
                    },
                    payload={
                        "chunk_id": chunk.id,
                        "path": chunk.path,
                        "title": chunk.title,
                        "content": chunk.content[:500],
                        "content_type": "text",
                        "chunk_index": chunk.chunk_index,
                        # Store multi-vectors as base64 for MaxSim search
                        "multi_vectors_shape": list(multi_vecs.shape),
                        "multi_vectors": self._serialize_array(multi_vecs),
                        **chunk.metadata,
                    },
                )
                points.append(point)

            # Upsert to Qdrant
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
            )
            total_indexed += len(points)

        return total_indexed

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        use_maxsim: bool = True,
    ) -> list[VectorSearchResult]:
        """Search KB using multi-vector similarity (MaxSim).

        Args:
            query: Search query
            top_k: Maximum results to return
            min_score: Minimum similarity threshold
            use_maxsim: Use MaxSim scoring (True) or aggregated cosine (False)

        Returns:
            List of VectorSearchResult sorted by score descending
        """
        # Ensure collection exists
        try:
            self.ensure_collection()
        except Exception:
            return []  # Qdrant not available

        # Check if collection has points
        info = self.client.get_collection(self.collection_name)
        if info.points_count == 0:
            return []

        # Generate query embedding using ColBERT
        query_multi_vecs = self.embedder.embed_query(query)
        query_agg_vec = self.embedder.aggregate(query_multi_vecs)

        if use_maxsim:
            # MaxSim search: need to fetch candidates and rescore
            # First, get top_k * 3 candidates using aggregated vector
            candidate_results = self.client.search(
                collection_name=self.collection_name,
                query_vector=("agg", query_agg_vec.tolist()),
                limit=top_k * 3,  # Over-fetch for reranking
                with_payload=True,
            )

            # Rescore with MaxSim
            maxsim_results = []
            for hit in candidate_results:
                payload = hit.payload or {}

                # Deserialize multi-vectors
                try:
                    doc_multi_vecs = self._deserialize_array(
                        payload.get("multi_vectors", ""),
                        payload.get("multi_vectors_shape", (0, self.embedding_dim)),
                    )

                    # Compute MaxSim score
                    maxsim_score = self.embedder.compute_maxsim(
                        query_multi_vecs, doc_multi_vecs
                    )

                    maxsim_results.append((hit, maxsim_score))
                except Exception:
                    # Fallback to aggregated score
                    maxsim_results.append((hit, hit.score))

            # Sort by MaxSim score
            maxsim_results.sort(key=lambda x: x[1], reverse=True)

            # Take top_k and filter by min_score
            results = []
            for hit, score in maxsim_results[:top_k]:
                if score >= min_score:
                    payload = hit.payload or {}
                    results.append(
                        VectorSearchResult(
                            path=payload.get("path", ""),
                            title=payload.get("title", ""),
                            score=score,
                            snippet=payload.get("content", "")[:200] or "[image]",
                            chunk_id=payload.get("chunk_id", ""),
                            content_type=payload.get("content_type", "text"),
                            metadata={
                                k: v
                                for k, v in payload.items()
                                if k
                                not in (
                                    "path",
                                    "title",
                                    "content",
                                    "chunk_id",
                                    "content_type",
                                    "multi_vectors",
                                    "multi_vectors_shape",
                                )
                            },
                        )
                    )

            return results

        else:
            # Fallback: use aggregated vector with cosine similarity
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=("agg", query_agg_vec.tolist()),
                limit=top_k,
                score_threshold=min_score,
            )

            # Convert to result objects
            search_results = []
            for hit in results:
                payload = hit.payload or {}
                search_results.append(
                    VectorSearchResult(
                        path=payload.get("path", ""),
                        title=payload.get("title", ""),
                        score=hit.score,
                        snippet=payload.get("content", "")[:200] or "[image]",
                        chunk_id=payload.get("chunk_id", ""),
                        content_type=payload.get("content_type", "text"),
                        metadata={
                            k: v
                            for k, v in payload.items()
                            if k
                            not in (
                                "path",
                                "title",
                                "content",
                                "chunk_id",
                                "content_type",
                                "multi_vectors",
                                "multi_vectors_shape",
                            )
                        },
                    )
                )

            return search_results

    def _load_chunks(self) -> Iterator[KBChunk]:
        """Load and chunk all KB text documents."""
        for dir_name in self.ALLOWED_DIRS:
            dir_path = self.kb_root / dir_name
            if not dir_path.exists():
                continue

            # Process markdown files
            for md_file in dir_path.rglob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    rel_path = str(md_file.relative_to(self.kb_root))
                    title = self._extract_title(content, md_file.stem)

                    # Chunk the text content
                    for i, chunk_text in enumerate(self._chunk_text(content)):
                        chunk_id = hashlib.sha256(
                            f"{rel_path}:text:{i}".encode()
                        ).hexdigest()[:16]

                        yield KBChunk(
                            id=chunk_id,
                            path=rel_path,
                            title=title,
                            content=chunk_text,
                            chunk_index=i,
                        )
                except Exception:
                    continue

    def _chunk_text(self, text: str) -> Iterator[str]:
        """Split text into overlapping chunks (character-based)."""
        if len(text) <= self.CHUNK_SIZE:
            yield text
            return

        start = 0
        while start < len(text):
            end = start + self.CHUNK_SIZE
            chunk = text[start:end]

            # Try to break at sentence boundary
            if end < len(text):
                last_period = chunk.rfind(". ")
                if last_period > self.CHUNK_SIZE // 2:
                    chunk = chunk[: last_period + 1]
                    end = start + last_period + 1

            yield chunk.strip()
            start = end - self.CHUNK_OVERLAP

    def _extract_title(self, content: str, fallback: str) -> str:
        """Extract title from markdown heading."""
        for line in content.split("\n")[:10]:
            if line.startswith("# "):
                return line[2:].strip()
        return fallback.replace("-", " ").replace("_", " ").title()

    def _hash_to_int(self, s: str) -> int:
        """Convert string hash to positive integer for Qdrant ID."""
        return int(hashlib.sha256(s.encode()).hexdigest()[:15], 16)

    def _serialize_array(self, arr: np.ndarray) -> str:
        """Serialize numpy array to base64 string for storage."""
        import base64

        return base64.b64encode(arr.tobytes()).decode("utf-8")

    def _deserialize_array(self, data: str, shape: tuple) -> np.ndarray:
        """Deserialize base64 string to numpy array."""
        import base64

        bytes_data = base64.b64decode(data)
        arr = np.frombuffer(bytes_data, dtype=np.float32).reshape(shape)
        return arr

    def get_collection_info(self) -> dict:
        """Get information about the Qdrant collection."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status.value,
                "embedding_type": "multi",
            }
        except Exception as e:
            return {"error": str(e)}

    def clear_collection(self) -> bool:
        """Delete and recreate the collection."""
        try:
            self.client.delete_collection(self.collection_name)
            self.ensure_collection()
            return True
        except Exception:
            return False

    def get_all_multi_vectors(self) -> tuple[list[np.ndarray], list[dict]]:
        """Retrieve all multi-vectors from Qdrant for IsoFeatures computation.

        Returns:
            Tuple of:
                - List of multi-vector arrays [(n_tokens, embedding_dim), ...]
                - List of metadata dicts with path, title, chunk_id
        """
        multi_vectors = []
        metadata = []

        try:
            # Check collection exists and has points
            info = self.client.get_collection(self.collection_name)
            if info.points_count == 0:
                return [], []

            # Scroll through all points
            offset = None
            batch_size = 100

            while True:
                results, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=batch_size,
                    offset=offset,
                    with_vectors=False,  # We get vectors from payload
                    with_payload=True,
                )

                if not results:
                    break

                for point in results:
                    payload = point.payload or {}

                    # Deserialize multi-vectors from payload
                    mv_data = payload.get("multi_vectors", "")
                    mv_shape = payload.get("multi_vectors_shape", [])

                    if mv_data and mv_shape:
                        try:
                            mv = self._deserialize_array(mv_data, tuple(mv_shape))
                            multi_vectors.append(mv)
                            metadata.append({
                                "path": payload.get("path", ""),
                                "title": payload.get("title", ""),
                                "chunk_id": payload.get("chunk_id", ""),
                            })
                        except Exception:
                            # Skip malformed entries
                            continue

                if offset is None:
                    break

            return multi_vectors, metadata

        except Exception:
            return [], []


# Module-level singleton
_vector_search_multi: VectorSearchMulti | None = None


def get_vector_search_multi(kb_root: Path | str | None = None) -> VectorSearchMulti:
    """Get or create multi-vector search singleton.

    Reads embedding model from config if available.
    """
    global _vector_search_multi
    if _vector_search_multi is None:
        _vector_search_multi = VectorSearchMulti(kb_root)
    return _vector_search_multi
