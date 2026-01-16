"""Situation Report (SITREP) generation.

The SITREP is the core deliverable of ThetaAgent - a time-horizon-aware
situational awareness document with human factors consideration.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any

from .horizons import Horizon, HorizonView


class SitrepSection(str, Enum):
    """Sections of a SITREP document."""

    SYSTEM_STATUS = "system_status"
    PRIORITY = "priority"
    THOUGHTS = "thoughts"
    OBJECTIVES = "objectives"
    EVOLUTION = "evolution"
    QUICK_ACTIONS = "quick_actions"


@dataclass
class HealthStatus:
    """System health summary."""

    healthy: bool = True
    status_text: str = "UNKNOWN"
    gpu_count: int = 0
    endpoint_count: int = 0
    error: str | None = None
    suggestion: str | None = None


@dataclass
class PriorityItem:
    """A priority item from agenda aggregation."""

    description: str
    priority: str = "P2"  # P0, P1, P2
    project: str = ""
    due_date: date | None = None
    completed: bool = False


@dataclass
class ThoughtSummary:
    """Summary of an agent thought."""

    id: str
    thought_type: str
    title: str
    summary: str  # Truncated to ~80 chars
    has_action_link: bool = False


@dataclass
class ObjectiveStatus:
    """Status of a tracked objective."""

    name: str
    progress_pct: int = 0
    status: str = "NOT RUN"  # PASS, FAIL, IN PROGRESS, NOT RUN
    priority: str = "normal"


@dataclass
class EvolutionStatus:
    """Evolution daemon status."""

    next_agent: str = ""
    mode: str = ""
    last_cycle: datetime | None = None
    score_before: float | None = None
    score_after: float | None = None
    running: bool = False


@dataclass
class QuickAction:
    """A suggested quick action."""

    command: str
    description: str


@dataclass
class SituationReport:
    """Complete situation report for a time horizon.

    Aggregates all relevant data into a structured report
    with ASCII formatting for terminal display.
    """

    horizon: Horizon
    generated_at: datetime = field(default_factory=datetime.now)

    # Sections
    system_status: HealthStatus = field(default_factory=HealthStatus)
    priorities: list[PriorityItem] = field(default_factory=list)
    thoughts: list[ThoughtSummary] = field(default_factory=list)
    objectives: list[ObjectiveStatus] = field(default_factory=list)
    evolution: EvolutionStatus = field(default_factory=EvolutionStatus)
    quick_actions: list[QuickAction] = field(default_factory=list)

    # Metadata
    is_bootstrap: bool = False
    project_count: int = 0
    total_thoughts: int = 0
    total_objectives: int = 0

    def to_ascii(self) -> str:
        """Format as ASCII text for terminal display.

        Returns:
            Multi-line string formatted for 80-column terminal.
        """
        lines = []
        width = 80

        # Header
        lines.append("=" * width)
        title = "GAIUS SITUATION REPORT"
        lines.append(title.center(width))
        date_str = f"{self.generated_at.strftime('%Y-%m-%d')} ({self.horizon.value.title()} View)"
        lines.append(date_str.center(width))
        lines.append("=" * width)
        lines.append("")

        if self.is_bootstrap:
            lines.extend(self._format_bootstrap())
        else:
            lines.extend(self._format_system_status())
            lines.append("")
            lines.extend(self._format_priorities())
            lines.append("")
            lines.extend(self._format_thoughts())
            lines.append("")
            lines.extend(self._format_objectives())
            lines.append("")
            lines.extend(self._format_evolution())
            lines.append("")
            lines.extend(self._format_quick_actions())

        lines.append("")
        lines.append("=" * width)

        return "\n".join(lines)

    def _format_bootstrap(self) -> list[str]:
        """Format bootstrap/onboarding message."""
        return [
            "WELCOME TO GAIUS",
            "",
            "  Your knowledge base is fresh. Get started:",
            "",
            '  1. /project new "my-project"   - Create a project',
            '  2. /research "topic"           - Research something',
            "  3. /thoughts                   - Let Gaius think",
            "",
            "  Run /sitrep again after adding content.",
            "",
            "CAPABILITY OVERVIEW",
            "",
            "  Your Gaius instance has these capabilities:",
            "  - Research synthesis with web search integration",
            "  - Multi-agent swarm analysis",
            "  - Topological data analysis (TDA) for KB structure",
            f"  - GPU-accelerated inference ({self.system_status.gpu_count} GPUs detected)",
            "  - Agent evolution and self-improvement",
        ]

    def _format_system_status(self) -> list[str]:
        """Format system status line."""
        status = self.system_status
        status_str = status.status_text
        info = f"[{status.gpu_count} GPUs | {status.endpoint_count} Endpoints]"

        # Right-align the info
        padding = 80 - len(f"SYSTEM STATUS: {status_str}") - len(info) - 2
        line = f"SYSTEM STATUS: {status_str}" + " " * padding + info

        lines = [line, "-" * 80]

        if status.error:
            lines.append(f"  Warning: {status.error}")
            if status.suggestion:
                lines.append(f"  Suggestion: {status.suggestion}")

        return lines

    def _format_priorities(self) -> list[str]:
        """Format priority items section."""
        if self.project_count > 0:
            header = f"TODAY'S PRIORITY (from {self.project_count} projects)"
        else:
            header = "TODAY'S PRIORITY"

        lines = [header]

        if not self.priorities:
            lines.append("  [--] No agenda items | /agenda init to create")
        else:
            for i, item in enumerate(self.priorities[:5], 1):
                priority = f"[{item.priority}]" if item.priority else "[--]"
                project = f"({item.project})" if item.project else ""
                lines.append(f"  {i}. {priority} {item.description} {project}")

            remaining = len(self.priorities) - 5
            if remaining > 0:
                lines.append(f"  + {remaining} more | /agenda for full list")

        return lines

    def _format_thoughts(self) -> list[str]:
        """Format agent thoughts section."""
        if self.total_thoughts > 0:
            header = f"AGENT THOUGHTS ({len(self.thoughts)} shown, {self.total_thoughts} total)"
        else:
            header = "AGENT THOUGHTS"

        lines = [header]

        if not self.thoughts:
            lines.append("  [--] No recent thoughts | /thoughts to trigger cognition")
        else:
            for thought in self.thoughts[:5]:
                type_tag = f"[{thought.thought_type}]"
                action_marker = " [action]" if thought.has_action_link else ""
                # Truncate title to fit
                max_title = 60 - len(type_tag) - len(action_marker)
                title = thought.title[:max_title] + "..." if len(thought.title) > max_title else thought.title
                lines.append(f"  {type_tag} {title}{action_marker}")

            remaining = self.total_thoughts - 5
            if remaining > 0:
                lines.append(f"  + {remaining} more | /thoughts recent for full list")

        return lines

    def _format_objectives(self) -> list[str]:
        """Format objectives section."""
        if self.total_objectives > 0:
            header = f"OBJECTIVES ({len(self.objectives)} shown, {self.total_objectives} tracked)"
        else:
            header = "OBJECTIVES"

        lines = [header]

        if not self.objectives:
            lines.append("  [--] No objectives defined | see current/objectives/")
        else:
            for obj in self.objectives[:5]:
                # Progress bar
                filled = obj.progress_pct // 10
                bar = "#" * filled + "-" * (10 - filled)

                # Format: [##########] name                    100%  PASS
                name_width = 35
                name = obj.name[:name_width].ljust(name_width)
                pct = f"{obj.progress_pct}%".rjust(4)
                status = obj.status

                lines.append(f"  [{bar}] {name} {pct}  {status}")

            remaining = self.total_objectives - 5
            if remaining > 0:
                lines.append(f"  + {remaining} more | /objectives for full list")

        return lines

    def _format_evolution(self) -> list[str]:
        """Format evolution status section."""
        lines = ["EVOLUTION"]

        evo = self.evolution
        if not evo.running and not evo.next_agent:
            lines.append("  [--] Evolution daemon not running | /evolve start")
        else:
            # Next agent and mode
            next_info = f"Next: {evo.next_agent}" if evo.next_agent else "Next: (idle)"
            mode_info = f"({evo.mode})" if evo.mode else ""

            # Score delta
            if evo.score_before is not None and evo.score_after is not None:
                delta = evo.score_after - evo.score_before
                delta_pct = (delta / evo.score_before * 100) if evo.score_before > 0 else 0
                score_info = f"Last: {evo.score_before:.2f} -> {evo.score_after:.2f} ({delta_pct:+.1f}%)"
            else:
                score_info = ""

            line = f"  {next_info} {mode_info}"
            if score_info:
                line += f" | {score_info}"
            lines.append(line)

        return lines

    def _format_quick_actions(self) -> list[str]:
        """Format quick actions section."""
        lines = ["QUICK ACTIONS"]

        if not self.quick_actions:
            # Default actions
            self.quick_actions = [
                QuickAction("/thoughts", "Trigger cognition cycle"),
                QuickAction("/health", "Run diagnostics"),
                QuickAction("/research <topic>", "Start research on topic"),
            ]

        for action in self.quick_actions[:5]:
            cmd = action.command.ljust(18)
            lines.append(f"  {cmd} {action.description}")

        return lines

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return {
            "horizon": self.horizon.value,
            "generated_at": self.generated_at.isoformat(),
            "is_bootstrap": self.is_bootstrap,
            "system_status": {
                "healthy": self.system_status.healthy,
                "status": self.system_status.status_text,
                "gpus": self.system_status.gpu_count,
                "endpoints": self.system_status.endpoint_count,
                "error": self.system_status.error,
            },
            "priorities": [
                {
                    "description": p.description,
                    "priority": p.priority,
                    "project": p.project,
                    "completed": p.completed,
                }
                for p in self.priorities
            ],
            "thoughts": [
                {
                    "id": t.id,
                    "type": t.thought_type,
                    "title": t.title,
                    "has_action": t.has_action_link,
                }
                for t in self.thoughts
            ],
            "objectives": [
                {
                    "name": o.name,
                    "progress": o.progress_pct,
                    "status": o.status,
                }
                for o in self.objectives
            ],
            "evolution": {
                "next_agent": self.evolution.next_agent,
                "mode": self.evolution.mode,
                "running": self.evolution.running,
                "score_before": self.evolution.score_before,
                "score_after": self.evolution.score_after,
            },
            "quick_actions": [
                {"command": a.command, "description": a.description}
                for a in self.quick_actions
            ],
            "metadata": {
                "project_count": self.project_count,
                "total_thoughts": self.total_thoughts,
                "total_objectives": self.total_objectives,
            },
        }
