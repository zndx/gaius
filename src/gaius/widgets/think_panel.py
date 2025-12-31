"""Think Panel widget for displaying engine activity and reasoning traces.

This widget shows "signs of life" from the engine - autonomous cognition,
evolution cycles, and other background activity. It demonstrates that the
engine is continuously performing valuable work, with the TUI serving as
a window into that activity.

Requires the engine to be running (agent-first architecture).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text

from textual.widget import Widget
from textual.reactive import reactive

from ..core.state import AppState, ReasoningTrace, BackgroundTask

logger = logging.getLogger(__name__)


@dataclass
class EngineActivity:
    """Cached engine activity state."""

    # Cognition daemon status
    cognition_running: bool = False
    cycles_completed: int = 0
    last_cycle_at: Optional[datetime] = None
    current_task: Optional[str] = None

    # Evolution daemon status
    evolution_running: bool = False
    evolution_cycles: int = 0
    next_agent: Optional[str] = None

    # Recent thoughts from engine
    thoughts: list[dict] = field(default_factory=list)

    # Health indicators
    engine_healthy: bool = False
    endpoints_running: int = 0
    gpu_utilization: float = 0.0

    # Last update
    last_update: Optional[datetime] = None
    update_error: Optional[str] = None


class ThinkPanel(Widget):
    """Displays engine activity and reasoning traces.

    Shows "signs of life" from the autonomous engine:
    - Cognition daemon: thoughts, patterns, connections
    - Evolution daemon: agent improvement cycles
    - GPU health and endpoint status

    Layout:
    +- Engine Activity ----------------------------------------+
    | ● Cognition: 12 cycles, last 3m ago                     |
    | ● Evolution: running, next: leader                       |
    | ● GPUs: 4 endpoints, 45% util                           |
    +----------------------------------------------------------+
    +- Recent Thoughts ----------------------------------------+
    | 14:32 pattern: recurring theme in consensus              |
    | 14:28 connection: raft ↔ paxos similarity               |
    | 14:15 curiosity: why does CAP limit availability?        |
    +----------------------------------------------------------+
    +- Local Traces -------------------------------------------+
    | 14:10 swarm: pension-analysis (7 agents)                |
    +----------------------------------------------------------+
    """

    DEFAULT_CSS = """
    ThinkPanel {
        width: 40;
        height: 21;
        overflow: hidden;
    }

    ThinkPanel.hidden {
        display: none;
    }
    """

    # Reactive to trigger refresh when traces change
    trace_count = reactive(0)

    # Engine poll interval (seconds)
    ENGINE_POLL_INTERVAL = 5.0

    def __init__(
        self,
        state: AppState,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.state = state
        self._engine_activity = EngineActivity()
        self._poll_task: Optional[asyncio.Task] = None
        self._cognition_stream_task: Optional[asyncio.Task] = None
        self._evolution_stream_task: Optional[asyncio.Task] = None
        self._streaming_active: bool = False

    def render(self) -> RenderableType:
        """Render the think panel content."""
        lines = []
        activity = self._engine_activity

        # ── Engine Status Section ──
        if activity.engine_healthy:
            lines.append(Text("Engine Activity", style="bold green"))
        else:
            lines.append(Text("Engine Activity", style="bold red"))
        lines.append(Text("─" * 36, style="dim"))

        # Cognition daemon status
        cog_line = Text()
        if activity.cognition_running:
            cog_line.append("● ", style="bold green")
            cog_line.append("Cognition: ", style="cyan")

            if activity.current_task:
                cog_line.append(activity.current_task[:20], style="yellow")
            elif activity.last_cycle_at:
                age = self._format_age(activity.last_cycle_at)
                cog_line.append(f"{activity.cycles_completed} cycles", style="white")
                cog_line.append(f", {age} ago", style="dim")
            else:
                cog_line.append("idle", style="dim")
        else:
            cog_line.append("○ ", style="dim")
            cog_line.append("Cognition: ", style="dim")
            cog_line.append("stopped", style="dim red")
        lines.append(cog_line)

        # Evolution daemon status
        evo_line = Text()
        if activity.evolution_running:
            evo_line.append("● ", style="bold green")
            evo_line.append("Evolution: ", style="magenta")
            evo_line.append(f"{activity.evolution_cycles} cycles", style="white")
            if activity.next_agent:
                evo_line.append(f", next: {activity.next_agent[:12]}", style="dim")
        else:
            evo_line.append("○ ", style="dim")
            evo_line.append("Evolution: ", style="dim")
            evo_line.append("stopped", style="dim red")
        lines.append(evo_line)

        # GPU/endpoint status
        gpu_line = Text()
        if activity.endpoints_running > 0:
            gpu_line.append("● ", style="bold green")
            gpu_line.append("GPU: ", style="yellow")
            gpu_line.append(f"{activity.endpoints_running} endpoints", style="white")
            if activity.gpu_utilization > 0:
                gpu_line.append(f", {activity.gpu_utilization:.0f}% util", style="dim")
        else:
            gpu_line.append("○ ", style="dim")
            gpu_line.append("GPU: ", style="dim")
            gpu_line.append("no endpoints", style="dim red")
        lines.append(gpu_line)

        # Update status
        if activity.update_error:
            err_line = Text()
            err_line.append("[!] ", style="bold red")
            err_line.append(activity.update_error[:32], style="red")
            lines.append(err_line)

        # Padding
        while len(lines) < 6:
            lines.append(Text(""))

        # ── Recent Thoughts Section ──
        lines.append(Text(""))
        lines.append(Text("Recent Thoughts", style="bold cyan"))
        lines.append(Text("─" * 36, style="dim"))

        if activity.thoughts:
            for thought in activity.thoughts[:5]:
                thought_line = self._format_thought(thought)
                lines.append(thought_line)
        else:
            lines.append(Text("  (awaiting engine thoughts)", style="dim"))

        # Padding
        while len(lines) < 13:
            lines.append(Text(""))

        # ── Local Traces Section ──
        lines.append(Text(""))
        lines.append(Text("Local Traces", style="bold yellow"))
        lines.append(Text("─" * 36, style="dim"))

        # Show TUI-initiated traces (swarm, search, etc.)
        traces = list(reversed(self.state.reasoning_traces[-4:]))
        if traces:
            for trace in traces:
                line = self._format_trace(trace)
                lines.append(line)
        else:
            lines.append(Text("  (no local activity)", style="dim"))

        # Combine all lines
        content = Text("\n").join(lines)

        # Panel title shows engine health
        if activity.engine_healthy:
            title = "[bold green]◉[/bold green] [bold]Think[/bold]"
        else:
            title = "[bold red]○[/bold red] [bold]Think[/bold]"

        return Panel(
            content,
            title=title,
            title_align="left",
            border_style="cyan" if activity.engine_healthy else "red",
            padding=(0, 1),
        )

    def _format_thought(self, thought: dict) -> Text:
        """Format a single thought from the engine."""
        text = Text()

        # Timestamp
        ts = thought.get("timestamp") or thought.get("created_at")
        if ts:
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                except (ValueError, TypeError):
                    time_str = "??:??"
            else:
                time_str = ts.strftime("%H:%M")
        else:
            time_str = "??:??"
        text.append(f"{time_str} ", style="dim")

        # Thought type with color
        thought_type = thought.get("type") or thought.get("thought_type", "thought")
        type_colors = {
            "pattern": "blue",
            "connection": "green",
            "curiosity": "yellow",
            "momentum": "magenta",
            "observation": "cyan",
            "self_observation": "bright_cyan",
            "engine_audit": "red",
        }
        color = type_colors.get(thought_type, "white")
        text.append(f"{thought_type[:10]}: ", style=color)

        # Title or content (truncated)
        title = thought.get("title") or thought.get("summary") or thought.get("content", "")
        if isinstance(title, str):
            max_len = 22
            if len(title) > max_len:
                title = title[: max_len - 1] + "…"
            text.append(title, style="white")

        return text

    def _format_trace(self, trace: ReasoningTrace) -> Text:
        """Format a single local trace line."""
        text = Text()

        # Timestamp (HH:MM)
        time_str = trace.timestamp.strftime("%H:%M")
        text.append(f"{time_str} ", style="dim")

        # Operation type with color coding
        op_colors = {
            "search": "blue",
            "synthesis": "green",
            "inference": "yellow",
            "swarm": "magenta",
        }
        color = op_colors.get(trace.operation, "white")
        text.append(f"{trace.operation}: ", style=color)

        # Query (truncated)
        query_max = 18
        query = trace.query[:query_max]
        if len(trace.query) > query_max:
            query = query[:-1] + "…"
        text.append(query, style="white")

        # Stats
        stats = []
        if trace.sources:
            stats.append(f"{trace.sources}src")
        if trace.tokens:
            if trace.tokens >= 1000:
                stats.append(f"{trace.tokens // 1000}k tok")
            else:
                stats.append(f"{trace.tokens}tok")
        if stats:
            text.append(f" ({', '.join(stats)})", style="dim")

        return text

    def _format_age(self, dt: datetime) -> str:
        """Format a datetime as age string."""
        now = datetime.now()
        if dt.tzinfo:
            now = datetime.now(dt.tzinfo)

        delta = now - dt
        seconds = delta.total_seconds()

        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m"
        elif seconds < 86400:
            return f"{int(seconds / 3600)}h"
        else:
            return f"{int(seconds / 86400)}d"

    # ─────────────────────────────────────────────────────────────────────────
    # Engine Polling / Streaming
    # ─────────────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        """Set up engine activity updates.

        Attempts streaming first (real-time updates), falls back to polling
        if streaming is not available.
        """
        # Try to start streaming, fall back to polling
        asyncio.create_task(self._start_streaming_or_polling())

    async def _start_streaming_or_polling(self) -> None:
        """Attempt to use gRPC streaming for real-time updates.

        Fail-fast: If streaming is unavailable, shows error state with
        actionable remediation instead of silently falling back to polling.
        """
        try:
            from ..client.grpc_client import get_grpc_client

            client = await get_grpc_client()

            if not client.is_connected:
                # Fail-fast: Show error instead of silent polling fallback
                logger.error("gRPC client not connected - engine unavailable")
                self._engine_activity.engine_healthy = False
                self._engine_activity.update_error = (
                    "Engine not connected.\n"
                    "Guru Meditation: #THINK.00000002.NOENGINE\n"
                    "Try: devenv processes up gaius-engine"
                )
                self.refresh()
                return

            # Try to start streaming - if it works, we're good
            # Start cognition stream
            self._cognition_stream_task = asyncio.create_task(
                self._consume_cognition_stream(client)
            )
            # Start evolution stream
            self._evolution_stream_task = asyncio.create_task(
                self._consume_evolution_stream(client)
            )

            self._streaming_active = True
            self._engine_activity.engine_healthy = True
            self._engine_activity.update_error = None
            logger.info("ThinkPanel using gRPC streaming for real-time updates")

            # Do initial poll to populate state immediately
            await self._do_poll()

        except Exception as e:
            # Fail-fast: Show error instead of silent polling fallback
            logger.error(f"Streaming setup failed: {e}")
            self._engine_activity.engine_healthy = False
            self._engine_activity.update_error = (
                f"Engine streaming unavailable: {e}\n"
                "Guru Meditation: #THINK.00000001.STREAMFAIL\n"
                "Try: /health fix engine"
            )
            self.refresh()

    def _start_polling(self) -> None:
        """Fall back to polling mode."""
        self._streaming_active = False
        self.set_interval(self.ENGINE_POLL_INTERVAL, self._poll_engine)
        asyncio.create_task(self._do_poll())
        logger.info(
            f"ThinkPanel using polling mode (interval={self.ENGINE_POLL_INTERVAL}s)"
        )

    async def _consume_cognition_stream(self, client) -> None:
        """Consume cognition events and update state.

        Runs continuously until cancelled. Updates engine activity state
        from incoming CognitionEvent messages.
        """
        try:
            async for event in client.subscribe_cognition():
                event_type = event.get("type", "")

                if event_type == "ERROR":
                    logger.debug(f"Cognition stream error: {event.get('error_message')}")
                    # Don't break - stream may recover
                    continue

                # Update activity based on event type
                if event_type == "CYCLE_START":
                    self._engine_activity.cognition_running = True
                    self._engine_activity.current_task = "thinking..."

                elif event_type == "CYCLE_END":
                    self._engine_activity.cognition_running = True
                    self._engine_activity.cycles_completed += 1
                    self._engine_activity.current_task = None
                    self._engine_activity.last_cycle_at = datetime.now()

                elif event_type in ("THOUGHT", "PATTERN", "CONNECTION", "CURIOSITY",
                                   "SELF_OBSERVATION", "ENGINE_AUDIT"):
                    # Add to thoughts list (most recent first)
                    thought = {
                        "timestamp": datetime.fromtimestamp(
                            event.get("timestamp_ms", 0) / 1000
                        ),
                        "type": event.get("thought_type", event_type.lower()),
                        "title": event.get("title", ""),
                        "content": event.get("content", ""),
                    }
                    # Prepend and limit to 10
                    self._engine_activity.thoughts = (
                        [thought] + self._engine_activity.thoughts
                    )[:10]

                # Mark engine as healthy since we're receiving events
                self._engine_activity.engine_healthy = True
                self._engine_activity.update_error = None
                self._engine_activity.last_update = datetime.now()
                self.refresh()

        except asyncio.CancelledError:
            logger.debug("Cognition stream cancelled")
        except Exception as e:
            # Fail-fast: Show error instead of silent polling fallback
            logger.error(f"Cognition stream failed: {e}")
            self._streaming_active = False
            self._engine_activity.engine_healthy = False
            self._engine_activity.update_error = (
                f"Cognition streaming failed: {e}\n"
                "Guru Meditation: #THINK.00000003.COGFAIL\n"
                "Try: /health fix engine"
            )
            self.refresh()

    async def _consume_evolution_stream(self, client) -> None:
        """Consume evolution events and update state.

        Runs continuously until cancelled. Updates engine activity state
        from incoming EvolutionEvent messages.
        """
        try:
            async for event in client.subscribe_evolution():
                event_type = event.get("type", "")

                if event_type == "ERROR":
                    logger.debug(f"Evolution stream error: {event.get('error_message')}")
                    continue

                # Update activity based on event type
                if event_type == "CYCLE_START":
                    self._engine_activity.evolution_running = True
                    self._engine_activity.next_agent = event.get("agent_id", "")

                elif event_type == "CYCLE_END":
                    self._engine_activity.evolution_running = True
                    self._engine_activity.evolution_cycles += 1
                    self._engine_activity.next_agent = None

                elif event_type in ("OPTIMIZATION_STEP", "EVALUATION"):
                    self._engine_activity.evolution_running = True
                    self._engine_activity.next_agent = event.get("agent_id", "")

                elif event_type == "PROMOTION":
                    # Agent was promoted - noteworthy event
                    self._engine_activity.evolution_running = True

                # Mark engine healthy
                self._engine_activity.engine_healthy = True
                self._engine_activity.last_update = datetime.now()
                self.refresh()

        except asyncio.CancelledError:
            logger.debug("Evolution stream cancelled")
        except Exception as e:
            # Fail-fast: Show error instead of silent degradation
            logger.error(f"Evolution stream failed: {e}")
            self._engine_activity.engine_healthy = False
            self._engine_activity.update_error = (
                f"Evolution streaming failed: {e}\n"
                "Guru Meditation: #THINK.00000004.EVOLFAIL\n"
                "Try: /health fix engine"
            )
            self.refresh()

    def on_unmount(self) -> None:
        """Clean up streaming tasks on unmount."""
        if self._cognition_stream_task:
            self._cognition_stream_task.cancel()
        if self._evolution_stream_task:
            self._evolution_stream_task.cancel()

    async def _poll_engine(self) -> None:
        """Trigger engine poll from interval timer."""
        await self._do_poll()

    async def refresh_now(self) -> None:
        """Trigger immediate refresh of engine activity.

        Call this after operations that generate new thoughts (like /thoughts)
        to update the panel without waiting for the next poll interval.
        """
        await self._do_poll()

    async def _do_poll(self) -> None:
        """Poll engine for activity."""
        try:
            from ..client.engine_proxy import use_engine_proxy

            if not use_engine_proxy():
                self._engine_activity.engine_healthy = False
                self._engine_activity.update_error = "Engine not running"
                self.refresh()
                return

            await self._fetch_engine_activity()
            self.refresh()

        except Exception as e:
            logger.debug(f"Engine poll failed: {e}")
            self._engine_activity.engine_healthy = False
            self._engine_activity.update_error = str(e)[:40]
            self.refresh()

    async def _fetch_engine_activity(self) -> None:
        """Fetch activity from engine services."""
        from ..client.engine_proxy import (
            get_cognition_proxy,
            get_evolution_proxy,
            get_health_proxy,
        )

        activity = self._engine_activity

        # Get cognition proxy
        try:
            cog = await get_cognition_proxy()
        except Exception as e:
            logger.debug(f"Failed to get cognition proxy: {e}")
            cog = None

        # Get cognition daemon status (may fail if daemon not started)
        if cog:
            try:
                status = await cog.get_status()

                activity.cognition_running = status.get("running", False)
                activity.cycles_completed = status.get("cycles_completed", 0)
                activity.current_task = status.get("current_task")

                if status.get("last_cycle_at"):
                    try:
                        activity.last_cycle_at = datetime.fromisoformat(
                            status["last_cycle_at"].replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        pass

            except Exception as e:
                logger.debug(f"Cognition status failed: {e}")
                # Continue - status failure doesn't prevent thought retrieval

        # Get recent thoughts (separate from status - should work even if status fails)
        if cog:
            try:
                thoughts = await cog.get_recent_thoughts(limit=5)
                activity.thoughts = thoughts
            except Exception as e:
                logger.debug(f"Failed to get recent thoughts: {e}")

        # Get evolution status
        try:
            evo = await get_evolution_proxy()
            status = await evo._get_status_async()

            activity.evolution_running = status.get("running", False)
            activity.evolution_cycles = status.get("cycles_completed", 0)
            activity.next_agent = status.get("next_agent")

        except Exception as e:
            logger.debug(f"Evolution fetch failed: {e}")

        # Get health status - this determines engine_healthy
        try:
            health = await get_health_proxy()
            status = await health.check()

            endpoints = status.get("endpoints", {})
            activity.endpoints_running = sum(
                1 for e in endpoints.values()
                if isinstance(e, dict) and e.get("status") == "healthy"
            )

            # Engine is healthy if we have at least one running endpoint
            if activity.endpoints_running > 0:
                activity.engine_healthy = True
                activity.update_error = None

            # Get GPU utilization
            gpu_util = await health.get_gpu_utilization()
            if gpu_util:
                activity.gpu_utilization = sum(gpu_util.values()) / len(gpu_util)

        except Exception as e:
            logger.debug(f"Health fetch failed: {e}")
            activity.engine_healthy = False
            activity.update_error = f"Health check failed: {e}"[:40]

        activity.last_update = datetime.now()

    # ─────────────────────────────────────────────────────────────────────────
    # Legacy Interface (for TUI-initiated operations)
    # ─────────────────────────────────────────────────────────────────────────

    def start_trace(
        self,
        operation: str,
        query: str,
        model: str = "",
    ) -> None:
        """Start a new reasoning trace.

        Called at the beginning of an inference/search operation.
        """
        initial_text = f"Starting {operation}..."
        if model:
            initial_text += f"\nUsing: {model}"
        initial_text += f"\nQuery: {query}"

        self.state.active_reasoning = initial_text
        self.refresh()

    def stream_reasoning(self, text: str) -> None:
        """Append text to active reasoning display."""
        if self.state.active_reasoning:
            self.state.active_reasoning += "\n" + text
        else:
            self.state.active_reasoning = text

        # Keep only last N lines
        lines = self.state.active_reasoning.split("\n")
        if len(lines) > 10:
            self.state.active_reasoning = "\n".join(lines[-10:])

        self.refresh()

    def complete_trace(
        self,
        operation: str,
        query: str,
        summary: str,
        tokens: int = 0,
        sources: int = 0,
        technique: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Complete the current reasoning and add to history."""
        trace = ReasoningTrace(
            timestamp=datetime.now(),
            operation=operation,
            query=query,
            summary=summary,
            tokens=tokens,
            sources=sources,
            technique=technique,
            duration_ms=duration_ms,
            full_trace=self.state.active_reasoning or "",
        )

        self.state.add_reasoning_trace(trace)
        self.state.active_reasoning = None
        self.trace_count = len(self.state.reasoning_traces)
        self.refresh()

    def clear_active(self) -> None:
        """Clear the active reasoning display."""
        self.state.active_reasoning = None
        self.refresh()

    def update_state(self, state: AppState) -> None:
        """Update the state reference and refresh."""
        self.state = state
        self.trace_count = len(self.state.reasoning_traces)
        self.refresh()
