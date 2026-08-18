"""Tests for ACP agent selection (acp.agent config key / GAIUS_ACP_AGENT).

Roster is grok-build on local thinking (default) and grok-build with a
Grok subscription (escalate). Mistral / vibe is not on the roster.
"""

import shutil
from pathlib import Path

import pytest

from gaius.acp import (
    ACP_AGENT_KEYS,
    DEFAULT_ACP_AGENT,
    ACPConfig,
    ACPConnectionError,
    load_acp_agent_selection,
    resolve_acp_agent,
    write_thinking_grok_home,
)
from gaius.acp.attribution import get_model_attribution


def test_default_agent_is_thinking(monkeypatch):
    """With no env override and no config key, default is thinking."""
    monkeypatch.delenv("GAIUS_ACP_AGENT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent"))
    monkeypatch.setattr(Path, "cwd", lambda: Path("/nonexistent"))
    assert load_acp_agent_selection() == "thinking"
    assert DEFAULT_ACP_AGENT == "thinking"


def test_env_override(monkeypatch):
    monkeypatch.setenv("GAIUS_ACP_AGENT", "grok")
    assert load_acp_agent_selection() == "grok"


def test_unknown_agent_fails_fast(monkeypatch):
    monkeypatch.setenv("GAIUS_ACP_AGENT", "claude")
    with pytest.raises(ACPConnectionError, match="ACP.00000011.BADAGENT"):
        load_acp_agent_selection()


def test_vibe_is_off_the_roster(monkeypatch):
    monkeypatch.setenv("GAIUS_ACP_AGENT", "vibe")
    with pytest.raises(ACPConnectionError, match="ACP.00000011.BADAGENT"):
        load_acp_agent_selection()
    assert "vibe" not in ACP_AGENT_KEYS


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_thinking_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIUS_ACP_GROK_HOME", str(tmp_path))
    command, args = resolve_acp_agent("thinking")
    assert command.endswith("grok")
    assert args == ["agent", "--always-approve", "--model", "gaius-thinking", "stdio"]
    cfg = (tmp_path / "config.toml").read_text()
    assert "[model.gaius-thinking]" in cfg
    assert "base_url" in cfg


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_grok_resolution(monkeypatch):
    """grok resolves to subscription grok-build when credentials exist."""
    if not (Path.home() / ".grok/auth.json").exists():
        monkeypatch.setenv("XAI_API_KEY", "test-key")
    command, args = resolve_acp_agent("grok")
    assert command.endswith("grok")
    assert args == ["agent", "--always-approve", "--model", "grok-build", "stdio"]


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_grok_without_credentials_fails_fast(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent"))
    with pytest.raises(ACPConnectionError, match="ACP.00000013.GROKAUTH"):
        resolve_acp_agent("grok")


def test_acp_config_explicit_command_respected(monkeypatch):
    """Explicit agent_command bypasses registry resolution."""
    monkeypatch.delenv("GAIUS_ACP_AGENT", raising=False)
    config = ACPConfig(agent="thinking", agent_command="/usr/bin/custom-acp")
    assert config.agent_command == "/usr/bin/custom-acp"
    assert config.agent_args == []


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_acp_config_grok_agent(monkeypatch):
    if not (Path.home() / ".grok/auth.json").exists():
        monkeypatch.setenv("XAI_API_KEY", "test-key")
    config = ACPConfig(agent="grok")
    assert config.agent_command.endswith("grok")
    assert config.agent_args == ["agent", "--always-approve", "--model", "grok-build", "stdio"]


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_acp_config_thinking_sets_grok_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIUS_ACP_GROK_HOME", str(tmp_path))
    config = ACPConfig(agent="thinking")
    assert config.agent_env["GROK_HOME"] == str(tmp_path)
    assert (tmp_path / "config.toml").is_file()


def test_write_thinking_home_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIUS_UI_BIND", "0.0.0.0:9890")
    home = write_thinking_grok_home(tmp_path)
    text = (home / "config.toml").read_text()
    assert "http://127.0.0.1:9890/v1" in text


def test_registry_keys_have_attribution():
    """Every roster agent maps to a non-default attribution."""
    assert get_model_attribution("thinking").name == "Qwen3.8-27B"
    assert get_model_attribution("grok").name == "Grok"
    assert "grok" not in ACP_AGENT_KEYS or get_model_attribution("grok").url
