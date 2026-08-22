"""Cerebras panel stays available when the preferred GLM id is archived."""

from gaius.engine.backends.external.cerebras_backend import CerebrasBackend


def test_cerebras_keeps_fallback_models() -> None:
    assert CerebrasBackend.DEFAULT_MODEL == "zai-glm-4.7"
    assert "qwen-3-32b" in CerebrasBackend.FALLBACK_MODELS
    assert "llama-3.3-70b" in CerebrasBackend.FALLBACK_MODELS
