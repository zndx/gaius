"""ACP Client for connecting Gaius to Claude Code.

This module provides the ACP (Agent Client Protocol) client that enables
Gaius to delegate complex reasoning tasks to Claude Code for autonomous
health maintenance, diagnosis, and remediation.

The client wraps the agent-client-protocol Python SDK to manage:
- Connection lifecycle (spawn, initialize, session management)
- Permission handling for filesystem and terminal operations
- Prompt/response communication with Claude Code

Architecture:
    Gaius (this client) → Claude Code (via ACP) → Anthropic API
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


def _find_acp_adapter() -> str:
    """Find the claude-code-acp adapter command.

    Looks for:
    1. Local node_modules/.bin/claude-code-acp (installed via npm install)
    2. Global claude-code-acp (installed via npm install -g)
    3. npx claude-code-acp as fallback

    Returns:
        Path to the adapter command
    """
    # Check local node_modules first (relative to project root)
    local_adapter = Path(__file__).parent.parent.parent.parent.parent / "node_modules/.bin/claude-code-acp"
    if local_adapter.exists():
        return str(local_adapter.resolve())  # Return absolute path

    # Check if globally available
    import shutil
    global_adapter = shutil.which("claude-code-acp")
    if global_adapter:
        return global_adapter

    # Fall back to npx (will download if needed)
    return "npx"


@dataclass
class ACPConfig:
    """Configuration for ACP client.

    Requires the claude-code-acp adapter:
        npm install @zed-industries/claude-code-acp

    Attributes:
        agent_command: Command to spawn the ACP adapter (claude-code-acp)
        agent_args: Arguments for the adapter
        working_directory: Directory for Claude Code operations
        connection_timeout: Seconds to wait for connection
        prompt_timeout: Seconds to wait for prompt response
        auto_approve_fs: Auto-approve filesystem operations
        auto_approve_terminal: Auto-approve terminal operations
        mcp_config: MCP server configuration for Claude Code to use
        include_gaius_mcp: Automatically include Gaius MCP server
        github_repo: GitHub repository for issue tracking
        stream_callback: Optional async callback for streaming responses to TUI
    """
    # claude-code-acp is the required adapter from Zed
    # See: https://github.com/zed-industries/claude-code-acp
    agent_command: str = field(default_factory=_find_acp_adapter)
    agent_args: list[str] = field(default_factory=lambda: ["@zed-industries/claude-code-acp"] if _find_acp_adapter() == "npx" else [])
    working_directory: str = field(default_factory=lambda: os.getcwd())
    connection_timeout: float = 30.0
    prompt_timeout: float = 300.0  # 5 minutes for complex operations
    auto_approve_fs: bool = True  # Trust Claude Code with KB files
    auto_approve_terminal: bool = True  # Allow gh CLI for issue management
    mcp_config: dict[str, Any] | None = None  # Additional MCP servers
    include_gaius_mcp: bool = True  # Include Gaius MCP server in session
    github_repo: str = "zndx/gaius-internal"  # GitHub repo for issue tracking
    stream_callback: StreamCallback | None = None  # Streaming to TUI panel


class GaiusACPClient:
    """ACP client for connecting to Claude Code.

    This client implements the Agent Client Protocol to communicate with
    Claude Code, enabling Gaius to delegate complex tasks like:
    - Health report analysis and root cause diagnosis
    - Remediation planning and execution
    - GitHub issue creation and management

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
        """Connect to Claude Code via ACP.

        Spawns Claude Code subprocess and establishes an ACP session.

        Raises:
            ACPConnectionError: If connection fails
        """
        if self._connected:
            logger.warning("ACP client already connected")
            return

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
                                if callback:
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
                            await callback("tool_start", f"⚙ {tool_name}")
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

            # Create client instance and store reference for response extraction
            gaius_client = GaiusClient(self)
            self._gaius_client = gaius_client

            # Build environment with MCP config if provided
            env = dict(os.environ)

            # IMPORTANT: Remove ANTHROPIC_API_KEY so Claude Code uses subscription auth
            # instead of trying to use API credits (which may have low balance)
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("CLAUDE_API_KEY", None)

            if self.config.mcp_config:
                # Configure Gaius MCP server for Claude Code
                env["CLAUDE_CODE_MCP_CONFIG"] = json.dumps(self.config.mcp_config)

            # Spawn agent process with timeout
            async with asyncio.timeout(self.config.connection_timeout):
                # spawn_agent_process returns an async context manager
                self._context_manager = spawn_agent_process(
                    gaius_client,
                    self.config.agent_command,
                    *self.config.agent_args,
                    env=env,
                    cwd=self.config.working_directory,
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
                            cwd=self.config.working_directory,
                            env=[],  # Empty list, not None
                        ))
                    else:
                        mcp_servers.append(McpServerStdio(
                            name="gaius",
                            command=str(venv_python),
                            args=["-m", "gaius.mcp_server"],
                            cwd=self.config.working_directory,
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
                            cwd=cfg.get("cwd"),
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
                f"Ensure Claude Code is installed: npm install -g @anthropic-ai/claude-code"
            )
        except Exception as e:
            raise ACPConnectionError(
                f"Failed to connect to Claude Code.\n"
                f"Guru Meditation: #ACP.00000001.CONNFAIL\n"
                f"Error: {e}"
            )

    async def prompt(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Send a prompt to Claude Code and get response.

        Args:
            message: The prompt message
            context: Optional context dict to include
            timeout: Override default prompt timeout

        Returns:
            Response text from Claude Code

        Raises:
            ACPConnectionError: If not connected or prompt fails
        """
        if not self._connected:
            raise ACPConnectionError(
                "Not connected. Call connect() first.\n"
                "Guru Meditation: #ACP.00000003.NOTCONN"
            )

        try:
            from acp import text_block

            # Build prompt with context
            full_prompt = message
            if context:
                full_prompt = f"{message}\n\nContext:\n```json\n{json.dumps(context, indent=2)}\n```"

            start_time = datetime.now()
            self._prompts_sent += 1

            # Send prompt with timeout
            # Response text comes via session_update callbacks, not the return value
            effective_timeout = timeout or self.config.prompt_timeout
            async with asyncio.timeout(effective_timeout):
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
