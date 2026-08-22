"""optillm binds a provided vLLM; it does not mint a second GPU claim."""

from gaius.engine.backends.optillm_controller import pids_listening_on_port
from gaius.engine.backends.vllm_controller import ProcessStatus, VLLMProcess


def test_healthy_generate_prefers_thinking() -> None:
    from gaius.engine.backends.vllm_controller import VLLMController

    ctrl = VLLMController.__new__(VLLMController)
    ctrl._processes = {
        "ask-agent": VLLMProcess(
            agent_alias="ask-agent",
            model="tiny",
            port=8083,
            gpu_ids=[5],
            status=ProcessStatus.HEALTHY,
        ),
        "thinking": VLLMProcess(
            agent_alias="thinking",
            model="qwen",
            port=8081,
            gpu_ids=[0, 1, 2, 3],
            status=ProcessStatus.HEALTHY,
        ),
        "embed": VLLMProcess(
            agent_alias="embed",
            model="nomic",
            port=8089,
            gpu_ids=[4],
            task="embed",
            status=ProcessStatus.HEALTHY,
        ),
    }
    urls = ctrl.healthy_generate_base_urls()
    assert urls[0] == ("thinking", "http://localhost:8081/v1")
    assert all(a != "embed" for a, _ in urls)


def test_pids_listening_type() -> None:
    assert isinstance(pids_listening_on_port(9), set)
