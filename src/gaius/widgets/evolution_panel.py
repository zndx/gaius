"""Evolution Panel widget for monitoring the evolution daemon.

This widget shows real-time status of the Agent0-style evolution process,
including daemon status, recent cycles, agent performance, and trends.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from textual.widget import Widget
from textual.reactive import reactive

from ..core.state import AppState


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

        # Cached data
        self._daemon_status: dict = {}
        self._recent_cycles: list[EvolutionCycleDisplay] = []
        self._agent_statuses: list[AgentStatus] = []
        self._trend: str = "unknown"
        self._trend_confidence: float = 0.0
        self._held_out_stats: dict = {}

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
        running = status.get("running", False)
        cycles = status.get("cycles_completed", 0)
        improvement = status.get("total_improvement_percent", 0.0)
        next_agent = status.get("next_agent", "?")

        # Line 1: Status and cycles
        line1 = Text()
        if running:
            line1.append("● RUNNING", style="bold green")
        else:
            line1.append("○ STOPPED", style="bold red")
        line1.append(f"  Cycles: {cycles}", style="white")
        if improvement > 0:
            line1.append(f"  +{improvement:.1f}%", style="green")
        lines.append(line1)

        # Line 2: Next agent and config
        line2 = Text()
        line2.append(f"Next: ", style="dim")
        line2.append(next_agent, style="cyan bold")
        config = status.get("config", {})
        if config:
            strategy = config.get("strategy", "?")
            line2.append(f"  Strategy: {strategy}", style="dim")
        lines.append(line2)

        return lines

    def _render_recent_cycles(self) -> list[Text]:
        """Render recent cycles section."""
        lines = []
        lines.append(Text("Recent Cycles", style="bold yellow"))
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
                line.append(" ⏸ ", style="yellow")
            elif cycle.success:
                line.append(" ✓ ", style="green")
            else:
                line.append(" ✗ ", style="red")

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
        lines.append(Text("Agent Scores", style="bold cyan"))
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

        trend_emoji = {
            "improving": "📈",
            "stable": "➡️",
            "declining": "📉",
            "unknown": "❓",
        }
        trend_colors = {
            "improving": "green",
            "stable": "white",
            "declining": "red",
            "unknown": "dim",
        }

        emoji = trend_emoji.get(self._trend, "❓")
        color = trend_colors.get(self._trend, "dim")

        line = Text()
        line.append(f"{emoji} Trend: ", style="dim")
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
        """Fetch fresh data from evolution daemon and database."""
        try:
            # Get daemon status
            from ..agents.evolution import get_evolution_daemon
            daemon = get_evolution_daemon()
            self._daemon_status = daemon.get_status()

            # Get recent cycles from DB
            await self._fetch_recent_cycles()

            # Get agent scores
            await self._fetch_agent_scores()

            # Get held-out stats
            await self._fetch_held_out_stats()

            # Get trend
            await self._fetch_trend()

            self.cycle_count = self._daemon_status.get("cycles_completed", 0)
            self.refresh()

        except Exception as e:
            # Don't crash on fetch errors
            pass

    async def _fetch_recent_cycles(self) -> None:
        """Fetch recent evolution cycles from database."""
        try:
            import asyncpg
            import os

            url = os.getenv(
                "DATABASE_URL",
                "postgresql://gaius:gaius@localhost:5432/gaius"
            )

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
            finally:
                await conn.close()

        except Exception:
            pass  # Keep existing data

    async def _fetch_agent_scores(self) -> None:
        """Fetch agent training vs held-out scores."""
        try:
            import asyncpg
            import os

            url = os.getenv(
                "DATABASE_URL",
                "postgresql://gaius:gaius@localhost:5432/gaius"
            )

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
            finally:
                await conn.close()

        except Exception:
            pass

    async def _fetch_held_out_stats(self) -> None:
        """Fetch held-out pool statistics."""
        try:
            from ..agents.evolution import get_held_out_manager
            manager = get_held_out_manager()
            self._held_out_stats = await manager.get_stats()
        except Exception:
            pass

    async def _fetch_trend(self) -> None:
        """Fetch trend from daily summaries."""
        try:
            import asyncpg
            import os

            url = os.getenv(
                "DATABASE_URL",
                "postgresql://gaius:gaius@localhost:5432/gaius"
            )

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
            finally:
                await conn.close()

        except Exception:
            pass

    def on_mount(self) -> None:
        """Set up periodic refresh."""
        # Refresh every 2 seconds
        self.set_interval(2.0, self._periodic_refresh)
        # Initial fetch
        asyncio.create_task(self.refresh_data())

    def _periodic_refresh(self) -> None:
        """Periodic data refresh."""
        asyncio.create_task(self.refresh_data())

    def update_state(self, state: AppState) -> None:
        """Update the state reference."""
        self.state = state
