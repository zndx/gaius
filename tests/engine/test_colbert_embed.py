import pytest

from gaius.engine.embeddings.colbert import (
    DEFAULT_MODEL,
    GURU_RETIRED,
    refuse_retired_embedding_model,
)


def test_refuse_retired_nomic_and_colpali_names() -> None:
    refuse_retired_embedding_model("")
    refuse_retired_embedding_model(None)
    refuse_retired_embedding_model(DEFAULT_MODEL)
    refuse_retired_embedding_model("colbert-zero")
    for name in (
        "nomic-ai/nomic-embed-text-v1",
        "nomic-ai/colnomic-embed-multimodal-7b",
        "vidore/colpali-v1.2",
        "vidore/colqwen2-v0.1",
    ):
        with pytest.raises(RuntimeError, match=GURU_RETIRED):
            refuse_retired_embedding_model(name)
