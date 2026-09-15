"""Engine-side embedding models (GPU forward passes live in the engine).

ColBERT-Zero (`gaius.engine.embeddings.colbert`) is the text embedder.
"""

from .colbert import ColBERTZeroEmbedder, get_colbert_embedder
from .colqwen import ColQwenEmbedder, get_colqwen_embedder

__all__ = [
    "ColBERTZeroEmbedder",
    "get_colbert_embedder",
    "ColQwenEmbedder",
    "get_colqwen_embedder",
]
