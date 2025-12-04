"""Qdrant-backed latent working memory for agent collaboration.

Stores agent thoughts as 768-dim Nomic embeddings in Qdrant,
enabling semantic retrieval and cross-agent context sharing.

This implements LatentMAS-style collaboration where agents
communicate via latent representations rather than full text.
"""

import os
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6339"))
COLLECTION_NAME = os.getenv("GAIUS_LATENT_COLLECTION", "gaius_latent_thoughts")
EMBEDDING_DIM = 768  # Nomic embeddings


@dataclass
class LatentThought:
    """A thought stored in latent working memory.

    Attributes:
        id: Unique identifier
        agent_role: Role of the agent that generated this thought
        content_summary: First 200 chars of content (for debugging)
        embedding: 768-dim Nomic embedding
        domain: Domain/topic context
        created_at: Timestamp
        metadata: Additional metadata
    """

    id: str
    agent_role: str
    content_summary: str
    embedding: np.ndarray
    domain: str
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        agent_role: str,
        content: str,
        embedding: np.ndarray,
        domain: str = "",
        metadata: dict | None = None,
    ) -> "LatentThought":
        """Create a new latent thought.

        Args:
            agent_role: Role of generating agent
            content: Full content (will be summarized)
            embedding: 768-dim embedding vector
            domain: Domain context
            metadata: Optional metadata
        """
        return cls(
            id=str(uuid.uuid4()),
            agent_role=agent_role,
            content_summary=content[:200] + ("..." if len(content) > 200 else ""),
            embedding=embedding,
            domain=domain,
            metadata=metadata or {},
        )

    def similarity(self, other: "LatentThought") -> float:
        """Compute cosine similarity with another thought."""
        return float(np.dot(self.embedding, other.embedding) / (
            np.linalg.norm(self.embedding) * np.linalg.norm(other.embedding) + 1e-8
        ))


class LatentWorkingMemory:
    """Qdrant-backed working memory for latent collaboration.

    Stores agent thoughts as embeddings, enabling:
    - Semantic similarity search
    - Cross-agent context retrieval
    - Consensus computation via embedding interpolation

    This is the core component for LatentMAS-style collaboration.
    """

    def __init__(
        self,
        host: str = QDRANT_HOST,
        port: int = QDRANT_PORT,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initialize working memory.

        Args:
            host: Qdrant server host
            port: Qdrant server port
            collection_name: Qdrant collection name
        """
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self._client = None
        self._collection_created = False

    def _get_client(self):
        """Get or create Qdrant client."""
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(host=self.host, port=self.port)
        return self._client

    async def _ensure_collection(self) -> None:
        """Ensure collection exists with correct schema."""
        if self._collection_created:
            return

        from qdrant_client import models

        client = self._get_client()

        try:
            # Check if collection exists
            collections = client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)

            if not exists:
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=EMBEDDING_DIM,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {self.collection_name}")

            self._collection_created = True

        except Exception as e:
            logger.warning(f"Failed to ensure Qdrant collection: {e}")
            raise

    async def store(self, thought: LatentThought) -> str:
        """Store a thought in working memory.

        Args:
            thought: LatentThought to store

        Returns:
            ID of stored thought
        """
        await self._ensure_collection()

        from qdrant_client import models

        client = self._get_client()

        # Build payload
        payload = {
            "agent_role": thought.agent_role,
            "content_summary": thought.content_summary,
            "domain": thought.domain,
            "created_at": thought.created_at.isoformat(),
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

        logger.debug(f"Stored thought {thought.id} from {thought.agent_role}")
        return thought.id

    async def retrieve_similar(
        self,
        query_embedding: np.ndarray,
        limit: int = 5,
        threshold: float = 0.5,
        exclude_agent: str | None = None,
        domain: str | None = None,
    ) -> list[LatentThought]:
        """Retrieve similar thoughts from working memory.

        Args:
            query_embedding: 768-dim query vector
            limit: Maximum results to return
            threshold: Minimum similarity threshold
            exclude_agent: Agent role to exclude from results
            domain: Filter by domain

        Returns:
            List of similar LatentThoughts, sorted by similarity
        """
        await self._ensure_collection()

        from qdrant_client import models

        client = self._get_client()

        # Build filter
        must_conditions = []
        must_not_conditions = []

        if exclude_agent:
            must_not_conditions.append(
                models.FieldCondition(
                    key="agent_role",
                    match=models.MatchValue(value=exclude_agent),
                )
            )

        if domain:
            must_conditions.append(
                models.FieldCondition(
                    key="domain",
                    match=models.MatchValue(value=domain),
                )
            )

        query_filter = None
        if must_conditions or must_not_conditions:
            query_filter = models.Filter(
                must=must_conditions if must_conditions else None,
                must_not=must_not_conditions if must_not_conditions else None,
            )

        # Search
        results = client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding.tolist(),
            query_filter=query_filter,
            limit=limit,
            score_threshold=threshold,
        )

        # Convert to LatentThought objects
        thoughts = []
        for hit in results:
            payload = hit.payload or {}
            thoughts.append(LatentThought(
                id=str(hit.id),
                agent_role=payload.get("agent_role", ""),
                content_summary=payload.get("content_summary", ""),
                embedding=np.array(hit.vector) if hit.vector else np.zeros(EMBEDDING_DIM),
                domain=payload.get("domain", ""),
                created_at=datetime.fromisoformat(payload["created_at"]) if "created_at" in payload else datetime.now(),
                metadata={k: v for k, v in payload.items() if k not in ("agent_role", "content_summary", "domain", "created_at")},
            ))

        return thoughts

    async def get_consensus(self, domain: str, limit: int = 10) -> np.ndarray:
        """Compute consensus embedding for a domain.

        Computes the mean embedding of recent thoughts in the domain,
        representing a "consensus" latent representation.

        Args:
            domain: Domain to compute consensus for
            limit: Max thoughts to include

        Returns:
            768-dim consensus embedding
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
            with_vectors=True,
        )

        points = results[0]

        if not points:
            # Return zero vector if no thoughts
            return np.zeros(EMBEDDING_DIM)

        # Compute mean embedding
        embeddings = [np.array(p.vector) for p in points if p.vector]
        if not embeddings:
            return np.zeros(EMBEDDING_DIM)

        consensus = np.mean(embeddings, axis=0)

        # Normalize
        norm = np.linalg.norm(consensus)
        if norm > 0:
            consensus = consensus / norm

        return consensus

    async def clear_domain(self, domain: str) -> int:
        """Clear all thoughts for a domain.

        Args:
            domain: Domain to clear

        Returns:
            Number of thoughts deleted
        """
        await self._ensure_collection()

        from qdrant_client import models

        client = self._get_client()

        # First count how many will be deleted
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
            limit=1000,
            with_vectors=False,
        )
        count = len(results[0])

        # Delete points
        client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="domain",
                            match=models.MatchValue(value=domain),
                        )
                    ]
                )
            ),
        )

        logger.info(f"Cleared {count} thoughts for domain: {domain}")
        return count

    async def get_stats(self) -> dict:
        """Get working memory statistics.

        Returns:
            Dict with count, domains, etc.
        """
        await self._ensure_collection()

        client = self._get_client()

        try:
            info = client.get_collection(self.collection_name)
            return {
                "collection": self.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "indexed_vectors_count": info.indexed_vectors_count,
                "status": info.status.value if info.status else "unknown",
            }
        except Exception as e:
            return {"error": str(e)}


# Module-level singleton
_latent_memory: LatentWorkingMemory | None = None


def get_latent_memory() -> LatentWorkingMemory:
    """Get or create latent memory singleton."""
    global _latent_memory
    if _latent_memory is None:
        _latent_memory = LatentWorkingMemory()
    return _latent_memory
