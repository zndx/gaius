"""Inference backend controllers (optillm, vLLM, exo/MLX, embeddings, ColPali)."""

from .backend_router import (
    BackendRouter,
    InferenceRequest,
    InferenceResponse,
)
# ColPali and Embedding controllers are lazy-loaded to avoid heavy transformers import at startup
# Use: from gaius.engine.backends.colpali_controller import ColPaliController
# Or just access gaius.engine.backends.ColPaliController (uses __getattr__ below)
from .exo_controller import (
    ExoController,
    ExoEndpointInfo,
    ExoRequest,
    ExoResponse,
    ExoStatus,
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
    # Exo/MLX (Apple Silicon)
    "ExoController",
    "ExoEndpointInfo",
    "ExoRequest",
    "ExoResponse",
    "ExoStatus",
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


# Lazy loading for ColPali and Embedding controllers (avoids heavy transformers import at startup)
_COLPALI_NAMES = {
    "ColPaliController", "ColPaliEndpoint", "ColPaliRequest",
    "ColPaliResponse", "ColPaliStatus", "get_colpali_controller",
}
_EMBEDDING_NAMES = {
    "EmbeddingController", "EmbeddingEndpoint", "EmbeddingRequest",
    "EmbeddingResponse", "EmbeddingStatus", "get_embedding_controller",
}


def __getattr__(name: str):
    """Lazy-load ColPali and Embedding controller components on first access."""
    if name in _COLPALI_NAMES:
        from .colpali_controller import (
            ColPaliController,
            ColPaliEndpoint,
            ColPaliRequest,
            ColPaliResponse,
            ColPaliStatus,
            get_colpali_controller,
        )
        return {
            "ColPaliController": ColPaliController,
            "ColPaliEndpoint": ColPaliEndpoint,
            "ColPaliRequest": ColPaliRequest,
            "ColPaliResponse": ColPaliResponse,
            "ColPaliStatus": ColPaliStatus,
            "get_colpali_controller": get_colpali_controller,
        }[name]
    if name in _EMBEDDING_NAMES:
        from .embedding_controller import (
            EmbeddingController,
            EmbeddingEndpoint,
            EmbeddingRequest,
            EmbeddingResponse,
            EmbeddingStatus,
            get_embedding_controller,
        )
        return {
            "EmbeddingController": EmbeddingController,
            "EmbeddingEndpoint": EmbeddingEndpoint,
            "EmbeddingRequest": EmbeddingRequest,
            "EmbeddingResponse": EmbeddingResponse,
            "EmbeddingStatus": EmbeddingStatus,
            "get_embedding_controller": get_embedding_controller,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
