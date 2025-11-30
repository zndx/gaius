"""Vector search over KB using Qdrant.

Uses sentence-transformers for local embeddings and Qdrant for vector storage/search.
Embeddings are generated on-demand and cached in Qdrant.

Usage:
    vector_search = VectorSearch()
    await vector_search.index_kb()  # Index all KB documents

    results = await vector_search.search("distributed consensus", top_k=5)
    for r in results:
        print(f"{r.path}: {r.score:.3f}")
"""

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer


# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6339"))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "gaius_kb")

# Default embedding model - good balance of quality and speed
# all-MiniLM-L6-v2: 384 dim, fast
# all-mpnet-base-v2: 768 dim, better quality
# nomic-ai/nomic-embed-text-v1.5: 768 dim, excellent quality
DEFAULT_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


@dataclass
class VectorSearchResult:
    """A vector search result with citation info."""

    path: str  # KB path
    title: str
    score: float  # Cosine similarity (0-1)
    snippet: str
    chunk_id: str  # For precise citation
    metadata: dict = field(default_factory=dict)


@dataclass
class KBChunk:
    """A chunk of KB content for embedding."""

    id: str  # Unique chunk ID (hash of path + chunk_index)
    path: str  # KB file path
    title: str
    content: str  # Chunk text
    chunk_index: int
    metadata: dict = field(default_factory=dict)


class VectorSearch:
    """Vector search engine using Qdrant and sentence-transformers.

    Indexes KB markdown files as chunks with embeddings.
    Supports semantic search with cosine similarity.
    """

    ALLOWED_DIRS = ("archive", "current", "scratch")
    CHUNK_SIZE = 512  # Characters per chunk
    CHUNK_OVERLAP = 64  # Overlap between chunks

    def __init__(
        self,
        kb_root: Path | str | None = None,
        model_name: str = DEFAULT_MODEL,
        qdrant_host: str = QDRANT_HOST,
        qdrant_port: int = QDRANT_PORT,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initialize vector search.

        Args:
            kb_root: Root of KB directory
            model_name: Sentence transformer model name
            qdrant_host: Qdrant server host
            qdrant_port: Qdrant server port
            collection_name: Qdrant collection name
        """
        if kb_root is None:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        self.kb_root = Path(kb_root)

        self.model_name = model_name
        self.collection_name = collection_name

        # Lazy initialization
        self._model: SentenceTransformer | None = None
        self._client: QdrantClient | None = None
        self._qdrant_host = qdrant_host
        self._qdrant_port = qdrant_port

    @property
    def model(self) -> SentenceTransformer:
        """Get or create embedding model."""
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

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
        """Get embedding dimension from model."""
        return self.model.get_sentence_embedding_dimension()

    def ensure_collection(self) -> None:
        """Ensure Qdrant collection exists with correct schema."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            )

    def index_kb(self, batch_size: int = 32) -> int:
        """Index all KB documents into Qdrant.

        Args:
            batch_size: Number of chunks to embed at once

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

            # Generate embeddings
            texts = [c.content for c in batch]
            embeddings = self.model.encode(texts, show_progress_bar=False)

            # Prepare points
            points = [
                models.PointStruct(
                    id=self._hash_to_int(chunk.id),
                    vector=embedding.tolist(),
                    payload={
                        "chunk_id": chunk.id,
                        "path": chunk.path,
                        "title": chunk.title,
                        "content": chunk.content[:500],  # Truncate for storage
                        "chunk_index": chunk.chunk_index,
                        **chunk.metadata,
                    },
                )
                for chunk, embedding in zip(batch, embeddings)
            ]

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
    ) -> list[VectorSearchResult]:
        """Search KB using semantic similarity.

        Args:
            query: Search query
            top_k: Maximum results to return
            min_score: Minimum similarity threshold (0-1)

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
        query_embedding = self.model.encode(query, show_progress_bar=False)

        # Search Qdrant
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding.tolist(),
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
                    snippet=payload.get("content", "")[:200],
                    chunk_id=payload.get("chunk_id", ""),
                    metadata={
                        k: v
                        for k, v in payload.items()
                        if k not in ("path", "title", "content", "chunk_id")
                    },
                )
            )

        return search_results

    def _load_chunks(self) -> Iterator[KBChunk]:
        """Load and chunk all KB markdown documents."""
        for dir_name in self.ALLOWED_DIRS:
            dir_path = self.kb_root / dir_name
            if not dir_path.exists():
                continue

            for md_file in dir_path.rglob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    rel_path = str(md_file.relative_to(self.kb_root))
                    title = self._extract_title(content, md_file.stem)

                    # Chunk the content
                    for i, chunk_text in enumerate(self._chunk_text(content)):
                        chunk_id = hashlib.sha256(
                            f"{rel_path}:{i}".encode()
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
        """Split text into overlapping chunks."""
        # Simple character-based chunking
        # Could be improved with sentence boundaries
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

    def get_collection_info(self) -> dict:
        """Get information about the Qdrant collection."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status.value,
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
_vector_search: VectorSearch | None = None


def get_vector_search(kb_root: Path | str | None = None) -> VectorSearch:
    """Get or create vector search singleton."""
    global _vector_search
    if _vector_search is None:
        _vector_search = VectorSearch(kb_root)
    return _vector_search
