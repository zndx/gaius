"""ColBERT-Zero late-interaction embedder (replaces ColPali / ColNomic).

``lightonai/ColBERT-Zero`` is a fully open multi-vector model (Apache 2.0,
public Nomic-embed training mixture, training code released). Contrastive
pre-training is done in the multi-vector setting, not bolted on after a
dense stage.

Text only. Vision/PDF late-interaction is Qwen3.8 VL — not this model.
Prompt alignment is mandatory: ``prompt_name="query"`` / ``"document"``.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

GURU_NOVISION = "#EM.00000001.NOVISION"
GURU_NOPYLATE = "#EM.00000002.NOPYLATE"

DEFAULT_MODEL = "lightonai/ColBERT-Zero"
EMBEDDING_DIM = 128


class AggregationMethod(str, Enum):
    MEAN = "mean"
    MAX = "max"
    FIRST = "first"


class ColBERTVisionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            f"{GURU_NOVISION} ColBERT-Zero is text late-interaction. "
            "It does not embed images or PDFs. "
            "Use Qwen3.8-27B vision (thinking) for multimodal, then index text."
        )


def _ensure_pylate() -> None:
    try:
        import pylate  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            f"{GURU_NOPYLATE} pylate is required for ColBERT-Zero.\n"
            "  Try: uv sync\n"
            "  ColPali/colpali-engine is retired."
        ) from e


class ColBERTZeroEmbedder:
    """PyLate ColBERT-Zero: token vectors + MaxSim, 128-d."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        aggregation: str = "mean",
        batch_size: int = 16,
    ) -> None:
        _ensure_pylate()
        self.model_name = model_name
        if not (device or "").strip():
            from gaius.engine.sentinel_claim import embedding_cuda_device

            device = embedding_cuda_device()
        self.device = device
        self.aggregation = AggregationMethod(aggregation)
        self.batch_size = batch_size
        self._model: Any = None

    @property
    def embedding_dim(self) -> int:
        return EMBEDDING_DIM

    @property
    def model(self) -> Any:
        if self._model is None:
            from pylate import models

            logger.info("Loading ColBERT-Zero %s on %s", self.model_name, self.device)
            self._model = models.ColBERT(
                model_name_or_path=self.model_name,
                device=self.device,
            )
        return self._model

    def encode_text(
        self, text: str, prefix: str = "search_query: "
    ) -> tuple[np.ndarray, np.ndarray]:
        is_query = "query" in (prefix or "").lower()
        prompt_name = "query" if is_query else "document"
        with _infer_lock:
            raw = self.model.encode(
                [text],
                batch_size=1,
                is_query=is_query,
                prompt_name=prompt_name,
                show_progress_bar=False,
            )
        multi = _as_token_matrix(raw[0])
        return multi, self._aggregate(multi)

    def offset_mapping(self, text: str) -> list[tuple[int, int]]:
        """Tokenizer offsets. HuggingFace tokenizers is not thread-safe."""
        with _infer_lock:
            tok = self.model.tokenizer
            encoded = tok(
                text,
                truncation=False,
                return_offsets_mapping=True,
                add_special_tokens=False,
            )
        return list(encoded["offset_mapping"])

    def encode_image(self, image: object) -> tuple[np.ndarray, np.ndarray]:
        raise ColBERTVisionError()

    def encode_batch(
        self,
        items: list[object],
        prefixes: list[str] | None = None,
    ) -> list[Any]:
        from .colqwen import EmbeddingResult

        results: list[Any] = []
        for i, item in enumerate(items):
            if not isinstance(item, str):
                raise ColBERTVisionError()
            prefix = prefixes[i] if prefixes else "search_query: "
            multi, agg = self.encode_text(item, prefix)
            results.append(
                EmbeddingResult(
                    multi_vectors=multi,
                    aggregated_vector=agg,
                    source_type="text",
                )
            )
        return results

    def _aggregate(self, multi_vectors: np.ndarray) -> np.ndarray:
        if self.aggregation == AggregationMethod.MEAN:
            agg = np.mean(multi_vectors, axis=0)
        elif self.aggregation == AggregationMethod.MAX:
            agg = np.max(multi_vectors, axis=0)
        else:
            agg = multi_vectors[0]
        norm = np.linalg.norm(agg)
        if norm > 0:
            agg = agg / norm
        return agg

    def compute_maxsim(
        self, query_vecs: np.ndarray, doc_vecs: np.ndarray
    ) -> float:
        sims = query_vecs @ doc_vecs.T
        return float(np.sum(np.max(sims, axis=1)))


def _as_token_matrix(raw: object) -> np.ndarray:
    arr = np.asarray(raw, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim != 2:
        raise RuntimeError(
            f"ColBERT-Zero encode returned shape {arr.shape}; expected (tokens, dim)"
        )
    return arr


_embedder: ColBERTZeroEmbedder | None = None
_embedder_lock = threading.Lock()
_infer_lock = threading.Lock()


def get_colbert_embedder(
    model_name: str = DEFAULT_MODEL,
    device: str | None = None,
) -> ColBERTZeroEmbedder:
    """One light-profile ColBERT. Pin the GPU; do not reload per MaxSim window."""
    global _embedder
    with _embedder_lock:
        if _embedder is not None and _embedder.model_name == model_name:
            return _embedder
        from gaius.engine.sentinel_claim import embedding_cuda_device

        resolved = (device or "").strip() or embedding_cuda_device()
        _embedder = ColBERTZeroEmbedder(model_name=model_name, device=resolved)
        return _embedder


def reset_colbert_embedder() -> None:
    """Tests only."""
    global _embedder
    with _embedder_lock:
        _embedder = None
