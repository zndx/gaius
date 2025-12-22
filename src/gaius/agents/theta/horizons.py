"""Temporal horizons for situational awareness.

Maps to theta wave frequency bands:
- DAY (Low theta, 2-5 Hz): Tactical, immediate actions
- WEEK (Variable theta, 4-8 Hz): Sprint planning, deliverables
- QUARTER (High theta, 6-10 Hz): Strategic objectives, goals
- OPEN (Ultra-low, <2 Hz): Emergent, open domain reasoning
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Any


class Horizon(str, Enum):
    """Temporal horizon for situational awareness.

    Each horizon corresponds to a different theta frequency band
    and cognitive frame.
    """

    DAY = "day"  # ~8 actions, tactical, immediate
    WEEK = "week"  # ~40 actions, sprint, deliverables
    QUARTER = "quarter"  # ~100 actions, strategic, goals
    OPEN = "open"  # Unbounded, emergent, open domain

    @property
    def action_budget(self) -> int:
        """Approximate action budget for this horizon."""
        return {
            Horizon.DAY: 8,
            Horizon.WEEK: 40,
            Horizon.QUARTER: 100,
            Horizon.OPEN: -1,  # Unbounded
        }[self]

    @property
    def theta_frequency(self) -> str:
        """Conceptual theta frequency band."""
        return {
            Horizon.DAY: "2-5 Hz (low theta)",
            Horizon.WEEK: "4-8 Hz (variable)",
            Horizon.QUARTER: "6-10 Hz (high theta)",
            Horizon.OPEN: "<2 Hz (ultra-low)",
        }[self]

    @property
    def cognitive_frame(self) -> str:
        """Human-readable cognitive frame description."""
        return {
            Horizon.DAY: "Tactical, immediate",
            Horizon.WEEK: "Sprint, deliverables",
            Horizon.QUARTER: "Strategic, goals",
            Horizon.OPEN: "Emergent, open domain",
        }[self]

    def get_date_range(self, reference: date | None = None) -> tuple[date, date]:
        """Get the date range for this horizon.

        Returns:
            Tuple of (start_date, end_date) inclusive.
        """
        ref = reference or date.today()

        if self == Horizon.DAY:
            return (ref, ref)
        elif self == Horizon.WEEK:
            # Start of week (Monday) to end of week (Sunday)
            start = ref - timedelta(days=ref.weekday())
            end = start + timedelta(days=6)
            return (start, end)
        elif self == Horizon.QUARTER:
            # Current quarter
            quarter = (ref.month - 1) // 3
            start_month = quarter * 3 + 1
            start = date(ref.year, start_month, 1)
            # End of quarter
            end_month = start_month + 2
            if end_month == 12:
                end = date(ref.year, 12, 31)
            else:
                end = date(ref.year, end_month + 1, 1) - timedelta(days=1)
            return (start, end)
        else:  # OPEN
            # Unbounded - use a very wide range
            return (date(1970, 1, 1), date(2099, 12, 31))


@dataclass
class HorizonView:
    """Situational view at a specific temporal horizon.

    Aggregates all relevant data for generating a SITREP
    at a particular time scale.
    """

    horizon: Horizon
    generated_at: datetime = field(default_factory=datetime.now)

    # Agenda items filtered to this horizon
    agenda_items: list[dict] = field(default_factory=list)

    # Objectives with status
    objectives: list[dict] = field(default_factory=list)

    # Active research threads
    threads: list[dict] = field(default_factory=list)

    # Recent thoughts from cognition agent
    thoughts: list[dict] = field(default_factory=list)

    # Action links extracted from thoughts
    action_links: list[dict] = field(default_factory=list)

    # KB activity summary
    kb_activity: dict[str, Any] = field(default_factory=dict)

    # System health summary
    system_health: dict[str, Any] = field(default_factory=dict)

    # Evolution status
    evolution: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Check if this view has no meaningful content."""
        return (
            not self.agenda_items
            and not self.objectives
            and not self.thoughts
            and not self.threads
        )

    @property
    def item_count(self) -> int:
        """Total number of items across all categories."""
        return (
            len(self.agenda_items)
            + len(self.objectives)
            + len(self.thoughts)
            + len(self.threads)
        )
