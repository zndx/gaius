"""ACP Client for connecting Gaius to grok-build.

This module provides the ACP (Agent Client Protocol) client that enables
Gaius to delegate complex reasoning tasks to grok-build for autonomous
health maintenance, diagnosis, and remediation.

Default agent is local thinking (Qwen3.8-27B via Engine/Complete).
Escalation is grok-build with a Grok subscription. Mistral is not on
the roster.

The client wraps the agent-client-protocol Python SDK to manage:
- Connection lifecycle (spawn, initialize, session management)
- Permission handling for filesystem and terminal operations
- Prompt/response communication with the agent

Architecture:
    Gaius (this client) → grok agent stdio → Engine/Complete (thinking)
                                    ↘ subscription grok-build (escalate)
                                    ↓
                            Gaius MCP Server (tools)

Usage:
    client = GaiusACPClient()
    await client.connect()

    response = await client.prompt(
        "Analyze this health report and recommend fixes",
        context={"report": health_report.to_dict()}
    )

    await client.close()
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Type alias for streaming callback
# Receives: (chunk_type: str, content: str)
# chunk_type is one of: "text", "tool_use", "thought", "status"
StreamCallback = Callable[[str, str], Awaitable[None]]


class ACPConnectionError(Exception):
    """Raised when ACP connection fails.

    Guru Meditation: #ACP.00000001.CONNFAIL
    """
    pass


class ACPRateLimitError(ACPConnectionError):
    """Rate limit hit during ACP session.

    Guru Meditation: #ACP.00000006.RATELIMIT

    This exception indicates the underlying model hit a rate limit.
    The client supports exponential backoff retry - callers should check
    `is_rate_limited()` after `prompt()` returns to detect mid-stream rate limits.
    """
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


# Roster: local thinking (default) and subscription grok-build (escalate).
# Selected via `acp.agent` in ~/.config/gaius/acp.conf or GAIUS_ACP_AGENT.
DEFAULT_ACP_AGENT = "thinking"
ACP_AGENT_KEYS = ("thinking", "grok")


def _repo_root() -> Path:
    for key in ("GAIUS_REPO_ROOT", "DEVENV_ROOT"):
        val = os.environ.get(key)
        if val:
            return Path(val)
    return Path.cwd()


def thinking_facade_url() -> str:
    """OpenAI-compatible base URL for Engine/Complete (gaius-ui :9890/v1)."""
    bind = (
        os.environ.get("GAIUS_PRIMARY_UI")
        or os.environ.get("GAIUS_UI_ORIGIN")
        or ""
    ).rstrip("/")
    if bind.startswith("http"):
        return f"{bind}/v1"
    raw = os.environ.get("GAIUS_UI_BIND", "127.0.0.1:9890")
    host, _, port = raw.rpartition(":")
    if not port:
        port = "9890"
        host = raw or "127.0.0.1"
    if host in ("0.0.0.0", "", "::", "[::]"):
        host = "127.0.0.1"
    return f"http://{host}:{port}/v1"


def write_thinking_grok_home(dest: Path | None = None) -> Path:
    """Write a GROK_HOME that aims grok-build at local thinking.

    Isolated from ~/.grok so the interactive TUI can stay on a
    subscription default. Override dest with GAIUS_ACP_GROK_HOME.
    """
    if dest is None:
        override = os.environ.get("GAIUS_ACP_GROK_HOME", "").strip()
        dest = Path(override) if override else _repo_root() / "build/dev/.gaius-acp-grok"
    dest.mkdir(parents=True, exist_ok=True)
    base = thinking_facade_url()
    toml = f"""
[models]
default = "gaius-thinking"
max_retries = 2

[agent]
system_prompt_label = "Qwen3.8-27B on Gaius Engine"

[model.gaius-thinking]
model = "thinking"
base_url = "{base}"
name = "Gaius thinking (Engine/Complete)"
api_key = "gaius"
api_backend = "chat_completions"
context_window = 262144
max_completion_tokens = 8192
max_retries = 2
system_prompt_label = "Qwen3.8-27B on Gaius Engine"

[ui]
permission_mode = "always-approve"

[features]
telemetry = false
remote_fetch = false
"""
    (dest / "config.toml").write_text(toml.lstrip(), encoding="utf-8")
    return dest


def acp_agent_environ(agent: str) -> dict[str, str]:
    """Extra env for the spawned ACP process (GROK_HOME for thinking)."""
    if agent == "thinking":
        return {"GROK_HOME": str(write_thinking_grok_home())}
    return {}


def _parse_acp_conf() -> Any | None:
    """Parse the first ACP HOCON config found on the standard search paths.

    Env-var substitutions (`${?VAR}`) resolve against the current process
    environment at parse time, so `.env` values (sourced into the engine by
    gaius-engine.sh) are picked up here. Returns None if no config file exists or
    pyhocon is unavailable.
    """
    candidates = [
        Path.home() / ".config/gaius/acp.conf",
        Path.home() / ".gaius/acp.conf",
        Path.cwd() / "config/acp.conf",
        Path.cwd() / ".gaius/acp.conf",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                from pyhocon import ConfigFactory

                return ConfigFactory.parse_file(str(candidate))
            except ImportError:
                logger.warning("pyhocon not installed; ACP HOCON config ignored")
            return None
    return None


def load_acp_agent_selection() -> str:
    """Load the configured ACP agent key.

    Precedence:
    1. GAIUS_ACP_AGENT environment variable
    2. `acp.agent` in the HOCON config (same search paths as security config)
    3. Default: "thinking" (grok-build on local Qwen3.8-27B)

    Returns:
        Agent key ("thinking" or "grok")

    Raises:
        ACPConnectionError: Unknown agent key.
        Guru Meditation: #ACP.00000011.BADAGENT
    """
    agent = os.environ.get("GAIUS_ACP_AGENT", "").strip().lower()

    if not agent:
        hocon = _parse_acp_conf()
        if hocon is not None:
            agent = str(hocon.get("acp.agent", "")).strip().lower()

    if not agent:
        agent = DEFAULT_ACP_AGENT

    if agent not in ACP_AGENT_KEYS:
        raise ACPConnectionError(
            f"Unknown ACP agent '{agent}' (#ACP.00000011.BADAGENT)\n"
            f"  Valid values: {', '.join(ACP_AGENT_KEYS)}\n"
            f"  thinking = grok-build on local Qwen3.8-27B (default)\n"
            f"  grok     = grok-build with Grok subscription (escalate)\n"
            f"  Set acp.agent in ~/.config/gaius/acp.conf or GAIUS_ACP_AGENT"
        )
    return agent


def _grok_bin() -> str:
    """Resolve the grok-build CLI path.

    The engine's systemd/process-compose PATH omits ~/.local/bin, so
    `shutil.which("grok")` fails there — every ACP escalation then died with
    #ACP.00000012.AGENTMISSING. Prefer an explicit path from `acp.grok_bin`
    (HOCON `${?GAIUS_GROK_BIN}`, sourced from .env by gaius-engine.sh), then the
    GAIUS_GROK_BIN env var directly, then PATH.
    """
    import shutil

    explicit = ""
    hocon = _parse_acp_conf()
    if hocon is not None:
        explicit = str(hocon.get("acp.grok_bin", "") or "").strip()
    if not explicit:
        explicit = os.environ.get("GAIUS_GROK_BIN", "").strip()

    if explicit:
        if os.path.isfile(explicit) and os.access(explicit, os.X_OK):
            return explicit
        raise ACPConnectionError(
            f"grok CLI configured but not an executable file: '{explicit}' "
            f"(#ACP.00000012.AGENTMISSING)\n"
            f"  Fix GAIUS_GROK_BIN (.env) / acp.grok_bin to point at the grok binary"
        )

    grok_cmd = shutil.which("grok")
    if grok_cmd:
        return grok_cmd
    raise ACPConnectionError(
        "grok CLI not found in PATH (#ACP.00000012.AGENTMISSING)\n"
        "  Install: https://docs.x.ai/grok-cli\n"
        "  Or set GAIUS_GROK_BIN=/path/to/grok in .env (surfaced via acp.grok_bin)"
    )


def resolve_acp_agent(agent: str) -> tuple[str, list[str]]:
    """Resolve an agent key to its spawn command and default args.

    Fail-fast: verifies the grok binary exists. Subscription grok also
    requires credentials (login token or XAI_API_KEY). Local thinking
    does not — it uses Engine/Complete via gaius-thinking.

    Args:
        agent: Agent key from ACP_AGENT_KEYS

    Returns:
        (command, default_args) to spawn the ACP agent over stdio

    Raises:
        ACPConnectionError: Agent binary missing, unknown key, or grok unauthenticated.
        Guru Meditations: #ACP.00000011.BADAGENT, #ACP.00000012.AGENTMISSING, #ACP.00000013.GROKAUTH
    """
    if agent == "thinking":
        write_thinking_grok_home()
        return _grok_bin(), [
            "agent",
            "--always-approve",
            "--model",
            "gaius-thinking",
            "stdio",
        ]

    if agent == "grok":
        grok_cmd = _grok_bin()
        # Subscription token (grok login) or API key must be present,
        # otherwise session/new fails with auth_required deep in the SDK.
        has_token = (Path.home() / ".grok/auth.json").exists()
        if not has_token and not os.environ.get("XAI_API_KEY"):
            raise ACPConnectionError(
                "grok CLI has no credentials (#ACP.00000013.GROKAUTH)\n"
                "  Subscription (QR-friendly): grok login --device-auth\n"
                "  Or API key: export XAI_API_KEY=...\n"
            )
        return grok_cmd, [
            "agent",
            "--always-approve",
            "--model",
            "grok-build",
            "stdio",
        ]

    raise ACPConnectionError(
        f"Unknown ACP agent '{agent}' (#ACP.00000011.BADAGENT)\n"
        f"  Valid values: {', '.join(ACP_AGENT_KEYS)}"
    )


@dataclass
class ACPConfig:
    """Configuration for ACP client.

    Requires the grok CLI (grok-build) in PATH.

    Attributes:
        agent: ACP agent key ("thinking" or "grok"). Empty = load from config
            (acp.agent in ~/.config/gaius/acp.conf, or GAIUS_ACP_AGENT env).
            Default is thinking (local Qwen3.8-27B). grok is subscription escalation.
        agent_command: Command to spawn the ACP agent. Empty = resolve from agent key
        agent_args: Arguments for the agent command
        agent_env: Extra environment for the spawned process (GROK_HOME for thinking)
        working_directory: Directory for agent operations
        connection_timeout: Seconds to wait for connection
        prompt_timeout: Seconds to wait for prompt response
        auto_approve_fs: Auto-approve filesystem operations
        auto_approve_terminal: Auto-approve terminal operations
        mcp_config: MCP server configuration for the agent to use
        include_gaius_mcp: Automatically include Gaius MCP server
        github_repo: GitHub repository for issue tracking (MUST be in allowlist)
        stream_callback: Optional async callback for streaming responses to TUI
        buffer_limit: Asyncio stream buffer limit in bytes (default 16MB for large files)
        security_config_path: Path to HOCON security config (None for auto-discovery)

    Security Note:
        GitHub security verification is MANDATORY and cannot be disabled.
        The github_repo must be in the allowlist at ~/.config/gaius/acp.conf
        and must have private visibility.
    """
    # Agent selection: "thinking" (grok-build + local Qwen3.8-27B) or
    # "grok" (grok-build + Grok subscription). Resolved in __post_init__
    # so explicit agent_command overrides still work.
    agent: str = ""
    agent_command: str = ""
    agent_args: list[str] | None = None
    agent_env: dict[str, str] = field(default_factory=dict)
    working_directory: str = field(default_factory=lambda: os.getcwd())
    connection_timeout: float = 30.0
    prompt_timeout: float | None = None  # None = no timeout, let the agent run to completion
    auto_approve_fs: bool = True  # Trust the agent with KB files
    auto_approve_terminal: bool = True  # Allow gh CLI for issue management
    mcp_config: dict[str, Any] | None = None  # Additional MCP servers
    include_gaius_mcp: bool = True  # Include Gaius MCP server in session
    github_repo: str = "zndx/gaius-acp"  # GitHub repo for issue tracking
    stream_callback: StreamCallback | None = None  # Streaming to TUI panel
    buffer_limit: int = 16 * 1024 * 1024  # 16MB buffer for large ACP agent responses
    security_config_path: Path | None = None  # HOCON config for GitHub security
    # NOTE: verify_github_security removed - security is MANDATORY, not optional

    def __post_init__(self) -> None:
        if not self.agent:
            self.agent = load_acp_agent_selection()
        if not self.agent_command:
            self.agent_command, default_args = resolve_acp_agent(self.agent)
            if self.agent_args is None:
                self.agent_args = default_args
        if self.agent_args is None:
            self.agent_args = []
        if not self.agent_env:
            self.agent_env = acp_agent_environ(self.agent)


class GaiusACPClient:
    """ACP client for connecting to grok-build.

    This client implements the Agent Client Protocol to communicate with
    grok-build, enabling Gaius to delegate complex tasks like:
    - Health report analysis and root cause diagnosis
    - Remediation planning and execution
    - GitHub issue creation and management

    Default inference is local thinking (Qwen3.8-27B via Engine/Complete).
    Pass ACPConfig(agent="grok") to escalate to a Grok subscription.

    The client handles permission requests for filesystem and terminal
    operations, with configurable auto-approval policies.

    Example:
        async with GaiusACPClient() as client:
            response = await client.prompt(
                "Analyze GPU health and suggest optimizations"
            )
    """

    def __init__(self, config: ACPConfig | None = None):
        """Initialize ACP client.

        Args:
            config: ACP configuration (uses defaults if None)
        """
        self.config = config or ACPConfig()
        self._connection = None
        self._process = None
        self._session_id: str | None = None
        self._connected = False
        self._last_activity: datetime | None = None
        self._context_manager = None
        self._gaius_client = None  # Reference to inner client for response extraction

        # Metrics
        self._prompts_sent = 0
        self._prompts_succeeded = 0
        self._total_latency_ms = 0

    @property
    def connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self._connection is not None

    @property
    def session_id(self) -> str | None:
        """Get current session ID."""
        return self._session_id

    async def connect(self) -> None:
        """Connect to grok-build via ACP.

        Spawns `grok agent stdio` and establishes an ACP session.
        Verifies GitHub repository security before connecting.

        Raises:
            ACPConnectionError: If connection fails
            GitHubSecurityError: If GitHub repository fails security checks
        """
        if self._connected:
            logger.warning("ACP client already connected")
            return

        # MANDATORY security check: verify GitHub repo before connecting
        # This check cannot be disabled - it prevents information leakage
        # and prompt injection attacks via public GitHub repos
        if self.config.github_repo:
            from .security import GitHubSecurityGuard

            try:
                guard = GitHubSecurityGuard.from_config(self.config.security_config_path)
                await guard.verify_repo(self.config.github_repo)
                logger.info(
                    f"GitHub security verified: {self.config.github_repo} is private and allowed"
                )
            except Exception as e:
                raise ACPConnectionError(
                    f"GitHub security check failed for {self.config.github_repo}.\n"
                    f"Ensure the repository is private and in your allowlist.\n"
                    f"Config file: ~/.config/gaius/acp.conf\n"
                    f"Guru Meditation: #ACP.00000010.GHSECFAIL\n"
                    f"Error: {e}"
                )

        try:
            # Import ACP SDK
            from acp import (
                Client,
                PROTOCOL_VERSION,
                spawn_agent_process,
                text_block,
            )
            from acp.schema import Implementation, McpServerStdio

            logger.info(f"Connecting to ACP agent: {self.config.agent_command}")

            # Import schema types for session updates
            from acp.schema import (
                AgentMessageChunk,
                AgentThoughtChunk,
                TextContentBlock,
                ToolCallStart,
                ToolCallUpdate,
                ToolCallProgress,
            )

            # Create custom client class with permission handlers
            class GaiusClient(Client):
                def __init__(self, parent: "GaiusACPClient"):
                    super().__init__()
                    self._parent = parent
                    # Buffer to accumulate response text from session updates
                    self._response_buffer: list[str] = []
                    # Rate limit detection state
                    self._rate_limit_detected: bool = False
                    self._rate_limit_message: str | None = None

                async def read_text_file(self, path: str, session_id: str, **kwargs) -> str | None:
                    """Handle filesystem read permission request."""
                    if self._parent.config.auto_approve_fs:
                        logger.debug(f"Auto-approved read: {path}")
                        try:
                            return Path(path).read_text()
                        except Exception as e:
                            logger.warning(f"Failed to read {path}: {e}")
                            return None
                    logger.warning(f"Denied read (auto_approve_fs=False): {path}")
                    return None

                async def write_text_file(self, path: str, content: str, session_id: str, **kwargs) -> bool:
                    """Handle filesystem write permission request."""
                    if self._parent.config.auto_approve_fs:
                        logger.debug(f"Auto-approved write: {path}")
                        try:
                            Path(path).parent.mkdir(parents=True, exist_ok=True)
                            Path(path).write_text(content)
                            return True
                        except Exception as e:
                            logger.warning(f"Failed to write {path}: {e}")
                            return False
                    logger.warning(f"Denied write (auto_approve_fs=False): {path}")
                    return False

                async def create_terminal(self, **kwargs) -> str | None:
                    """Handle terminal creation request."""
                    if self._parent.config.auto_approve_terminal:
                        logger.info("Auto-approved terminal creation")
                        return "terminal-1"  # Return terminal ID
                    logger.warning("Denied terminal creation (auto_approve_terminal=False)")
                    return None

                async def session_update(self, session_id: str, update, **kwargs) -> None:
                    """Handle session update notifications.

                    Streams updates to TUI panel via callback if configured,
                    and also buffers text for final response.

                    Chunk types streamed:
                    - "text": Agent message text chunks
                    - "thought": Agent thinking/reasoning chunks
                    - "tool_start": Tool call initiated
                    - "tool_progress": Tool execution progress
                    - "tool_update": Tool call result
                    """
                    logger.debug(f"Session update: {type(update).__name__}")
                    callback = self._parent.config.stream_callback

                    # Handle agent message chunks (the actual response text)
                    if isinstance(update, AgentMessageChunk):
                        if isinstance(update.content, TextContentBlock):
                            text = update.content.text
                            if text:
                                self._response_buffer.append(text)

                                # Check for rate limit error mid-stream
                                if "Error: API error from" in text and "Rate limit" in text:
                                    self._rate_limit_detected = True
                                    self._rate_limit_message = text
                                    logger.warning(f"Rate limit detected: {text[:100]}...")
                                    if callback:
                                        await callback("error", text)
                                elif callback:
                                    await callback("text", text)

                                logger.debug(f"Captured text chunk: {text[:50]}...")

                    # Handle agent thought chunks (reasoning/thinking)
                    elif isinstance(update, AgentThoughtChunk):
                        if hasattr(update, 'content') and isinstance(update.content, TextContentBlock):
                            text = update.content.text
                            if text and callback:
                                await callback("thought", text)
                            logger.debug(f"Thought chunk: {text[:50] if text else '(empty)'}...")

                    # Handle tool call start
                    elif isinstance(update, ToolCallStart):
                        tool_name = getattr(update, 'title', 'unknown')
                        if callback:
                            await callback("tool_start", f"[TOOL] {tool_name}")
                        logger.debug(f"Tool start: {tool_name}")

                    # Handle tool call progress
                    elif isinstance(update, ToolCallProgress):
                        progress = getattr(update, 'message', '')
                        if progress and callback:
                            await callback("tool_progress", progress)

                    # Handle tool call update (result)
                    elif isinstance(update, ToolCallUpdate):
                        # Tool results can be large, just note completion
                        if callback:
                            await callback("tool_update", "✓ Tool complete")

                def get_response(self) -> str:
                    """Get accumulated response and clear buffer."""
                    response = "".join(self._response_buffer)
                    self._response_buffer.clear()
                    return response

                def is_rate_limited(self) -> bool:
                    """Check if rate limit was detected during streaming."""
                    return self._rate_limit_detected

                def get_rate_limit_message(self) -> str | None:
                    """Get the rate limit error message if detected."""
                    return self._rate_limit_message

                def reset_rate_limit_state(self) -> None:
                    """Reset rate limit detection for retry."""
                    self._rate_limit_detected = False
                    self._rate_limit_message = None

            # Create client instance and store reference for response extraction
            gaius_client = GaiusClient(self)
            self._gaius_client = gaius_client

            # Build environment with MCP config if provided
            env = dict(os.environ)
            env.update(self.config.agent_env)

            if self.config.mcp_config:
                env["VIBE_MCP_CONFIG"] = json.dumps(self.config.mcp_config)

            # Spawn agent process with timeout and increased buffer limit
            async with asyncio.timeout(self.config.connection_timeout):
                # spawn_agent_process returns an async context manager
                # Pass buffer limit via transport_kwargs to handle large agent responses
                self._context_manager = spawn_agent_process(
                    gaius_client,
                    self.config.agent_command,
                    *(self.config.agent_args or []),
                    env=env,
                    cwd=self.config.working_directory,
                    transport_kwargs={"limit": self.config.buffer_limit},
                )
                self._connection, self._process = await self._context_manager.__aenter__()

                # Initialize the connection with protocol version
                await self._connection.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_info=Implementation(
                        name="gaius-health-observer",
                        version="0.1.0",
                    ),
                )

                # Build MCP servers list
                mcp_servers: list[McpServerStdio] = []

                # Include Gaius MCP server by default
                if self.config.include_gaius_mcp:
                    # Find the venv python for running gaius-mcp
                    venv_python = Path(self.config.working_directory) / ".devenv/state/venv/bin/python"
                    if not venv_python.exists():
                        # Fallback to uv run
                        mcp_servers.append(McpServerStdio(
                            name="gaius",
                            command="uv",
                            args=["run", "python", "-m", "gaius.mcp_server"],
                            cwd=self.config.working_directory,  # type: ignore[unknown-argument] - SDK stubs missing cwd kwarg
                            env=[],  # Empty list, not None
                        ))
                    else:
                        mcp_servers.append(McpServerStdio(
                            name="gaius",
                            command=str(venv_python),
                            args=["-m", "gaius.mcp_server"],
                            cwd=self.config.working_directory,  # type: ignore[unknown-argument] - SDK stubs missing cwd kwarg
                            env=[],  # Empty list, not None
                        ))
                    logger.info("Gaius MCP server configured for ACP session")

                # Add any additional configured MCP servers
                if self.config.mcp_config:
                    for name, cfg in self.config.mcp_config.items():
                        mcp_servers.append(McpServerStdio(
                            name=name,
                            command=cfg.get("command", ""),
                            args=cfg.get("args", []),
                            cwd=cfg.get("cwd"),  # type: ignore[unknown-argument] - SDK stubs missing cwd kwarg
                            env=cfg.get("env"),
                        ))

                # Create a new session with cwd and MCP servers
                session = await self._connection.new_session(
                    cwd=self.config.working_directory,
                    mcp_servers=mcp_servers,
                )
                self._session_id = session.session_id

            self._connected = True
            self._last_activity = datetime.now()
            logger.info(f"ACP connected, session_id={self._session_id}")

        except ImportError as e:
            raise ACPConnectionError(
                f"ACP SDK not available. Install with: pip install agent-client-protocol\n"
                f"Guru Meditation: #ACP.00000001.CONNFAIL\n"
                f"Error: {e}"
            )
        except asyncio.TimeoutError:
            raise ACPConnectionError(
                f"Connection timed out after {self.config.connection_timeout}s.\n"
                f"Guru Meditation: #ACP.00000002.TIMEOUT\n"
                f"Ensure grok CLI is in PATH and the selected agent can start.\n"
                f"  thinking: gaius-ui :9890 + Engine Complete capability=thinking\n"
                f"  grok:     grok login --device-auth (subscription escalation)"
            )
        except Exception as e:
            raise ACPConnectionError(
                f"Failed to connect to ACP agent ({self.config.agent}).\n"
                f"Guru Meditation: #ACP.00000001.CONNFAIL\n"
                f"Error: {e}"
            )

    async def prompt(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Send a prompt to the ACP agent and get response.

        Args:
            message: The prompt message
            context: Optional context dict to include
            timeout: Override default prompt timeout

        Returns:
            Response text from the agent

        Raises:
            ACPConnectionError: If not connected or prompt fails
        """
        if not self._connected:
            raise ACPConnectionError(
                "Not connected. Call connect() first.\n"
                "Guru Meditation: #ACP.00000003.NOTCONN"
            )

        # Connection is guaranteed to exist when _connected is True
        assert self._connection is not None

        try:
            from acp import text_block

            # Build prompt with context
            full_prompt = message
            if context:
                full_prompt = f"{message}\n\nContext:\n```json\n{json.dumps(context, indent=2)}\n```"

            start_time = datetime.now()
            self._prompts_sent += 1

            # Send prompt - no timeout by default, let the ACP agent run to completion
            # Response text comes via session_update callbacks, not the return value
            effective_timeout = timeout if timeout is not None else self.config.prompt_timeout

            if effective_timeout is not None:
                # With explicit timeout
                async with asyncio.timeout(effective_timeout):
                    await self._connection.prompt(
                        prompt=[text_block(full_prompt)],
                        session_id=self._session_id,
                    )
            else:
                # No timeout - let the ACP agent run until natural completion
                await self._connection.prompt(
                    prompt=[text_block(full_prompt)],
                    session_id=self._session_id,
                )

            # Extract text from accumulated session updates
            response_text = self._gaius_client.get_response() if self._gaius_client else ""

            # Update metrics
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            self._prompts_succeeded += 1
            self._total_latency_ms += latency_ms
            self._last_activity = datetime.now()

            logger.debug(f"Prompt completed in {latency_ms}ms")
            return response_text

        except asyncio.TimeoutError:
            raise ACPConnectionError(
                f"Prompt timed out after {effective_timeout}s.\n"
                f"Guru Meditation: #ACP.00000004.PROMPTTIMEOUT"
            )
        except Exception as e:
            raise ACPConnectionError(
                f"Prompt failed: {e}\n"
                f"Guru Meditation: #ACP.00000005.PROMPTFAIL"
            )

    def _extract_text(self, response) -> str:
        """Extract text content from ACP response.

        Args:
            response: ACP response object

        Returns:
            Extracted text content
        """
        # Response structure varies by implementation
        # Handle common formats
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for block in content:
                    if hasattr(block, "text"):
                        texts.append(block.text)
                    elif isinstance(block, dict) and "text" in block:
                        texts.append(block["text"])
                    elif isinstance(block, str):
                        texts.append(block)
                return "\n".join(texts)

        # Fallback: convert to string
        return str(response)

    async def close(self) -> None:
        """Close the ACP connection gracefully."""
        if not self._connected:
            return

        try:
            if self._context_manager:
                await self._context_manager.__aexit__(None, None, None)
        except Exception as e:
            logger.warning(f"Error closing ACP connection: {e}")
        finally:
            self._connected = False
            self._connection = None
            self._process = None
            self._session_id = None
            self._context_manager = None
            logger.info("ACP connection closed")

    def get_metrics(self) -> dict[str, Any]:
        """Get client metrics.

        Returns:
            Dict with prompts_sent, prompts_succeeded, avg_latency_ms, etc.
        """
        avg_latency = (
            self._total_latency_ms / self._prompts_succeeded
            if self._prompts_succeeded > 0
            else 0
        )

        return {
            "connected": self._connected,
            "session_id": self._session_id,
            "prompts_sent": self._prompts_sent,
            "prompts_succeeded": self._prompts_succeeded,
            "success_rate": (
                self._prompts_succeeded / self._prompts_sent
                if self._prompts_sent > 0
                else 0
            ),
            "avg_latency_ms": round(avg_latency, 2),
            "last_activity": (
                self._last_activity.isoformat()
                if self._last_activity
                else None
            ),
        }

    def is_rate_limited(self) -> bool:
        """Check if rate limit was detected during streaming.

        Call this after prompt() returns to check if the underlying model
        hit a rate limit. The response may still contain partial
        content before the error occurred.
        """
        return self._gaius_client.is_rate_limited() if self._gaius_client else False

    def get_rate_limit_message(self) -> str | None:
        """Get rate limit error message if detected."""
        return self._gaius_client.get_rate_limit_message() if self._gaius_client else None

    def reset_rate_limit_state(self) -> None:
        """Reset rate limit state for retry.

        Call this before retrying after a rate limit error.
        """
        if self._gaius_client:
            self._gaius_client.reset_rate_limit_state()

    async def __aenter__(self) -> "GaiusACPClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


# Module-level singleton for shared client
_acp_client: GaiusACPClient | None = None


async def get_acp_client(config: ACPConfig | None = None) -> GaiusACPClient:
    """Get or create ACP client singleton.

    Args:
        config: Optional config (only used on first call)

    Returns:
        Connected GaiusACPClient instance
    """
    global _acp_client

    if _acp_client is None:
        _acp_client = GaiusACPClient(config)

    if not _acp_client.connected:
        await _acp_client.connect()

    return _acp_client


async def close_acp_client() -> None:
    """Close the global ACP client if open."""
    global _acp_client

    if _acp_client is not None:
        await _acp_client.close()
        _acp_client = None
