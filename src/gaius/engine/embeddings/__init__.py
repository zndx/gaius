"""Engine-side embedding models (GPU forward passes live in the engine).

ColQwen/ColNomic multi-vector and ColBERT-style embedders. These run model
forward passes on engine-managed GPUs and are consumed by engine services
(vector search, CLT SKOS aperture, ColPali controller) and engine-adjacent
flows.
"""

from .colbert import ColBERTZeroEmbedder, get_colbert_embedder
from .colqwen import ColQwenEmbedder, get_colqwen_embedder

__all__ = [
    "ColBERTZeroEmbedder",
    "get_colbert_embedder",
    "ColQwenEmbedder",
    "get_colqwen_embedder",
]
