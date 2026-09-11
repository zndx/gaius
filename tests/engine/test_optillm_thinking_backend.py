"""optillm's vLLM backend is thinking :8081, not vestigial instruct :8082."""

from gaius.engine.config import OptillmConfig


def test_optillm_backend_defaults_to_thinking_not_instruct_http():
    cfg = OptillmConfig()
    assert ":8081" in cfg.backend_url
    assert ":8082" not in cfg.backend_url
