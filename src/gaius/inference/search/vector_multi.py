"""Multi-vector search over KB using Qdrant and ColNomic (GPU-accelerated).

Unified multimodal vector search using ColNomic embeddings:
- GPU-accelerated via colpali-engine (nomic-ai/colnomic-embed-multimodal-7b)
- Qdrant named vectors: "agg" for initial retrieval, multi-vectors in payload
- MaxSim late-interaction scoring for high-quality retrieval
- 128-dim per token, unified text+image embedding space

NO CPU FALLBACK: This module requires GPU. If GPU is unavailable or unhealthy,
operations will fail explicitly rather than silently degrading to CPU.

Usage:
    vector_search = VectorSearchMulti()
    vector_search.index_kb()  # Index text and image documents

    results = vector_search.search("query text", top_k=5)
    for r in results:
        print(f"{r.path}: {r.score:.3f}")
"""

import base64
import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Union

import numpy as np
from PIL import Image
from qdrant_client import QdrantClient, models

from .colqwen import ColQwenEmbedder, get_colqwen_embedder

logger = logging.getLogger(__name__)

# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6339"))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "gaius_kb_colbert_zero")


@dataclass
class VectorSearchResult:
    """A vector search result with citation info."""

    path: str  # KB path
    title: str
    score: float  # MaxSim similarity score
    snippet: str
    chunk_id: str  # For precise citation
    content_type: str = "text"  # "text" or "image"
    metadata: dict = field(default_factory=dict)


@dataclass
class KBChunk:
    """A chunk of KB content for embedding."""

    id: str  # Unique chunk ID (hash of path + chunk_index)
    path: str  # KB file path
    title: str
    content: Union[str, Image.Image]  # Text chunk or PIL Image
    chunk_index: int
    content_type: str = "text"  # "text" or "image"
    metadata: dict = field(default_factory=dict)


class VectorSearchMulti:
    """Multi-vector search engine using Qdrant and ColNomic (GPU-accelerated).

    Indexes KB documents (text and images) with multi-vector embeddings.
    Supports semantic search with MaxSim similarity (late interaction).

    Uses ColNomic via colpali-engine:
    - GPU-accelerated (requires CUDA)
    - 128-dim per token (nomic-ai/colnomic-embed-multimodal-7b)
    - Unified text+image embedding space
    - MaxSim scoring for high-quality retrieval

    NO CPU FALLBACK: GPU failures are surfaced, not hidden.
    """

    ALLOWED_DIRS = ("archive", "current", "scratch")
    CHUNK_SIZE = 512  # Characters per text chunk
    CHUNK_OVERLAP = 64  # Overlap between text chunks
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

    def __init__(
        self,
        kb_root: Path | str | None = None,
        embedder: ColQwenEmbedder | None = None,
        qdrant_host: str = QDRANT_HOST,
        qdrant_port: int = QDRANT_PORT,
        collection_name: str = COLLECTION_NAME,
        device: str | None = None,
    ):
        """Initialize multi-vector search.

        Args:
            kb_root: Root of KB directory
            embedder: ColNomic embedder (None = create from config)
            qdrant_host: Qdrant server host
            qdrant_port: Qdrant server port
            collection_name: Qdrant collection name
            device: GPU device (e.g., "cuda:0"). None = auto-detect.

        Raises:
            RuntimeError: If GPU is not available
        """
        if kb_root is None:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        self.kb_root = Path(kb_root)

        self.collection_name = collection_name
        self._device = device

        # Lazy initialization
        self._embedder: ColQwenEmbedder | None = embedder
        self._client: QdrantClient | None = None
        self._qdrant_host = qdrant_host
        self._qdrant_port = qdrant_port

    @property
    def embedder(self) -> ColQwenEmbedder:
        """Get or create ColNomic embedder.

        When a device is specified, creates a fresh embedder on that device
        instead of using the module-level singleton. This ensures model tensors
        are on the correct GPU when the orchestrator allocates different GPUs.

        Raises:
            RuntimeError: If GPU is not available
        """
        if self._embedder is None:
            import torch
            from opentelemetry import trace

            tracer = trace.get_tracer("gaius.inference.search")

            if not torch.cuda.is_available():
                raise RuntimeError(
                    "ColNomic requires GPU but CUDA is not available. "
                    "Check GPU health with /gpu or nvidia-smi."
                )

            # Determine device
            device = self._device if self._device else "cuda:0"

            # When device is explicitly specified by VectorSearchService,
            # create a fresh embedder on that device instead of using singleton.
            # The singleton may be on a different GPU from a previous allocation.
            if self._device:
                with tracer.start_as_current_span("colnomic.embedder.create") as span:
                    span.set_attribute("device", device)
                    span.set_attribute("singleton", False)
                    span.add_event("colnomic.device.explicit", {"device": device})
                    self._embedder = ColQwenEmbedder(device=device)
                    span.add_event("colnomic.embedder.ready")
            else:
                # Use singleton for default behavior (backwards compatibility)
                with tracer.start_as_current_span("colnomic.embedder.singleton") as span:
                    span.set_attribute("device", device)
                    span.set_attribute("singleton", True)
                    self._embedder = get_colqwen_embedder()
                    span.add_event("colnomic.singleton.retrieved")

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
        """Get embedding dimension (128 for ColNomic)."""
        return 128

    def ensure_collection(self) -> None:
        """Ensure Qdrant collection exists with proper schema."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            # Create collection with aggregated vector for initial retrieval
            # Multi-vectors stored in payload for MaxSim reranking
            vectors_config = {
                "agg": models.VectorParams(
                    size=self.embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            }

            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=vectors_config,
            )
            logger.info(f"Created Qdrant collection: {self.collection_name}")

    def index_kb(self, batch_size: int = 8, include_images: bool = True) -> int:
        """Index all KB documents into Qdrant using ColNomic multi-vectors.

        Args:
            batch_size: Number of chunks to embed at once (smaller for GPU memory)
            include_images: Whether to index image files

        Returns:
            Number of chunks indexed

        Raises:
            RuntimeError: If GPU is not available
        """
        self.ensure_collection()

        chunks = list(self._load_chunks(include_images=include_images))
        if not chunks:
            return 0

        total_indexed = 0

        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            # Separate text and image chunks
            text_chunks = [c for c in batch if c.content_type == "text"]
            image_chunks = [c for c in batch if c.content_type == "image"]

            points = []

            # Process text chunks
            for chunk in text_chunks:
                try:
                    multi_vecs, agg_vec = self.embedder.encode_text(
                        chunk.content, prefix=""  # No prefix for documents
                    )

                    point = self._create_point(chunk, multi_vecs, agg_vec)
                    points.append(point)
                except Exception as e:
                    logger.error(f"Failed to embed text chunk {chunk.path}: {e}")
                    raise  # Don't silently skip - surface GPU errors

            # Process image chunks
            for chunk in image_chunks:
                try:
                    multi_vecs, agg_vec = self.embedder.encode_image(chunk.content)

                    point = self._create_point(chunk, multi_vecs, agg_vec)
                    points.append(point)
                except Exception as e:
                    logger.error(f"Failed to embed image chunk {chunk.path}: {e}")
                    raise  # Don't silently skip - surface GPU errors

            # Upsert to Qdrant
            if points:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                )
                total_indexed += len(points)

        logger.info(f"Indexed {total_indexed} chunks to {self.collection_name}")
        return total_indexed

    def _create_point(
        self, chunk: KBChunk, multi_vecs: np.ndarray, agg_vec: np.ndarray
    ) -> models.PointStruct:
        """Create a Qdrant point from a chunk and its embeddings."""
        # Prepare content snippet for payload
        if chunk.content_type == "text":
            content_snippet = chunk.content[:500] if isinstance(chunk.content, str) else ""
        else:
            content_snippet = "[image]"

        return models.PointStruct(
            id=self._hash_to_int(chunk.id),
            vector={
                "agg": agg_vec.tolist(),
            },
            payload={
                "chunk_id": chunk.id,
                "path": chunk.path,
                "title": chunk.title,
                "content": content_snippet,
                "content_type": chunk.content_type,
                "chunk_index": chunk.chunk_index,
                # Store multi-vectors as base64 for MaxSim search
                "multi_vectors_shape": list(multi_vecs.shape),
                "multi_vectors": self._serialize_array(multi_vecs),
                **chunk.metadata,
            },
        )

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        use_maxsim: bool = True,
        content_type: str | None = None,
    ) -> list[VectorSearchResult]:
        """Search KB using multi-vector similarity (MaxSim).

        Args:
            query: Search query text
            top_k: Maximum results to return
            min_score: Minimum similarity threshold
            use_maxsim: Use MaxSim scoring (True) or aggregated cosine (False)
            content_type: Filter by content type ("text", "image", or None for all)

        Returns:
            List of VectorSearchResult sorted by score descending

        Raises:
            RuntimeError: If GPU is not available
        """
        from opentelemetry import trace
        from opentelemetry.trace import StatusCode

        tracer = trace.get_tracer("gaius.inference.search")

        with tracer.start_as_current_span("vector_search.search") as span:
            span.set_attribute("query", query[:100])  # Truncate for safety
            span.set_attribute("top_k", top_k)
            span.set_attribute("min_score", min_score)
            span.set_attribute("use_maxsim", use_maxsim)
            span.set_attribute("content_type", content_type or "all")
            span.set_attribute("device", self._device or "default")

            try:
                # Ensure collection exists
                try:
                    self.ensure_collection()
                except Exception as e:
                    span.set_status(StatusCode.ERROR, f"Qdrant connection failed: {e}")
                    span.record_exception(e)
                    raise RuntimeError(f"Qdrant connection failed: {e}")

                # Check if collection has points
                info = self.client.get_collection(self.collection_name)
                span.set_attribute("collection_points", info.points_count)
                if info.points_count == 0:
                    span.add_event("search.empty_collection")
                    return []

                # Generate query embedding using ColNomic
                span.add_event("search.encoding_query")
                query_multi_vecs, query_agg_vec = self.embedder.encode_text(
                    query, prefix="search_query: "
                )
                span.add_event("search.query_encoded", {"embedding_dim": len(query_agg_vec)})

                # Build filter if content_type specified
                query_filter = None
                if content_type:
                    query_filter = models.Filter(
                        must=[
                            models.FieldCondition(
                                key="content_type",
                                match=models.MatchValue(value=content_type),
                            )
                        ]
                    )

                # Execute search
                span.add_event("search.executing", {"strategy": "maxsim" if use_maxsim else "aggregated"})
                if use_maxsim:
                    results = self._search_maxsim(
                        query_multi_vecs, query_agg_vec, top_k, min_score, query_filter
                    )
                else:
                    results = self._search_aggregated(
                        query_agg_vec, top_k, min_score, query_filter
                    )

                span.set_attribute("results_count", len(results))
                span.add_event("search.completed", {"results_count": len(results)})
                return results

            except Exception as e:
                span.set_status(StatusCode.ERROR, str(e))
                span.record_exception(e)
                raise

    def search_by_image(
        self,
        image: Union[str, Path, Image.Image],
        top_k: int = 10,
        min_score: float = 0.0,
        use_maxsim: bool = True,
    ) -> list[VectorSearchResult]:
        """Search KB using an image query.

        Args:
            image: PIL Image, or path to image file
            top_k: Maximum results to return
            min_score: Minimum similarity threshold
            use_maxsim: Use MaxSim scoring (True) or aggregated cosine (False)

        Returns:
            List of VectorSearchResult sorted by score descending

        Raises:
            RuntimeError: If GPU is not available
        """
        # Load image if path
        if isinstance(image, (str, Path)):
            image = Image.open(image).convert("RGB")

        # Ensure collection exists
        try:
            self.ensure_collection()
        except Exception as e:
            logger.error(f"Qdrant not available: {e}")
            raise RuntimeError(f"Qdrant connection failed: {e}")

        # Check if collection has points
        info = self.client.get_collection(self.collection_name)
        if info.points_count == 0:
            return []

        # Generate query embedding using ColNomic
        query_multi_vecs, query_agg_vec = self.embedder.encode_image(image)

        if use_maxsim:
            return self._search_maxsim(
                query_multi_vecs, query_agg_vec, top_k, min_score, None
            )
        else:
            return self._search_aggregated(query_agg_vec, top_k, min_score, None)

    def _search_maxsim(
        self,
        query_multi_vecs: np.ndarray,
        query_agg_vec: np.ndarray,
        top_k: int,
        min_score: float,
        query_filter: models.Filter | None,
    ) -> list[VectorSearchResult]:
        """Search with MaxSim reranking."""
        # First, get top_k * 3 candidates using aggregated vector
        candidate_results = self.client.search(
            collection_name=self.collection_name,
            query_vector=("agg", query_agg_vec.tolist()),
            limit=top_k * 3,  # Over-fetch for reranking
            with_payload=True,
            query_filter=query_filter,
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

    def _search_aggregated(
        self,
        query_agg_vec: np.ndarray,
        top_k: int,
        min_score: float,
        query_filter: models.Filter | None,
    ) -> list[VectorSearchResult]:
        """Search using aggregated vector only (faster, less accurate)."""
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=("agg", query_agg_vec.tolist()),
            limit=top_k,
            score_threshold=min_score,
            query_filter=query_filter,
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

    def _load_chunks(self, include_images: bool = True) -> Iterator[KBChunk]:
        """Load and chunk all KB documents (text and images)."""
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
                            content_type="text",
                        )
                except Exception as e:
                    logger.warning(f"Failed to load {md_file}: {e}")
                    continue

            # Process image files if enabled
            if include_images:
                for ext in self.IMAGE_EXTENSIONS:
                    for img_file in dir_path.rglob(f"*{ext}"):
                        try:
                            rel_path = str(img_file.relative_to(self.kb_root))
                            chunk_id = hashlib.sha256(
                                f"{rel_path}:image:0".encode()
                            ).hexdigest()[:16]

                            # Load image
                            image = Image.open(img_file).convert("RGB")

                            yield KBChunk(
                                id=chunk_id,
                                path=rel_path,
                                title=img_file.stem,
                                content=image,
                                chunk_index=0,
                                content_type="image",
                            )
                        except Exception as e:
                            logger.warning(f"Failed to load image {img_file}: {e}")
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
        return base64.b64encode(arr.astype(np.float32).tobytes()).decode("utf-8")

    def _deserialize_array(self, data: str, shape: tuple) -> np.ndarray:
        """Deserialize base64 string to numpy array."""
        bytes_data = base64.b64decode(data)
        arr = np.frombuffer(bytes_data, dtype=np.float32).reshape(shape)
        return arr

    def is_duplicate_thought(
        self, content: str, threshold: float = 0.95
    ) -> tuple[bool, VectorSearchResult | None]:
        """Check if content is semantically duplicate of existing KB entries.

        Args:
            content: Thought content to check (title + body)
            threshold: Similarity threshold (0.0-1.0). Default 0.95 = very similar.

        Returns:
            Tuple of (is_duplicate, most_similar_result).
            If no similar content found, returns (False, None).

        Raises:
            RuntimeError: If vector search fails (caller should handle gracefully)
        """
        # No try-except here - let errors propagate to caller
        # Caller (cognition.py) has fallback to exact hash check
        results = self.search(content, top_k=1, min_score=threshold)
        if results:
            return (True, results[0])
        return (False, None)

    def get_collection_info(self) -> dict:
        """Get information about the Qdrant collection."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status.value,
                "embedding_type": "colnomic",
                "embedding_dim": self.embedding_dim,
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

    def get_all_aggregated_vectors(self) -> tuple[np.ndarray, list[dict]]:
        """Retrieve all aggregated vectors from Qdrant for UMAP/TDA projection.

        Returns:
            Tuple of:
                - Array of aggregated vectors (n_docs, embedding_dim)
                - List of metadata dicts with path, title, chunk_id
        """
        vectors = []
        metadata = []

        try:
            # Check collection exists and has points
            info = self.client.get_collection(self.collection_name)
            if info.points_count == 0:
                return np.array([]), []

            # Scroll through all points
            offset = None
            batch_size = 100

            while True:
                results, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=batch_size,
                    offset=offset,
                    with_vectors=["agg"],
                    with_payload=True,
                )

                if not results:
                    break

                for point in results:
                    payload = point.payload or {}
                    vector = point.vector

                    if vector and "agg" in vector:
                        vectors.append(vector["agg"])
                        metadata.append({
                            "path": payload.get("path", ""),
                            "title": payload.get("title", ""),
                            "chunk_id": payload.get("chunk_id", ""),
                            "content_type": payload.get("content_type", "text"),
                        })

                if offset is None:
                    break

            return np.array(vectors), metadata

        except Exception as e:
            logger.error(f"Failed to retrieve vectors: {e}")
            return np.array([]), []

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
                                "content_type": payload.get("content_type", "text"),
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


def get_vector_search_multi(
    kb_root: Path | str | None = None,
    device: str | None = None,
) -> VectorSearchMulti:
    """Get or create multi-vector search singleton.

    Args:
        kb_root: KB root directory
        device: GPU device (e.g., "cuda:0"). If singleton exists with different
                device, logs a warning but returns existing instance.

    Returns:
        VectorSearchMulti instance

    Raises:
        RuntimeError: If GPU is not available
    """
    global _vector_search_multi
    if _vector_search_multi is None:
        _vector_search_multi = VectorSearchMulti(kb_root, device=device)
    elif device is not None and _vector_search_multi._device != device:
        # Warn if caller requested different device than singleton has
        logger.warning(
            f"VectorSearchMulti already initialized on {_vector_search_multi._device}, "
            f"ignoring requested device {device}. Restart engine to change GPU."
        )
    return _vector_search_multi


def reset_vector_search_multi() -> None:
    """Reset the singleton (for testing or GPU reallocation).

    Use with caution - existing references will become stale.
    """
    global _vector_search_multi
    if _vector_search_multi is not None:
        logger.info("Resetting VectorSearchMulti singleton")
        _vector_search_multi = None
