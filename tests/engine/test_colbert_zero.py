"""ColBERT-Zero replaces ColPali; text MaxSim only."""

from __future__ import annotations

import numpy as np
import pytest

from gaius.engine.config import load_config
from gaius.inference.search.colbert import (
    ColBERTVisionError,
    GURU_NOVISION,
    _as_token_matrix,
)
from gaius.inference.search.colqwen import get_colqwen_embedder


def test_token_matrix_shape() -> None:
    m = _as_token_matrix([[0.1, 0.2], [0.3, 0.4]])
    assert m.shape == (2, 2)
    assert _as_token_matrix([1.0, 2.0]).shape == (1, 2)


def test_image_fail_fast() -> None:
    from gaius.inference.search.colbert import ColBERTZeroEmbedder

    emb = ColBERTZeroEmbedder.__new__(ColBERTZeroEmbedder)
    with pytest.raises(ColBERTVisionError, match=GURU_NOVISION):
        emb.encode_image(object())


def test_colnomic_request_retired() -> None:
    with pytest.raises(RuntimeError, match="RETIRED"):
        get_colqwen_embedder(model_name="nomic-ai/colnomic-embed-multimodal-7b")


def test_agents_conf_embedding_is_colbert_zero() -> None:
    cfg = load_config()
    emb = cfg.agents["embedding"]
    assert emb.model == "lightonai/ColBERT-Zero"
    assert emb.backend == "colbert"
    assert emb.capabilities == ["open-embedding"]


def test_maxsim_identity() -> None:
    from gaius.inference.search.colbert import ColBERTZeroEmbedder

    e = ColBERTZeroEmbedder.__new__(ColBERTZeroEmbedder)
    q = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert e.compute_maxsim(q, q) == pytest.approx(2.0)


def test_colbert_singleton_pins_first_light_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gaius.inference.search.colbert import (
        get_colbert_embedder,
        reset_colbert_embedder,
    )

    picks = {"n": 0}

    def _pick() -> str:
        picks["n"] += 1
        return "cuda:4" if picks["n"] == 1 else "cuda:5"

    monkeypatch.setattr(
        "gaius.engine.sentinel_claim.embedding_cuda_device", _pick
    )
    reset_colbert_embedder()
    a = get_colbert_embedder()
    b = get_colbert_embedder()
    assert a is b
    assert a.device == "cuda:4"
    assert picks["n"] == 1
    reset_colbert_embedder()
