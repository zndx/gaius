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
    OLMO3_32B_THINK,
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


def test_registry_registers_qwen() -> None:
    spec = get_model_registry().get("Qwen/Qwen3.8-27B")
    assert spec is not None
    assert spec.capability_labels()[0] == "thinking"
