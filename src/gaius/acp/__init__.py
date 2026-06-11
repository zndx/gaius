"""Agent Client Protocol (ACP) integration for Gaius.

Provides ACP client for connecting to Mistral Vibe via the vibe-acp adapter,
enabling autonomous health maintenance and complex task delegation.

ACP (Agent Client Protocol) is JSON-RPC 2.0 over stdio, standardizing:
- Where the agent lives in your workflow (unlike MCP which covers data/tools access)
- Bidirectional communication between clients and AI agents

Supported agents: Mistral Vibe, Gemini CLI, OpenHands, Goose
Supported clients: Zed, Neovim, Toad (Textual-based TUI)

Usage:
    from gaius.acp import GaiusACPClient

    async with GaiusACPClient() as client:
        response = await client.prompt("Analyze health report and suggest fixes")
        print(response)
"""

from .client import (
    GaiusACPClient,
    ACPConnectionError,
    ACPRateLimitError,
    ACPConfig,
    StreamCallback,
    _find_acp_adapter,
    load_acp_agent_selection,
    resolve_acp_agent,
    ACP_AGENT_KEYS,
)
from .prompts import (
    WorkflowMode,
    CadencePolicy,
    build_system_prompt,
    build_incident_prompt,
    build_rca_prompt,
    format_rca_observations,
    format_rca_constraint_violations,
    format_issue_body,
    ISSUE_BODY_TEMPLATE,
    ISSUE_UPDATE_TEMPLATE,
    ISSUE_RESOLUTION_TEMPLATE,
    SYSTEM_PROMPT_RCA,
    RCA_ISSUE_BODY_TEMPLATE,
)
from .attribution import (
    ModelAttribution,
    get_model_attribution,
    MODEL_ATTRIBUTION_MAP,
    DEFAULT_ATTRIBUTION,
)
from .security import (
    GitHubSecurityError,
    RepositoryNotAllowedError,
    RepositoryNotPrivateError,
    RepositoryNotConfiguredError,
    GitHubSecurityConfig,
    GitHubSecurityGuard,
    load_security_config,
    sanitize_issue_content,
    validate_issue_title,
)
from .constraint_vocab import (
    CPSATConstraint,
    EnforcementMode,
    CPSAT_CONSTRAINTS,
    FAILURE_MODE_CONSTRAINTS,
    get_constraints_for_failure_mode,
    format_constraints_table,
    get_constraint_by_id,
    get_design_principles,
)

__all__ = [
    # Client
    "GaiusACPClient",
    "ACPConnectionError",
    "ACPRateLimitError",
    "ACPConfig",
    "StreamCallback",
    "_find_acp_adapter",
    "load_acp_agent_selection",
    "resolve_acp_agent",
    "ACP_AGENT_KEYS",
    # Prompts
    "WorkflowMode",
    "CadencePolicy",
    "build_system_prompt",
    "build_incident_prompt",
    "build_rca_prompt",
    "format_rca_observations",
    "format_rca_constraint_violations",
    "format_issue_body",
    "ISSUE_BODY_TEMPLATE",
    "ISSUE_UPDATE_TEMPLATE",
    "ISSUE_RESOLUTION_TEMPLATE",
    "SYSTEM_PROMPT_RCA",
    "RCA_ISSUE_BODY_TEMPLATE",
    # Attribution
    "ModelAttribution",
    "get_model_attribution",
    "MODEL_ATTRIBUTION_MAP",
    "DEFAULT_ATTRIBUTION",
    # Security
    "GitHubSecurityError",
    "RepositoryNotAllowedError",
    "RepositoryNotPrivateError",
    "RepositoryNotConfiguredError",
    "GitHubSecurityConfig",
    "GitHubSecurityGuard",
    "load_security_config",
    "sanitize_issue_content",
    "validate_issue_title",
    # Constraint Vocabulary (RCA)
    "CPSATConstraint",
    "EnforcementMode",
    "CPSAT_CONSTRAINTS",
    "FAILURE_MODE_CONSTRAINTS",
    "get_constraints_for_failure_mode",
    "format_constraints_table",
    "get_constraint_by_id",
    "get_design_principles",
]
