"""Latent collaboration module for LatentMAS-style agent communication.

Provides Qdrant-backed working memory for sharing embeddings between agents,
enabling latent-space collaboration with 70-90% token reduction.

Usage:
    from gaius.agents.latent import LatentWorkingMemory, LatentThought

    memory = LatentWorkingMemory()
    await memory.store(thought)
    similar = await memory.retrieve_similar(query_embedding)
"""

from .memory import (
    LatentThought,
    LatentWorkingMemory,
    get_latent_memory,
)

__all__ = [
    "LatentThought",
    "LatentWorkingMemory",
    "get_latent_memory",
]
