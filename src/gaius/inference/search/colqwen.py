"""ColQwen multimodal embedder for unified text+image embeddings.

Supports both ColQwen2 (colpali-engine 0.3.2) and ColQwen2_5 (0.3.5+):
- Multi-vector document embeddings (ColBERT-style late interaction)
- Unified text and image embedding space
- Safetensors only (no trust_remote_code needed)

Models:
- vidore/colqwen2-v0.1: 2B model, 128-dim, works with colpali-engine 0.3.2
- nomic-ai/colnomic-embed-multimodal-7b: 7B model, requires colpali-engine 0.3.5+

Usage:
    embedder = ColQwenEmbedder(
        model_name="vidore/colqwen2-v0.1",  # or "nomic-ai/colnomic-embed-multimodal-7b"
        aggregation="mean",  # For single-vector projection
    )

    # Text embedding
    multi_vecs, agg_vec = embedder.encode_text("Query about document")
    # multi_vecs: (n_tokens, 128), agg_vec: (128,)

    # Image embedding
    from PIL import Image
    img = Image.open("path/to/image.png")
    multi_vecs, agg_vec = embedder.encode_image(img)

    # Batch encoding
    results = embedder.encode_batch(["text query", img, "another text"])
"""

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


# Lazy imports to avoid loading ColQwen unless actually used
# We support both ColQwen2 (0.3.2) and ColQwen2_5 (0.3.5+)
_ColQwen2 = None
_ColQwen2Processor = None
_ColQwen2_5 = None
_ColQwen2_5_Processor = None
_COLPALI_VERSION = None


def _ensure_colpali_imports():
    """Lazy import colpali_engine with version detection."""
    global _ColQwen2, _ColQwen2Processor, _ColQwen2_5, _ColQwen2_5_Processor, _COLPALI_VERSION

    if _COLPALI_VERSION is not None:
        return  # Already imported

    try:
        import colpali_engine
        _COLPALI_VERSION = getattr(colpali_engine, "__version__", "0.3.0")

        # ColQwen2 is available in all versions
        from colpali_engine.models import ColQwen2, ColQwen2Processor
        _ColQwen2 = ColQwen2
        _ColQwen2Processor = ColQwen2Processor

        # ColQwen2_5 only available in 0.3.5+
        try:
            from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor
            _ColQwen2_5 = ColQwen2_5
            _ColQwen2_5_Processor = ColQwen2_5_Processor
        except ImportError:
            pass  # ColQwen2_5 not available in this version

    except ImportError as e:
        raise ImportError(
            "colpali-engine not installed. Install with: uv sync"
        ) from e


def _get_model_class(model_name: str):
    """Get appropriate ColQwen model and processor classes based on model name.

    Args:
        model_name: HuggingFace model ID

    Returns:
        Tuple of (ModelClass, ProcessorClass)
    """
    _ensure_colpali_imports()

    # Check if model requires ColQwen2_5
    is_qwen25_model = "qwen2.5" in model_name.lower() or "colnomic" in model_name.lower()

    if is_qwen25_model:
        if _ColQwen2_5 is None:
            raise ImportError(
                f"Model {model_name} requires ColQwen2_5 from colpali-engine>=0.3.5, "
                f"but you have version {_COLPALI_VERSION}. "
                f"Use 'vidore/colqwen2-v0.1' instead, or upgrade colpali-engine "
                f"(may conflict with vLLM)."
            )
        return _ColQwen2_5, _ColQwen2_5_Processor
    else:
        return _ColQwen2, _ColQwen2Processor


class AggregationMethod(str, Enum):
    """Method for aggregating multi-vectors to single vector."""

    MEAN = "mean"  # Average all token vectors (preserves semantic centroid)
    MAX = "max"  # Max pooling across tokens (emphasizes salient features)
    FIRST = "first"  # Use first token only (CLS token style)


@dataclass
class EmbeddingResult:
    """Result from encoding text or image."""

    multi_vectors: np.ndarray  # (n_tokens, hidden_dim) - for MaxSim search
    aggregated_vector: np.ndarray  # (hidden_dim,) - for UMAP/TDA projection
    source_type: str  # "text" or "image"
    metadata: dict[str, Any] | None = None


class ColQwenEmbedder:
    """Multi-vector embedder using ColQwen2 or ColQwen2.5.

    Stores both multi-vectors (for search quality) and aggregated single vectors
    (for grid projection and TDA).

    Supported models:
    - vidore/colqwen2-v0.1: 2B model, works with colpali-engine 0.3.2
    - nomic-ai/colnomic-embed-multimodal-7b: 7B model, requires colpali-engine 0.3.5+

    Architecture:
    - Output: Multiple 128-dim vectors per document (ColBERT-style)
    - Aggregation: Configurable (mean/max/first) for single-vector tasks

    Memory usage (vidore/colqwen2-v0.1):
    - fp32: ~4GB VRAM
    - bf16: ~2GB VRAM (recommended)
    """

    # Default to ColNomic multimodal embeddings model
    DEFAULT_MODEL = "nomic-ai/colnomic-embed-multimodal-7b"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        model_revision: str | None = None,
        aggregation: str | AggregationMethod = AggregationMethod.MEAN,
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
        dtype: torch.dtype = torch.bfloat16,  # bf16 for memory efficiency
        batch_size: int = 8,  # Larger batch ok for 2B model
    ):
        """Initialize ColQwen embedder.

        Args:
            model_name: HuggingFace model identifier
            model_revision: Pin to specific commit (None = latest)
            aggregation: Method for aggregating multi-vectors ("mean", "max", "first")
            device: Device to load model on ("cuda", "cpu")
            dtype: Model precision (bfloat16 recommended for GPU)
            batch_size: Default batch size for encoding
        """
        _ensure_colpali_imports()

        self.model_name = model_name
        self.model_revision = model_revision
        self.aggregation = (
            AggregationMethod(aggregation)
            if isinstance(aggregation, str)
            else aggregation
        )
        self.device = device
        self.dtype = dtype
        self.batch_size = batch_size

        # Get appropriate model and processor classes for this model
        self._model_class, self._processor_class = _get_model_class(model_name)

        # Lazy initialization
        self._model = None
        self._processor = None

    @property
    def model(self):
        """Get or create ColQwen model."""
        if self._model is None:
            kwargs = {"torch_dtype": self.dtype, "device_map": self.device}

            if self.model_revision:
                kwargs["revision"] = self.model_revision

            self._model = self._model_class.from_pretrained(self.model_name, **kwargs)
            self._model.eval()  # Inference mode

        return self._model

    @property
    def processor(self):
        """Get or create ColQwen processor."""
        if self._processor is None:
            kwargs = {}
            if self.model_revision:
                kwargs["revision"] = self.model_revision

            self._processor = self._processor_class.from_pretrained(
                self.model_name, **kwargs
            )

        return self._processor

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension (128 for ColQwen)."""
        return 128  # ColQwen2.5 hidden dimension

    def encode_text(
        self, text: str, prefix: str = "search_query: "
    ) -> tuple[np.ndarray, np.ndarray]:
        """Encode text to multi-vectors and aggregated single vector.

        Args:
            text: Text to embed
            prefix: Query prefix (ColQwen expects "search_query:" for queries)

        Returns:
            (multi_vectors, aggregated_vector)
            - multi_vectors: (n_tokens, 128) - for MaxSim search
            - aggregated_vector: (128,) - for UMAP/TDA
        """
        prefixed_text = prefix + text if prefix else text

        # Process text
        inputs = self.processor(text=[prefixed_text], return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Generate embeddings
        with torch.no_grad():
            outputs = self.model(**inputs)
            # outputs: (batch, n_tokens, hidden_dim)
            # Convert bfloat16 to float32 before numpy (bfloat16 not supported by numpy)
            multi_vecs = outputs[0].cpu().float().numpy()  # (n_tokens, 128)

        # Aggregate to single vector
        agg_vec = self._aggregate(multi_vecs)

        return multi_vecs, agg_vec

    def encode_image(self, image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
        """Encode image to multi-vectors and aggregated single vector.

        Args:
            image: PIL Image to embed

        Returns:
            (multi_vectors, aggregated_vector)
            - multi_vectors: (n_patches, 128) - for MaxSim search
            - aggregated_vector: (128,) - for UMAP/TDA
        """
        # Process image using the ColPali processor's process_images method
        inputs = self.processor.process_images([image])
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Generate embeddings
        with torch.no_grad():
            outputs = self.model(**inputs)
            # outputs: (batch, n_patches, hidden_dim)
            # Convert bfloat16 to float32 before numpy (bfloat16 not supported by numpy)
            multi_vecs = outputs[0].cpu().float().numpy()  # (n_patches, 128)

        # Aggregate to single vector
        agg_vec = self._aggregate(multi_vecs)

        return multi_vecs, agg_vec

    def encode_batch(
        self, items: list[str | Image.Image], prefixes: list[str] | None = None
    ) -> list[EmbeddingResult]:
        """Encode batch of mixed text and images.

        Args:
            items: List of texts (str) or images (PIL.Image)
            prefixes: Optional list of prefixes for text items

        Returns:
            List of EmbeddingResult with multi_vectors and aggregated_vector
        """
        results = []

        # Process in batches to manage memory
        for i in range(0, len(items), self.batch_size):
            batch = items[i : i + self.batch_size]
            batch_prefixes = (
                prefixes[i : i + self.batch_size] if prefixes else [None] * len(batch)
            )

            for item, prefix in zip(batch, batch_prefixes):
                if isinstance(item, str):
                    multi_vecs, agg_vec = self.encode_text(
                        item, prefix or "search_query: "
                    )
                    source_type = "text"
                elif isinstance(item, Image.Image):
                    multi_vecs, agg_vec = self.encode_image(item)
                    source_type = "image"
                else:
                    raise TypeError(
                        f"Unsupported item type: {type(item)}. Expected str or PIL.Image"
                    )

                results.append(
                    EmbeddingResult(
                        multi_vectors=multi_vecs,
                        aggregated_vector=agg_vec,
                        source_type=source_type,
                    )
                )

        return results

    def _aggregate(self, multi_vectors: np.ndarray) -> np.ndarray:
        """Aggregate multi-vectors to single vector.

        Args:
            multi_vectors: (n_tokens, hidden_dim)

        Returns:
            aggregated_vector: (hidden_dim,)
        """
        if self.aggregation == AggregationMethod.MEAN:
            # Mean pooling (preserves semantic centroid)
            agg = np.mean(multi_vectors, axis=0)
        elif self.aggregation == AggregationMethod.MAX:
            # Max pooling (emphasizes salient features)
            agg = np.max(multi_vectors, axis=0)
        elif self.aggregation == AggregationMethod.FIRST:
            # First token (CLS-style)
            agg = multi_vectors[0]
        else:
            raise ValueError(f"Unknown aggregation method: {self.aggregation}")

        # Normalize to unit length (for cosine similarity)
        agg_norm = np.linalg.norm(agg)
        if agg_norm > 0:
            agg = agg / agg_norm

        return agg

    def compute_maxsim(
        self, query_vecs: np.ndarray, doc_vecs: np.ndarray
    ) -> float:
        """Compute MaxSim score between query and document multi-vectors.

        MaxSim (maximum similarity) is the ColBERT late-interaction scoring:
        For each query token, find max similarity with any document token,
        then sum across query tokens.

        Args:
            query_vecs: (n_query_tokens, hidden_dim)
            doc_vecs: (n_doc_tokens, hidden_dim)

        Returns:
            MaxSim score (higher = more similar)
        """
        # Compute pairwise similarities: (n_query, n_doc)
        similarities = np.dot(query_vecs, doc_vecs.T)

        # For each query token, take max similarity with any doc token
        max_sims = np.max(similarities, axis=1)

        # Sum across query tokens
        maxsim_score = np.sum(max_sims)

        return maxsim_score


def load_image(path: Path | str) -> Image.Image:
    """Load image from file path.

    Args:
        path: Path to image file

    Returns:
        PIL Image in RGB mode
    """
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def extract_pdf_pages(pdf_path: Path | str) -> list[Image.Image]:
    """Extract pages from PDF as images.

    Args:
        pdf_path: Path to PDF file

    Returns:
        List of PIL Images (one per page)
    """
    try:
        import pypdf
    except ImportError as e:
        raise ImportError(
            "pypdf not installed. Install with: uv sync --extra multimodal"
        ) from e

    images = []
    pdf_path = Path(pdf_path)

    # TODO: Implement PDF to image conversion
    # pypdf doesn't directly extract rendered images, need to use pdf2image
    # or similar library. For now, raise NotImplementedError.
    raise NotImplementedError(
        "PDF page extraction not yet implemented. "
        "Consider using pdf2image or similar for rendering."
    )

    return images


# Module-level singleton
_embedder: ColQwenEmbedder | None = None


def get_colqwen_embedder(
    model_name: str | None = None,
    model_revision: str | None = None,
    aggregation: str | AggregationMethod = AggregationMethod.MEAN,
) -> ColQwenEmbedder:
    """Get or create ColQwen embedder singleton.

    Reads settings from config if available.

    Args:
        model_name: Override model name (None = use config or default)
        model_revision: Override model revision (None = use config)
        aggregation: Override aggregation method (None = use config)

    Returns:
        ColQwenEmbedder instance
    """
    global _embedder
    if _embedder is None:
        # Try to get settings from config
        try:
            from ...core.config import get_config

            config = get_config()
            mm_config = config.vector_store  # Will have multimodal settings

            if model_name is None:
                model_name = getattr(
                    mm_config, "multimodal_model", ColQwenEmbedder.DEFAULT_MODEL
                )
            if model_revision is None:
                model_revision = getattr(mm_config, "model_revision", None)
            if aggregation == AggregationMethod.MEAN:  # Default
                agg_str = getattr(mm_config, "aggregation", "mean")
                aggregation = AggregationMethod(agg_str)
        except Exception:
            # Use defaults if config not available
            if model_name is None:
                model_name = ColQwenEmbedder.DEFAULT_MODEL

        _embedder = ColQwenEmbedder(
            model_name=model_name,
            model_revision=model_revision,
            aggregation=aggregation,
        )

    return _embedder
