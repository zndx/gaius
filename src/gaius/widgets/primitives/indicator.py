"""Status indicator rendering with colored symbols.

Renders status indicators like:
● OK (green)
◐ Warning (yellow)
○ Error (red)
? Unknown (dim)
"""

from enum import Enum
from typing import Optional

from rich.text import Text


class StatusLevel(Enum):
    """Status levels with associated colors."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


# Icon and color mapping for each status level
LEVEL_STYLES: dict[StatusLevel, tuple[str, str]] = {
    StatusLevel.OK: ("●", "green"),
    StatusLevel.WARNING: ("◐", "yellow"),
    StatusLevel.ERROR: ("○", "red"),
    StatusLevel.UNKNOWN: ("?", "dim"),
}


def render_status_indicator(
    level: StatusLevel,
    label: str = "",
    value: str = "",
) -> Text:
    """Render a colored status indicator.

    Args:
        level: Status level (OK, WARNING, ERROR, UNKNOWN)
        label: Optional label after icon
        value: Optional value after label

    Returns:
        Rich Text like "● OK" or "◐ Warning: 3 pending"

    Examples:
        >>> render_status_indicator(StatusLevel.OK)
        Text("●", style="green")

        >>> render_status_indicator(StatusLevel.WARNING, "Memory", "85%")
        Text("◐ Memory 85%", style="yellow")
    """
    icon, color = LEVEL_STYLES.get(level, ("?", "dim"))

    text = Text()
    text.append(icon, style=color)

    if label:
        text.append(f" {label}", style=color)

    if value:
        text.append(f" {value}", style=color)

    return text


def render_status_row(
    indicators: list[StatusLevel],
    separator: str = "",
) -> Text:
    """Render multiple status indicators in a row.

    Args:
        indicators: List of status levels
        separator: String between indicators (default: no separator)

    Returns:
        Rich Text like "●●●○" for [OK, OK, OK, ERROR]
    """
    text = Text()
    for i, level in enumerate(indicators):
        if i > 0 and separator:
            text.append(separator)
        icon, color = LEVEL_STYLES.get(level, ("?", "dim"))
        text.append(icon, style=color)
    return text


def render_health_summary(
    healthy: int,
    total: int,
    label: str = "",
) -> Text:
    """Render a health summary with indicator dots.

    Args:
        healthy: Number of healthy items
        total: Total number of items
        label: Optional label

    Returns:
        Rich Text like "●●●○ 3/4 healthy"

    Example:
        >>> render_health_summary(3, 4, "Endpoints")
        Text("●●●○ Endpoints 3/4 healthy")
    """
    # Build indicator row
    indicators = [StatusLevel.OK] * healthy + [StatusLevel.ERROR] * (total - healthy)
    dots = render_status_row(indicators)

    text = Text()
    text.append(dots)
    if label:
        text.append(f" {label}")
    text.append(f" {healthy}/{total}", style="bold")
    text.append(" healthy", style="dim")

    return text


def status_from_value(
    value: float,
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None,
    direction: str = "above",
) -> StatusLevel:
    """Convert a numeric value to a status level.

    Args:
        value: Current value
        warning_threshold: Threshold for WARNING level
        critical_threshold: Threshold for ERROR level
        direction: "above" (higher is worse) or "below" (lower is worse)

    Returns:
        StatusLevel based on thresholds
    """
    if direction == "above":
        if critical_threshold is not None and value >= critical_threshold:
            return StatusLevel.ERROR
        if warning_threshold is not None and value >= warning_threshold:
            return StatusLevel.WARNING
    else:
        if critical_threshold is not None and value <= critical_threshold:
            return StatusLevel.ERROR
        if warning_threshold is not None and value <= warning_threshold:
            return StatusLevel.WARNING

    return StatusLevel.OK
