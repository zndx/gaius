"""Latent collaboration module for LatentMAS-style agent communication.

Provides Qdrant-backed working memory for sharing embeddings between agents,
enabling latent-space collaboration with 70-90% token reduction.

Includes CLT-enhanced memory for interpretable sparse feature collaboration
using Cross-Layer Transcoders from BluelightAI.

The CLT projection bridge enables agents to be positioned in the same
semantic space as KB documents, projecting sparse features to ColNomic
embeddings for unified grid visualization.

Usage:
    # Standard latent memory (Nomic embeddings)
    from gaius.agents.latent import LatentWorkingMemory, LatentThought

    memory = LatentWorkingMemory()
    await memory.store(thought)
    similar = await memory.retrieve_similar(query_embedding)

    # CLT-enhanced memory (sparse features)
    from gaius.agents.latent import CLTLatentMemory, CLTLatentThought

    clt_memory = CLTLatentMemory()
    thought = await clt_memory.store_from_content("leader", "analysis...")
    consensus = await clt_memory.compute_feature_consensus("domain")

    # CLT→ColNomic projection for grid positioning
    from gaius.agents.latent import get_clt_projection_bridge, get_trace_embedder

    bridge = get_clt_projection_bridge()
    embedding = bridge.project_sparse_features(features)
    grid_pos = bridge.project_to_grid(features, projector)
"""

from .memory import (
    LatentThought,
    LatentWorkingMemory,
    get_latent_memory,
)
from .clt_memory import (
    CLTLatentThought,
    CLTLatentMemory,
    SparseFeatureSet,
    get_clt_memory,
)
from .clt_projection import (
    CLTProjectionBridge,
    TraceState,
    TraceEmbedder,
    AgentStateDecoder,
    get_clt_projection_bridge,
    get_trace_embedder,
    get_agent_state_decoder,
    CLT_FEATURE_DIM,
    COLNOMIC_DIM,
)

__all__ = [
    # Standard latent memory
    "LatentThought",
    "LatentWorkingMemory",
    "get_latent_memory",
    # CLT-enhanced memory
    "CLTLatentThought",
    "CLTLatentMemory",
    "SparseFeatureSet",
    "get_clt_memory",
    # CLT→ColNomic projection bridge
    "CLTProjectionBridge",
    "TraceState",
    "TraceEmbedder",
    "get_clt_projection_bridge",
    "get_trace_embedder",
    "CLT_FEATURE_DIM",
    "COLNOMIC_DIM",
    # Agent state decoder (bidirectional channel)
    "AgentStateDecoder",
    "get_agent_state_decoder",
]
