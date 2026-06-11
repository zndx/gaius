"""Tests for ACP agent selection (acp.agent config key / GAIUS_ACP_AGENT).

Covers the registry that lets Gaius spawn either Mistral Vibe (vibe-acp
adapter) or xAI Grok (native ACP via `grok agent stdio`) as the ACP agent.
"""

import shutil
from pathlib import Path

import pytest

from gaius.acp import (
    ACP_AGENT_KEYS,
    ACPConfig,
    ACPConnectionError,
    load_acp_agent_selection,
    resolve_acp_agent,
)
from gaius.acp.attribution import get_model_attribution


def test_default_agent_is_vibe(monkeypatch):
    """With no env override and no config key, default is vibe."""
    monkeypatch.delenv("GAIUS_ACP_AGENT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent"))
    monkeypatch.setattr(Path, "cwd", lambda: Path("/nonexistent"))
    assert load_acp_agent_selection() == "vibe"


def test_env_override(monkeypatch):
    monkeypatch.setenv("GAIUS_ACP_AGENT", "grok")
    assert load_acp_agent_selection() == "grok"


def test_unknown_agent_fails_fast(monkeypatch):
    monkeypatch.setenv("GAIUS_ACP_AGENT", "claude")
    with pytest.raises(ACPConnectionError, match="ACP.00000011.BADAGENT"):
        load_acp_agent_selection()


def test_vibe_resolution():
    command, args = resolve_acp_agent("vibe")
    assert command  # vibe-acp path or uvx fallback
    if command == "uvx":
        assert args == ["--from", "mistral-vibe", "vibe-acp"]


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_grok_resolution(monkeypatch):
    """grok resolves to `grok agent stdio` when credentials exist."""
    if not (Path.home() / ".grok/auth.json").exists():
        monkeypatch.setenv("XAI_API_KEY", "test-key")
    command, args = resolve_acp_agent("grok")
    assert command.endswith("grok")
    assert args == ["agent", "stdio"]


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_grok_without_credentials_fails_fast(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent"))
    with pytest.raises(ACPConnectionError, match="ACP.00000013.GROKAUTH"):
        resolve_acp_agent("grok")


def test_acp_config_explicit_command_respected(monkeypatch):
    """Explicit agent_command bypasses registry resolution."""
    monkeypatch.delenv("GAIUS_ACP_AGENT", raising=False)
    config = ACPConfig(agent="vibe", agent_command="/usr/bin/custom-acp")
    assert config.agent_command == "/usr/bin/custom-acp"
    assert config.agent_args == []


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_acp_config_grok_agent(monkeypatch):
    if not (Path.home() / ".grok/auth.json").exists():
        monkeypatch.setenv("XAI_API_KEY", "test-key")
    config = ACPConfig(agent="grok")
    assert config.agent_command.endswith("grok")
    assert config.agent_args == ["agent", "stdio"]


def test_registry_keys_have_attribution():
    """Every registry agent maps to a non-default attribution."""
    assert get_model_attribution("vibe-acp").name == "Mistral"
    assert get_model_attribution("grok").name == "Grok"
    assert "grok" not in ACP_AGENT_KEYS or get_model_attribution("grok").url
