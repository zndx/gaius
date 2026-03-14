"""Evolution Panel widget for monitoring the evolution daemon.

This widget shows real-time status of the Agent0-style evolution process,
including daemon status, recent cycles, agent performance, and trends.

Uses gRPC to connect to gaius-engine for real-time data.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from textual.widget import Widget
from textual.reactive import reactive

from ..core.state import AppState

logger = logging.getLogger(__name__)

# Engine client cache for TUI widgets
_engine_client: Optional[Any] = None
_engine_connected: bool = False


async def _get_engine_client():
    """Get gRPC engine client if available.

    Uses gRPC client by default for production use.
    Set GAIUS_DISABLE_ENGINE=true to skip engine connection.
    """
    global _engine_client, _engine_connected

    if os.environ.get("GAIUS_DISABLE_ENGINE", "").lower() == "true":
        return None

    if _engine_client is not None:
        if _engine_connected:
            return _engine_client
        # Try reconnecting
        try:
            if await _engine_client.connect():
                _engine_connected = True
                return _engine_client
        except Exception:
            pass
        return None

    try:
        from ..client.grpc_client import GrpcEngineClient
        _engine_client = GrpcEngineClient()
        if await _engine_client.connect():
            _engine_connected = True
            logger.info("TUI connected to gaius-engine via gRPC")
            return _engine_client
    except Exception as e:
        logger.debug(f"Engine not available for TUI: {e}")

    return None


@dataclass
class EvolutionCycleDisplay:
    """A cycle for display in the panel."""
    agent_id: str
    success: bool
    improvement: float
    duration_ms: int
    timestamp: datetime
    preempted: bool = False


@dataclass
class AgentStatus:
    """Status of a single agent."""
    agent_id: str
    version_id: str
    training_score: float
    held_out_score: float
    last_improved: Optional[datetime]
    trend: str  # "up", "down", "stable"


class EvolutionPanel(Widget):
    """Displays evolution daemon status and recent activity.

    Layout:
    +- Evolution Daemon ------------------------------------+
    | Status: RUNNING  │ Cycles: 42  │ Improvement: +12.5%  |
    | GPUs: 2/4 idle   │ Next: risk  │ Rate: 3.2/hr        |
    +-------------------------------------------------------+
    +- Recent Cycles ---------------------------------------+
    | 14:32 leader  ✓ +2.3%  1.2s                          |
    | 14:28 risk    ✓ +1.8%  0.9s                          |
    | 14:15 opt     ✗  0.0%  0.5s (preempted)              |
    +-------------------------------------------------------+
    +- Agent Scores (train/held-out) -----------------------+
    | leader   0.85/0.82 ↗  risk   0.78/0.76 →             |
    | opt      0.81/0.79 ↗  critic 0.77/0.75 ↘             |
    +-------------------------------------------------------+
    """

    DEFAULT_CSS = """
    EvolutionPanel {
        width: 40;
        height: 21;
        overflow: hidden;
    }

    EvolutionPanel.hidden {
        display: none;
    }
    """

    # Reactive to trigger refresh
    cycle_count = reactive(0)

    def __init__(
        self,
        state: AppState,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.state = state

        # Cached data - initialize with "loading" state
        self._daemon_status: dict = {"running": None, "loading": True}
        self._recent_cycles: list[EvolutionCycleDisplay] = []
        self._agent_statuses: list[AgentStatus] = []
        self._trend: str = "unknown"
        self._trend_confidence: float = 0.0
        self._held_out_stats: dict = {}
        self._last_refresh: Optional[datetime] = None

    def render(self) -> RenderableType:
        """Render the evolution panel content."""
        lines = []

        # Daemon status header
        lines.extend(self._render_daemon_status())
        lines.append(Text(""))

        # Recent cycles
        lines.extend(self._render_recent_cycles())
        lines.append(Text(""))

        # Agent scores
        lines.extend(self._render_agent_scores())

        # Trend footer
        lines.append(Text(""))
        lines.extend(self._render_trend())

        # Debug: show last refresh time
        if self._last_refresh:
            lines.append(Text(""))
            refresh_str = self._last_refresh.strftime("%H:%M:%S")
            lines.append(Text(f"Last refresh: {refresh_str}", style="dim"))

        content = Text("\n").join(lines)
        return Panel(
            content,
            title="[bold magenta]Evolution[/bold magenta]",
            title_align="left",
            border_style="magenta",
            padding=(0, 1),
        )

    def _render_daemon_status(self) -> list[Text]:
        """Render daemon status section."""
        lines = []

        status = self._daemon_status
        running = status.get("running")
        loading = status.get("loading", False)
        cycles = status.get("cycles_completed", 0)
        improvement = status.get("total_improvement_percent", 0.0)
        next_agent = status.get("next_agent", "?")
        parallel = status.get("parallel", False)
        parallel_endpoints = status.get("parallel_endpoints", 0)
        error = status.get("error")

        # Line 1: Status and cycles
        line1 = Text()
        if error:
            line1.append("[!] ERROR", style="bold red")
        elif loading or running is None:
            line1.append("◌ CHECKING...", style="bold yellow")
        elif running:
            line1.append("● RUNNING", style="bold green")
        else:
            line1.append("○ IDLE", style="dim")
        line1.append(f"  Cycles: {cycles}", style="white" if running else "dim")
        if improvement > 0 and running:
            line1.append(f"  +{improvement:.1f}%", style="green")
        lines.append(line1)

        # Line 2: Mode and next agent
        line2 = Text()
        mode = status.get("mode", "daemon")
        if mode == "orchestrated":
            line2.append("[ORCH] ", style="bold magenta")
        elif parallel and parallel_endpoints > 0:
            line2.append(f"[PAR] {parallel_endpoints}x ", style="bold magenta")

        # Show next agent or last decision for orchestrated
        if mode == "orchestrated":
            last_decision = status.get("last_decision")
            if last_decision:
                action = last_decision.get("action", "?")
                target = last_decision.get("target", "")
                line2.append(f"{action}", style="cyan bold")
                if target:
                    line2.append(f":{target}", style="white")
            else:
                line2.append("deciding...", style="yellow")
        else:
            line2.append(f"Next: ", style="dim")
            line2.append(next_agent, style="cyan bold")
            config = status.get("config", {})
            if config:
                strategy = config.get("strategy", "?")
                line2.append(f"  {strategy}", style="dim")
        lines.append(line2)

        return lines

    def _render_recent_cycles(self) -> list[Text]:
        """Render recent cycles section."""
        lines = []
        running = self._daemon_status.get("running", False)

        header = Text()
        header.append("Recent Cycles", style="bold yellow" if running else "yellow")
        if not running and self._recent_cycles:
            header.append(" (history)", style="dim")
        lines.append(header)
        lines.append(Text("─" * 36, style="dim"))

        if not self._recent_cycles:
            lines.append(Text("  (no cycles yet)", style="dim"))
            return lines

        for cycle in self._recent_cycles[:5]:
            line = Text()

            # Timestamp
            time_str = cycle.timestamp.strftime("%H:%M")
            line.append(f"{time_str} ", style="dim")

            # Agent (truncated)
            agent = cycle.agent_id[:8]
            line.append(f"{agent:<8}", style="cyan")

            # Success indicator
            if cycle.preempted:
                line.append(" = ", style="yellow")
            elif cycle.success:
                line.append(" + ", style="green")
            else:
                line.append(" - ", style="red")

            # Improvement
            if cycle.success and cycle.improvement > 0:
                line.append(f"+{cycle.improvement:.1f}%", style="green")
            elif cycle.improvement < 0:
                line.append(f"{cycle.improvement:.1f}%", style="red")
            else:
                line.append("  0.0%", style="dim")

            # Duration
            duration_s = cycle.duration_ms / 1000
            line.append(f" {duration_s:.1f}s", style="dim")

            lines.append(line)

        return lines

    def _render_agent_scores(self) -> list[Text]:
        """Render agent scores comparison."""
        lines = []
        running = self._daemon_status.get("running", False)

        header = Text()
        header.append("Agent Scores", style="bold cyan" if running else "cyan")
        if not running and self._agent_statuses:
            header.append(" (last eval)", style="dim")
        lines.append(header)
        lines.append(Text("─" * 36, style="dim"))

        if not self._agent_statuses:
            lines.append(Text("  (no evaluations)", style="dim"))
            return lines

        # Two agents per line
        for i in range(0, len(self._agent_statuses), 2):
            line = Text()
            for j in range(2):
                if i + j >= len(self._agent_statuses):
                    break
                agent = self._agent_statuses[i + j]

                # Agent name (truncated)
                name = agent.agent_id[:6]
                line.append(f"{name:<6}", style="white")

                # Scores
                train = agent.training_score
                held = agent.held_out_score
                line.append(f"{train:.2f}", style="green" if train > 0.8 else "yellow")
                line.append("/", style="dim")
                line.append(f"{held:.2f}", style="green" if held > 0.8 else "yellow")

                # Trend indicator
                trend_icons = {"up": "↗", "down": "↘", "stable": "→"}
                trend_colors = {"up": "green", "down": "red", "stable": "dim"}
                icon = trend_icons.get(agent.trend, "?")
                color = trend_colors.get(agent.trend, "dim")
                line.append(f" {icon} ", style=color)

            lines.append(line)

        return lines

    def _render_trend(self) -> list[Text]:
        """Render overall trend indicator."""
        lines = []

        trend_indicator = {
            "improving": "[+]",
            "stable": "[-]",
            "declining": "[v]",
            "unknown": "[?]",
        }
        trend_colors = {
            "improving": "green",
            "stable": "white",
            "declining": "red",
            "unknown": "dim",
        }

        indicator = trend_indicator.get(self._trend, "[?]")
        color = trend_colors.get(self._trend, "dim")

        line = Text()
        line.append(f"{indicator} Trend: ", style="dim")
        line.append(self._trend.upper(), style=f"bold {color}")
        if self._trend_confidence > 0:
            line.append(f" ({self._trend_confidence:.0%})", style="dim")
        lines.append(line)

        # Held-out stats if available
        if self._held_out_stats:
            stats_line = Text()
            total = self._held_out_stats.get("total_queries", 0)
            stats_line.append(f"Held-out pool: {total} queries", style="dim")
            lines.append(stats_line)

        return lines

    async def refresh_data(self) -> None:
        """Fetch fresh data from evolution daemon and database.

        Tries the engine proxy first if available, then falls back to
        direct module access (useful when running in the same process).
        """
        try:
            # Try engine proxy first (when available)
            client = await _get_engine_client()
            if client:
                await self._refresh_via_engine(client)
            else:
                await self._refresh_direct()

            self._daemon_status["loading"] = False
            self._last_refresh = datetime.now()
            self.cycle_count = self._daemon_status.get("cycles_completed", 0)
            self.refresh()

        except Exception as e:
            # Log errors but don't crash
            logger.warning(f"Evolution panel refresh failed: {e}")
            # Update status to show error state
            self._daemon_status = {"running": False, "loading": False, "error": str(e)}
            self.refresh()

    async def _refresh_via_engine(self, client) -> None:
        """Fetch data via gaius-engine proxy."""
        try:
            # Get evolution status from engine
            result = await client.call("Evolution", "status", {})
            if "error" not in result:
                self._daemon_status = result
                self._daemon_status["via_engine"] = True
                logger.debug(f"Evolution status via engine: running={result.get('running')}")
            else:
                logger.warning(f"Engine evolution status error: {result.get('error')}")
                # Fall back to direct access
                await self._refresh_direct()

        except Exception as e:
            logger.debug(f"Engine call failed, falling back: {e}")
            await self._refresh_direct()

        # Database queries still go direct for now (TODO: add to engine protocol)
        await self._fetch_recent_cycles()
        await self._fetch_agent_scores()
        await self._fetch_held_out_stats()
        await self._fetch_trend()

    async def _refresh_direct(self) -> None:
        """Fetch data directly from in-process modules."""
        # Check orchestrated evolution first (takes priority when running)
        try:
            from ..agents.evolution.orchestrated import get_orchestrated_evolution
            orch_evo = get_orchestrated_evolution()
            if orch_evo.running:
                self._daemon_status = orch_evo.get_status()
                self._daemon_status["mode"] = "orchestrated"
                self._daemon_status["total_improvement_percent"] = self._daemon_status.get("total_improvement", 0.0)
                logger.debug(f"Orchestrated evolution status: running={self._daemon_status.get('running')}, cycles={self._daemon_status.get('cycles_completed')}")
                # Get recent cycles from DB
                await self._fetch_recent_cycles()
                await self._fetch_agent_scores()
                await self._fetch_held_out_stats()
                await self._fetch_trend()
                return
        except Exception as e:
            logger.debug(f"Orchestrated evolution not available: {e}")

        # Fall back to simple daemon status
        from ..agents.evolution import get_evolution_daemon
        daemon = get_evolution_daemon()
        self._daemon_status = daemon.get_status()
        logger.debug(f"Daemon status (direct): running={self._daemon_status.get('running')}, cycles={self._daemon_status.get('cycles_completed')}")

        # Get recent cycles from DB
        await self._fetch_recent_cycles()

        # Get agent scores
        await self._fetch_agent_scores()

        # Get held-out stats
        await self._fetch_held_out_stats()

        # Get trend
        await self._fetch_trend()

    async def _fetch_recent_cycles(self) -> None:
        """Fetch recent evolution cycles from database."""
        try:
            import asyncpg
            import os

            from ..core.config import get_database_url
            url = get_database_url()

            conn = await asyncpg.connect(url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT agent_id, success, improvement_percent,
                           duration_ms, started_at, preempted
                    FROM evolution_cycles
                    ORDER BY started_at DESC
                    LIMIT 10
                    """
                )

                self._recent_cycles = [
                    EvolutionCycleDisplay(
                        agent_id=r["agent_id"],
                        success=r["success"],
                        improvement=r["improvement_percent"] or 0.0,
                        duration_ms=r["duration_ms"] or 0,
                        timestamp=r["started_at"],
                        preempted=r["preempted"] or False,
                    )
                    for r in rows
                ]
                logger.debug(f"Fetched {len(self._recent_cycles)} recent cycles")
            finally:
                await conn.close()

        except Exception as e:
            logger.debug(f"Failed to fetch cycles: {e}")

    async def _fetch_agent_scores(self) -> None:
        """Fetch agent training vs held-out scores."""
        try:
            import asyncpg
            import os

            from ..core.config import get_database_url
            url = get_database_url()

            conn = await asyncpg.connect(url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT agent_id, version_id, training_score,
                           held_out_score, overfit_gap
                    FROM eval_score_comparison
                    ORDER BY agent_id
                    """
                )

                self._agent_statuses = [
                    AgentStatus(
                        agent_id=r["agent_id"],
                        version_id=r["version_id"][:8] if r["version_id"] else "",
                        training_score=float(r["training_score"] or 0),
                        held_out_score=float(r["held_out_score"] or 0),
                        last_improved=None,
                        trend="up" if (r["overfit_gap"] or 0) < 0.05 else "down",
                    )
                    for r in rows
                ]
                logger.debug(f"Fetched {len(self._agent_statuses)} agent scores")
            finally:
                await conn.close()

        except Exception as e:
            logger.debug(f"Failed to fetch agent scores: {e}")

    async def _fetch_held_out_stats(self) -> None:
        """Fetch held-out pool statistics."""
        try:
            from ..agents.evolution import get_held_out_manager
            manager = get_held_out_manager()
            self._held_out_stats = await manager.get_stats()
            logger.debug(f"Fetched held-out stats: {self._held_out_stats}")
        except Exception as e:
            logger.debug(f"Failed to fetch held-out stats: {e}")

    async def _fetch_trend(self) -> None:
        """Fetch trend from daily summaries."""
        try:
            import asyncpg
            import os

            from ..core.config import get_database_url
            url = get_database_url()

            conn = await asyncpg.connect(url)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT trend_direction, trend_confidence
                    FROM daily_eval_summaries
                    ORDER BY eval_date DESC
                    LIMIT 1
                    """
                )
                if row:
                    self._trend = row["trend_direction"] or "unknown"
                    self._trend_confidence = float(row["trend_confidence"] or 0)
                    logger.debug(f"Fetched trend: {self._trend}")
            finally:
                await conn.close()

        except Exception as e:
            logger.debug(f"Failed to fetch trend: {e}")

    def on_mount(self) -> None:
        """Set up periodic refresh."""
        logger.info("Evolution panel mounted, starting 2s refresh interval")
        # Refresh every 2 seconds
        self.set_interval(2.0, self._periodic_refresh)
        # Initial fetch
        asyncio.create_task(self.refresh_data())

    def _periodic_refresh(self) -> None:
        """Periodic data refresh."""
        # Only refresh if visible (optimization)
        if not self.has_class("hidden"):
            asyncio.create_task(self.refresh_data())

    def on_show(self) -> None:
        """React to becoming visible - refresh data immediately."""
        logger.debug("Evolution panel became visible, refreshing")
        asyncio.create_task(self.refresh_data())

    def update_state(self, state: AppState) -> None:
        """Update the state reference."""
        self.state = state
