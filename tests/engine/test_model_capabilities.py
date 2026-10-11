"""Ordered capability arrays: thinking first, vision next; Olmo is open-thinking."""

from __future__ import annotations

import pytest

from gaius.engine.config import (
    GURU_NOAGENT,
    UnknownAgentError,
    get_agent_by_alias,
    load_config,
    require_agent,
    resolve_agent_name,
)
from gaius.models.registry import (
    ModelCapability,
    QWEN38_27B,
    D3_FLASH,
    OLMO3_32B_THINK,
    TaskType,
    get_model_registry,
)


def test_qwen_capability_order() -> None:
    labels = QWEN38_27B.capability_labels()
    assert labels[0] == "thinking"
    assert labels[1] == "vision"
    assert ModelCapability.THINKING in QWEN38_27B.capabilities
    assert ModelCapability.VISION_LANGUAGE in QWEN38_27B.capabilities


def test_olmo_is_open_thinking() -> None:
    assert OLMO3_32B_THINK.capability_labels()[0] == "open-thinking"
    assert ModelCapability.OPEN_THINKING in OLMO3_32B_THINK.capabilities
    assert "open-thinking" in OLMO3_32B_THINK.tags


def test_agents_conf_thinking_is_primary() -> None:
    cfg = load_config()
    thinking = cfg.agents["thinking"]
    assert thinking.model == "Qwen/Qwen3.8-27B"
    assert thinking.capabilities[:2] == ["thinking", "vision"]
    assert thinking.resources.context_length == 262144
    assert thinking.endpoint is not None
    extra = thinking.endpoint.extra_args
    assert "--reasoning-parser" in extra
    assert "qwen3" in extra
    assert "--enable-auto-tool-choice" in extra
    assert "--tool-call-parser" in extra
    assert "qwen3_coder" in extra
    assert "--enable-prefix-caching" in extra
    assert "--default-chat-template-kwargs" in extra
    assert "instruct" not in cfg.agents
    assert get_agent_by_alias(cfg, "instruct") is thinking
    assert resolve_agent_name("instruct") == "thinking"
    key, agent = require_agent(cfg, "instruct")
    assert key == "thinking"
    assert agent is thinking
    ot = cfg.agents["open-thinking"]
    assert ot.alias == "open-thinking"
    assert ot.capabilities == ["open-thinking"]
    fast = cfg.agents["fast"]
    assert fast.model == "Qwen/Qwen3.8-27B"
    assert fast.capabilities[:2] == ["thinking", "vision"]
    assert cfg.startup.preload_endpoints == ["thinking"]
    assert "decisions" not in cfg.agents
    for alias, port in (("d3-flash-0", 8096), ("d3-flash-1", 8097)):
        flash = cfg.agents[alias]
        assert flash.alias == alias
        assert flash.model == "vllm-sr/d3-flash"
        assert flash.backend == "d3"
        assert flash.capabilities == ["decisions"]
        assert flash.resources.gpus == 1
        assert flash.endpoint is not None
        assert flash.endpoint.port == port
        assert flash.endpoint.extra_args == []


def test_registry_registers_qwen() -> None:
    spec = get_model_registry().get("Qwen/Qwen3.8-27B")
    assert spec is not None
    assert spec.capability_labels()[0] == "thinking"
    assert spec.vllm_config is not None
    assert spec.vllm_config.tool_call_parser == "qwen3_coder"
    assert spec.vllm_config.enable_auto_tool_choice is True
    flash = get_model_registry().get_for_task(TaskType.DECISIONS, require_local=True)
    assert flash is not None
    assert flash.model_id == "vllm-sr/d3-flash"
    assert flash.provider == "d3"
    assert flash.vllm_config is None
    assert flash.get_resource_requirements().num_gpus == 1
    assert D3_FLASH.capability_labels()[0] == "decisions"
    args = spec.vllm_config.to_cli_args()
    assert "--enable-auto-tool-choice" in args
    assert "--tool-call-parser=qwen3_coder" in args
