"""Multi-vector search over KB using Qdrant and ColQwen2.5.

Extension of vector.py for multimodal embeddings with ColBERT-style multi-vector representation.
Stores both multi-vectors (for search) and aggregated single vectors (for UMAP/TDA).

Key differences from single-vector (vector_single.py):
- Uses ColQwen2.5 embedder (text + images)
- Qdrant named vectors: "multi" for search, "agg" for projection
- MaxSim late-interaction scoring
- Supports .png, .jpg, .pdf files alongside .md

Usage:
    vector_search = VectorSearchMulti()
    vector_search.index_kb()  # Index text + images

    results = vector_search.search("query text", top_k=5)
    for r in results:
        print(f"{r.path}: {r.score:.3f} [{r.content_type}]")
"""

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image
from qdrant_client import QdrantClient, models

from .colqwen import ColQwenEmbedder, get_colqwen_embedder, load_image


# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6339"))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "gaius_kb_multi")  # Separate collection


@dataclass
class VectorSearchResult:
    """A vector search result with citation info."""

    path: str  # KB path
    title: str
    score: float  # MaxSim similarity score
    snippet: str
    chunk_id: str  # For precise citation
    content_type: str  # "text" or "image"
    metadata: dict = field(default_factory=dict)


@dataclass
class KBChunk:
    """A chunk of KB content for embedding (text or image)."""

    id: str  # Unique chunk ID (hash of path + chunk_index)
    path: str  # KB file path
    title: str
    content: str | Image.Image  # Text chunk or PIL Image
    content_type: str  # "text" or "image"
    chunk_index: int
    metadata: dict = field(default_factory=dict)


class VectorSearchMulti:
    """Multi-vector search engine using Qdrant and ColQwen2.5.

    Indexes KB markdown files and images as chunks with multi-vector embeddings.
    Supports semantic search with MaxSim similarity.
    """

    ALLOWED_DIRS = ("archive", "current", "scratch")
    CHUNK_SIZE = 512  # Characters per text chunk
    CHUNK_OVERLAP = 64  # Overlap between text chunks

    # Image formats supported
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
    PDF_EXTENSION = ".pdf"

    def __init__(
        self,
        kb_root: Path | str | None = None,
        embedder: ColQwenEmbedder | None = None,
        qdrant_host: str = QDRANT_HOST,
        qdrant_port: int = QDRANT_PORT,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initialize multi-vector search.

        Args:
            kb_root: Root of KB directory
            embedder: ColQwen embedder (None = create from config)
            qdrant_host: Qdrant server host
            qdrant_port: Qdrant server port
            collection_name: Qdrant collection name
        """
        if kb_root is None:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        self.kb_root = Path(kb_root)

        self.collection_name = collection_name

        # Lazy initialization
        self._embedder: ColQwenEmbedder | None = embedder
        self._client: QdrantClient | None = None
        self._qdrant_host = qdrant_host
        self._qdrant_port = qdrant_port

    @property
    def embedder(self) -> ColQwenEmbedder:
        """Get or create ColQwen embedder."""
        if self._embedder is None:
            self._embedder = get_colqwen_embedder()
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

    def index_kb(self, batch_size: int = 4) -> int:
        """Index all KB documents and images into Qdrant.

        Args:
            batch_size: Number of chunks to embed at once (small for 7B model)

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

            # Generate embeddings (mixed text/images)
            items = [c.content for c in batch]
            embedding_results = self.embedder.encode_batch(items)

            # Prepare points with named vectors
            points = []
            for chunk, emb_result in zip(batch, embedding_results):
                # For now, store only aggregated vectors in Qdrant
                # Store multi-vectors in payload as numpy array (serialized)
                # This is a simplification - full multi-vector support would need
                # separate storage strategy

                point = models.PointStruct(
                    id=self._hash_to_int(chunk.id),
                    vector={
                        "agg": emb_result.aggregated_vector.tolist(),
                        # "multi": store elsewhere or serialize
                    },
                    payload={
                        "chunk_id": chunk.id,
                        "path": chunk.path,
                        "title": chunk.title,
                        "content": (
                            chunk.content[:500]
                            if isinstance(chunk.content, str)
                            else None
                        ),
                        "content_type": chunk.content_type,
                        "chunk_index": chunk.chunk_index,
                        # Store multi-vectors as base64 for MaxSim search
                        "multi_vectors_shape": emb_result.multi_vectors.shape,
                        "multi_vectors": self._serialize_array(emb_result.multi_vectors),
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

        # Generate query embedding
        query_multi_vecs, query_agg_vec = self.embedder.encode_text(query)

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
        """Load and chunk all KB documents (text + images)."""
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
                            content_type="text",
                            chunk_index=i,
                        )
                except Exception:
                    continue

            # Process image files
            for ext in self.IMAGE_EXTENSIONS:
                for img_file in dir_path.rglob(f"*{ext}"):
                    try:
                        rel_path = str(img_file.relative_to(self.kb_root))
                        title = img_file.stem.replace("-", " ").replace("_", " ").title()

                        # Load image
                        image = load_image(img_file)

                        chunk_id = hashlib.sha256(
                            f"{rel_path}:image:0".encode()
                        ).hexdigest()[:16]

                        yield KBChunk(
                            id=chunk_id,
                            path=rel_path,
                            title=title,
                            content=image,
                            content_type="image",
                            chunk_index=0,  # One chunk per image
                            metadata={"image_format": ext.lstrip(".")},
                        )
                    except Exception:
                        continue

            # TODO: Process PDF files (extract pages as images)
            # for pdf_file in dir_path.rglob("*.pdf"):
            #     ...

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
