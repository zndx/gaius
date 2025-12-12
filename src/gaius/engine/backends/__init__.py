"""Inference backend controllers (optillm, vLLM, embeddings, ColPali)."""

from .backend_router import (
    BackendRouter,
    InferenceRequest,
    InferenceResponse,
)
from .colpali_controller import (
    ColPaliController,
    ColPaliEndpoint,
    ColPaliRequest,
    ColPaliResponse,
    ColPaliStatus,
    get_colpali_controller,
)
from .embedding_controller import (
    EmbeddingController,
    EmbeddingEndpoint,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingStatus,
    get_embedding_controller,
)
from .optillm_controller import (
    OptillmController,
    OptillmRequest,
    OptillmResponse,
    OptillmTechnique,
)
from .vllm_controller import (
    ProcessStatus,
    VLLMController,
    VLLMProcess,
    VLLMRequest,
    VLLMResponse,
)

__all__ = [
    # Backend Router
    "BackendRouter",
    "InferenceRequest",
    "InferenceResponse",
    # ColPali (multi-vector embeddings)
    "ColPaliController",
    "ColPaliEndpoint",
    "ColPaliRequest",
    "ColPaliResponse",
    "ColPaliStatus",
    "get_colpali_controller",
    # Embedding (single-vector)
    "EmbeddingController",
    "EmbeddingEndpoint",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingStatus",
    "get_embedding_controller",
    # optillm
    "OptillmController",
    "OptillmRequest",
    "OptillmResponse",
    "OptillmTechnique",
    # vLLM
    "ProcessStatus",
    "VLLMController",
    "VLLMProcess",
    "VLLMRequest",
    "VLLMResponse",
]
