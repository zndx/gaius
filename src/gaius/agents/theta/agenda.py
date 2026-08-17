"""Agenda aggregation from project directories.

Scans current/projects/**/agenda.md files and synthesizes
them into a unified, priority-ordered agenda.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .horizons import Horizon
from .sitrep import PriorityItem


# Regex patterns for agenda parsing
TASK_PATTERN = re.compile(
    r"^-\s*\[([ xX])\]\s*(?:(P[0-2]):\s*)?(.+?)(?:\s+@(\S+))?$",
    re.MULTILINE,
)

# Date keywords
DATE_KEYWORDS = {
    "today": lambda ref: ref,
    "tomorrow": lambda ref: ref + timedelta(days=1),
    "this-week": lambda ref: ref + timedelta(days=(6 - ref.weekday())),
    "next-week": lambda ref: ref + timedelta(days=(13 - ref.weekday())),
    "this-month": lambda ref: date(ref.year, ref.month + 1, 1) - timedelta(days=1)
    if ref.month < 12
    else date(ref.year, 12, 31),
}


@dataclass
class AgendaTask:
    """A task from an agenda.md file."""

    description: str
    priority: str = "P2"
    project: str = ""
    due_date: date | None = None
    completed: bool = False
    source_path: str = ""

    def matches_horizon(self, horizon: Horizon, reference: date | None = None) -> bool:
        """Check if this task falls within the given horizon.

        Args:
            horizon: The temporal horizon to check against.
            reference: Reference date (defaults to today).

        Returns:
            True if task is relevant to this horizon.
        """
        ref = reference or date.today()
        start, end = horizon.get_date_range(ref)

        if self.due_date is None:
            # Tasks without dates are always relevant for OPEN horizon
            # and relevant for other horizons if high priority
            if horizon == Horizon.OPEN:
                return True
            return self.priority in ("P0", "P1")

        return start <= self.due_date <= end

    def to_priority_item(self) -> PriorityItem:
        """Convert to PriorityItem for SITREP."""
        return PriorityItem(
            description=self.description,
            priority=self.priority,
            project=self.project,
            due_date=self.due_date,
            completed=self.completed,
        )


def parse_date(date_str: str, reference: date | None = None) -> date | None:
    """Parse a date string to a date object.

    Supports:
    - Keywords: today, tomorrow, this-week, next-week, this-month
    - ISO format: YYYY-MM-DD
    - Partial: MM-DD (assumes current year)

    Args:
        date_str: The date string to parse.
        reference: Reference date for keywords (defaults to today).

    Returns:
        Parsed date or None if invalid.
    """
    ref = reference or date.today()
    date_str = date_str.lower().strip()

    # Check keywords
    if date_str in DATE_KEYWORDS:
        return DATE_KEYWORDS[date_str](ref)

    # Try ISO format
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        pass

    # Try MM-DD format
    try:
        parts = date_str.split("-")
        if len(parts) == 2:
            month, day = int(parts[0]), int(parts[1])
            return date(ref.year, month, day)
    except (ValueError, IndexError):
        pass

    return None


def parse_agenda_md(path: Path, project_name: str = "") -> list[AgendaTask]:
    """Parse tasks from an agenda.md file.

    Expected format:
    ```markdown
    # Project Agenda

    ## This Week
    - [ ] P0: Important task @today
    - [ ] P1: Less urgent task @2025-12-25
    - [x] Completed task

    ## Backlog
    - [ ] Future task
    ```

    Args:
        path: Path to the agenda.md file.
        project_name: Project name to associate with tasks.

    Returns:
        List of parsed tasks.
    """
    if not path.exists():
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return []

    tasks = []
    ref_date = date.today()

    for match in TASK_PATTERN.finditer(content):
        checkbox, priority, description, date_str = match.groups()

        completed = checkbox.lower() == "x"
        priority = priority or "P2"
        due_date = parse_date(date_str, ref_date) if date_str else None

        task = AgendaTask(
            description=description.strip(),
            priority=priority,
            project=project_name,
            due_date=due_date,
            completed=completed,
            source_path=str(path),
        )
        tasks.append(task)

    return tasks


class AgendaAggregator:
    """Aggregates agendas from all project directories.

    Scans current/projects/**/agenda.md and synthesizes
    into a unified priority-ordered list.
    """

    def __init__(self, kb_root: Path | str | None = None):
        """Initialize aggregator.

        Args:
            kb_root: Root of the knowledge base (default: build/dev).
        """
        if kb_root is None:
            kb_root = Path("build/dev")
        self.kb_root = Path(kb_root)
        self.projects_dir = self.kb_root / "current" / "projects"

    def day_agenda_path(self) -> Path:
        """Personal day rollup: ``current/agenda.md``."""
        return self.kb_root / "current" / "agenda.md"

    def discover_agendas(self) -> list[Path]:
        """Find the day rollup and all project ``agenda.md`` files."""
        found: list[Path] = []
        day = self.day_agenda_path()
        if day.is_file():
            found.append(day)
        if self.projects_dir.exists():
            found.extend(sorted(self.projects_dir.glob("**/agenda.md")))
        return found

    def aggregate(
        self,
        horizon: Horizon = Horizon.DAY,
        include_completed: bool = False,
    ) -> list[AgendaTask]:
        """Aggregate all agenda items filtered by horizon.

        Args:
            horizon: Temporal horizon to filter by.
            include_completed: Whether to include completed tasks.

        Returns:
            Priority-sorted list of tasks.
        """
        all_tasks = []

        for agenda_path in self.discover_agendas():
            if agenda_path == self.day_agenda_path():
                project_name = "today"
            else:
                try:
                    rel_path = agenda_path.relative_to(self.projects_dir)
                    project_name = rel_path.parts[0] if rel_path.parts else ""
                except ValueError:
                    project_name = agenda_path.parent.name

            tasks = parse_agenda_md(agenda_path, project_name)
            all_tasks.extend(tasks)

        # Filter by horizon
        filtered = [t for t in all_tasks if t.matches_horizon(horizon)]

        # Filter completed if requested
        if not include_completed:
            filtered = [t for t in filtered if not t.completed]

        # Sort by priority (P0 > P1 > P2) then by due date
        priority_order = {"P0": 0, "P1": 1, "P2": 2}
        filtered.sort(
            key=lambda t: (
                priority_order.get(t.priority, 3),
                t.due_date or date.max,
            )
        )

        return filtered

    def get_project_count(self) -> int:
        """Get number of projects with agendas."""
        return len(self.discover_agendas())

    def to_priority_items(
        self,
        horizon: Horizon = Horizon.DAY,
        limit: int = 7,
    ) -> list[PriorityItem]:
        """Get priority items for SITREP.

        Args:
            horizon: Temporal horizon.
            limit: Maximum items to return (7±2 per Miller's Law).

        Returns:
            List of PriorityItem objects.
        """
        tasks = self.aggregate(horizon)
        return [t.to_priority_item() for t in tasks[:limit]]

    def init_day_agenda(self, horizon: Horizon = Horizon.DAY) -> dict[str, Any]:
        """Create ``current/agenda.md`` if missing. Never overwrite.

        Seeds from open P0/P1 project tasks in the horizon, or one starter
        line so sitrep has something to roll up.
        """
        path = self.day_agenda_path()
        rel = "current/agenda.md"
        if path.is_file():
            tasks = parse_agenda_md(path, project_name="today")
            return {
                "created": False,
                "path": rel,
                "items": tasks,
            }

        path.parent.mkdir(parents=True, exist_ok=True)
        seeds = [
            t
            for t in self.aggregate(horizon)
            if t.priority in ("P0", "P1")
        ][:7]
        today = date.today().isoformat()
        lines = [
            "# Agenda",
            "",
            f"horizon: {horizon.value}",
            f"generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## Today",
            "",
        ]
        if seeds:
            for t in seeds:
                due = t.due_date.isoformat() if t.due_date else "today"
                proj = f" ({t.project})" if t.project else ""
                lines.append(f"- [ ] {t.priority}: {t.description}{proj} @{due}")
        else:
            lines.append(f"- [ ] P1: Set today's priorities @{today}")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        tasks = parse_agenda_md(path, project_name="today")
        return {
            "created": True,
            "path": rel,
            "items": tasks,
        }

    def format_ascii(
        self,
        tasks: list[AgendaTask],
        horizon: Horizon = Horizon.DAY,
        path: str = "current/agenda.md",
        created: bool | None = None,
    ) -> str:
        """80-col list for CLI / sitrep-adjacent display."""
        lines = [f"AGENDA ({horizon.value})", path]
        if created is True:
            lines.append("created")
        elif created is False:
            lines.append("already exists")
        if not tasks:
            lines.append("  [--] No agenda items | /agenda init to create")
        else:
            for t in tasks:
                box = "x" if t.completed else " "
                due = t.due_date.isoformat() if t.due_date else ""
                proj = f" ({t.project})" if t.project else ""
                tail = f" @{due}" if due else ""
                lines.append(f"  [{box}] {t.priority}: {t.description}{proj}{tail}")
        return "\n".join(lines)
