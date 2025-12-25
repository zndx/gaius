"""Agent Client Protocol (ACP) integration for Gaius.

Provides ACP client for connecting to Claude Code via the claude-code-acp adapter,
enabling autonomous health maintenance and complex task delegation.

ACP (Agent Client Protocol) is JSON-RPC 2.0 over stdio, standardizing:
- Where the agent lives in your workflow (unlike MCP which covers data/tools access)
- Bidirectional communication between clients and AI agents

Supported agents: Claude Code, Gemini CLI, OpenHands, Goose
Supported clients: Zed, Neovim, Toad (Textual-based TUI)

Usage:
    from gaius.acp import GaiusACPClient

    async with GaiusACPClient() as client:
        response = await client.prompt("Analyze health report and suggest fixes")
        print(response)
"""

from .client import GaiusACPClient, ACPConnectionError, ACPConfig, _find_acp_adapter
from .prompts import (
    WorkflowMode,
    CadencePolicy,
    build_system_prompt,
    build_incident_prompt,
    ISSUE_BODY_TEMPLATE,
    ISSUE_UPDATE_TEMPLATE,
    ISSUE_RESOLUTION_TEMPLATE,
)

__all__ = [
    # Client
    "GaiusACPClient",
    "ACPConnectionError",
    "ACPConfig",
    "_find_acp_adapter",
    # Prompts
    "WorkflowMode",
    "CadencePolicy",
    "build_system_prompt",
    "build_incident_prompt",
    "ISSUE_BODY_TEMPLATE",
    "ISSUE_UPDATE_TEMPLATE",
    "ISSUE_RESOLUTION_TEMPLATE",
]
