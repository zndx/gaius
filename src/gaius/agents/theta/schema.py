"""Attention Schema Theory (AST) implementation.

Based on Graziano's S+A+V framework:
- S (Self): The attending agent (ThetaAgent)
- A (Attention): The selection process (AttentionSchema)
- V (Visual stimulus): The target (AttentionTarget)

The schema is a simplified, useful model of attention - not the full
complexity of what's being attended, but enough to enable meta-cognition
about attention allocation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Any
import numpy as np


@dataclass
class AttentionTarget:
    """Something that attention can be directed toward (V in S+A+V).

    Represents an objective, thought, agenda item, thread, or KB entry
    that could capture the agent's focus.
    """

    id: str
    content_type: str  # "objective", "thought", "agenda_item", "thread", "kb_entry"
    title: str
    salience: float = 0.5  # Composite score 0.0-1.0

    # Component scores (contribute to salience)
    urgency: float = 0.0  # Time-sensitivity
    novelty: float = 0.0  # How new/surprising
    relevance: float = 0.0  # Semantic relevance to current context
    recency: float = 0.0  # Temporal decay factor

    # Metadata
    source_path: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Grid position (if mapped to spatial representation)
    grid_x: int | None = None
    grid_y: int | None = None

    def compute_salience(self, weights: dict[str, float] | None = None) -> float:
        """Compute composite salience from component scores.

        Args:
            weights: Optional custom weights. Uses defaults if not provided.

        Returns:
            Composite salience score 0.0-1.0.
        """
        w = weights or {
            "urgency": 0.3,
            "novelty": 0.2,
            "relevance": 0.2,
            "recency": 0.3,
        }

        self.salience = (
            w.get("urgency", 0.3) * self.urgency
            + w.get("novelty", 0.2) * self.novelty
            + w.get("relevance", 0.2) * self.relevance
            + w.get("recency", 0.3) * self.recency
        )

        # Clamp to [0, 1]
        self.salience = max(0.0, min(1.0, self.salience))
        return self.salience

    def to_grid_position(self) -> tuple[int, int] | None:
        """Get grid position if available."""
        if self.grid_x is not None and self.grid_y is not None:
            return (self.grid_x, self.grid_y)
        return None


@dataclass
class AttentionSchema:
    """AST-inspired model of the agent's own attention (A in S+A+V).

    The schema is a simplified representation enabling meta-cognition
    about what is being attended and why. It maintains:
    - A single focus (primary attention target)
    - A periphery (potential targets, limited to 7±2 per cognitive load)
    - Attention history for pattern detection
    - Configurable salience weights
    """

    # Current primary focus
    focus: AttentionTarget | None = None

    # Peripheral awareness (potential targets not currently focused)
    # Limited to 7±2 items per Miller's Law
    periphery: list[AttentionTarget] = field(default_factory=list)

    # Recent attention history for pattern detection
    history: deque[AttentionTarget] = field(
        default_factory=lambda: deque(maxlen=50)
    )

    # Salience computation weights
    salience_weights: dict[str, float] = field(
        default_factory=lambda: {
            "urgency": 0.3,
            "novelty": 0.2,
            "relevance": 0.2,
            "recency": 0.3,
        }
    )

    # Maximum periphery size (7±2)
    max_periphery: int = 7

    def shift_attention(self, new_focus: AttentionTarget) -> AttentionTarget | None:
        """Shift focus to a new target.

        Args:
            new_focus: The new target to focus on.

        Returns:
            The previous focus target, or None if there was none.
        """
        previous = self.focus

        # Add previous focus to history if it exists
        if previous is not None:
            self.history.append(previous)

            # Move previous focus to periphery if not already there
            if previous not in self.periphery:
                self.periphery.insert(0, previous)
                self._trim_periphery()

        # Remove new focus from periphery if it was there
        self.periphery = [t for t in self.periphery if t.id != new_focus.id]

        self.focus = new_focus
        return previous

    def add_to_periphery(self, target: AttentionTarget) -> bool:
        """Add a target to peripheral awareness.

        Args:
            target: The target to add.

        Returns:
            True if added, False if already at focus or max capacity.
        """
        # Don't add if it's the current focus
        if self.focus and target.id == self.focus.id:
            return False

        # Don't add duplicates
        if any(t.id == target.id for t in self.periphery):
            return False

        # Compute salience
        target.compute_salience(self.salience_weights)

        # Insert sorted by salience (highest first)
        inserted = False
        for i, existing in enumerate(self.periphery):
            if target.salience > existing.salience:
                self.periphery.insert(i, target)
                inserted = True
                break

        if not inserted:
            self.periphery.append(target)

        self._trim_periphery()
        return True

    def _trim_periphery(self) -> None:
        """Trim periphery to max size, keeping highest salience items."""
        if len(self.periphery) > self.max_periphery:
            # Sort by salience and keep top items
            self.periphery.sort(key=lambda t: t.salience, reverse=True)
            self.periphery = self.periphery[: self.max_periphery]

    def decay_salience(self, decay_rate: float = 0.05) -> None:
        """Apply temporal decay to all targets.

        Args:
            decay_rate: Amount to decay salience per call.
        """
        for target in self.periphery:
            target.salience = max(0.0, target.salience - decay_rate)

        # Re-sort periphery after decay
        self.periphery.sort(key=lambda t: t.salience, reverse=True)

    def get_grid_targets(self) -> list[tuple[str, int, int, str]]:
        """Get all targets with grid positions for visualization.

        Returns:
            List of (id, x, y, color) tuples for grid rendering.
        """
        targets = []

        # Focus gets bright yellow
        if self.focus and self.focus.grid_x is not None:
            targets.append(
                (self.focus.id, self.focus.grid_x, self.focus.grid_y, "bright_yellow")
            )

        # Periphery colored by salience
        for target in self.periphery:
            if target.grid_x is not None:
                if target.salience > 0.7:
                    color = "cyan"
                elif target.salience > 0.4:
                    color = "blue"
                else:
                    color = "dim"
                targets.append((target.id, target.grid_x, target.grid_y, color))

        return targets

    def to_dict(self) -> dict[str, Any]:
        """Serialize schema to dictionary."""
        return {
            "focus": {
                "id": self.focus.id,
                "type": self.focus.content_type,
                "title": self.focus.title,
                "salience": self.focus.salience,
            }
            if self.focus
            else None,
            "periphery": [
                {
                    "id": t.id,
                    "type": t.content_type,
                    "title": t.title,
                    "salience": t.salience,
                }
                for t in self.periphery
            ],
            "periphery_count": len(self.periphery),
            "history_count": len(self.history),
        }
