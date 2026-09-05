"""Cerebras panel stays available when a preferred model id is archived.

2026-09-05: zai-glm-4.7, qwen-3-32b and llama-3.3-70b were all archived
upstream (404 model_not_found on every "cerebras" card summary); the account's
live catalogue is gpt-oss-120b, qwen-3.8-27b, gemma-4-31b. The test pins the
SHAPE (a default plus non-empty fallbacks, all distinct, none of the archived
ids) rather than a catalogue that Cerebras rotates without notice.
"""

from gaius.engine.backends.external.cerebras_backend import CerebrasBackend

ARCHIVED = {"zai-glm-4.7", "glm-4.7", "qwen-3-32b", "llama-3.3-70b", "llama3.1-8b"}


def test_cerebras_keeps_fallback_models() -> None:
    # Same model as the local thinking lane, for like-for-like throughput tracking.
    assert CerebrasBackend.DEFAULT_MODEL == "qwen-3.8-27b"
    assert len(CerebrasBackend.FALLBACK_MODELS) >= 2
    assert CerebrasBackend.DEFAULT_MODEL not in CerebrasBackend.FALLBACK_MODELS
    assert len(set(CerebrasBackend.FALLBACK_MODELS)) == len(CerebrasBackend.FALLBACK_MODELS)


def test_cerebras_no_archived_ids() -> None:
    live = {CerebrasBackend.DEFAULT_MODEL, *CerebrasBackend.FALLBACK_MODELS}
    assert not (live & ARCHIVED), f"archived Cerebras ids still configured: {live & ARCHIVED}"
