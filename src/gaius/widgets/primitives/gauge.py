"""Gauge rendering with threshold-based coloring.

Renders horizontal bar gauges with fill percentage:
████████░░░░  67%

Colors based on warning/critical thresholds.
"""

from typing import Optional

from rich.text import Text


def render_gauge(
    value: float,
    max_value: float = 100,
    width: int = 12,
    unit: str = "",
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None,
    show_value: bool = True,
    precision: int = 0,
) -> Text:
    """Render a horizontal gauge bar.

    Args:
        value: Current value
        max_value: Maximum value (for percentage calculation)
        width: Width of the bar in characters
        unit: Units to display after value (%, GB, etc.)
        warning_threshold: Value at which to show yellow
        critical_threshold: Value at which to show red
        show_value: Whether to show numeric value after bar
        precision: Decimal places for value display

    Returns:
        Rich Text with gauge bar and optional value

    Example:
        >>> render_gauge(67, max_value=100, unit="%")
        Text("████████░░░░ 67%")
    """
    # Calculate fill ratio
    ratio = min(value / max_value, 1.0) if max_value > 0 else 0
    filled = int(ratio * width)
    empty = width - filled

    # Determine color based on thresholds
    color = _get_threshold_color(value, warning_threshold, critical_threshold)

    # Build the gauge
    text = Text()
    text.append("█" * filled, style=color)
    text.append("░" * empty, style="dim")

    if show_value:
        fmt = f"{{:.{precision}f}}"
        value_str = fmt.format(value)
        text.append(f" {value_str}{unit}", style=color)

    return text


def render_gauge_labeled(
    label: str,
    value: float,
    max_value: float = 100,
    width: int = 12,
    unit: str = "",
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None,
    label_width: int = 10,
) -> Text:
    """Render a labeled gauge bar.

    Args:
        label: Left-aligned label
        value: Current value
        max_value: Maximum value
        width: Bar width
        unit: Units suffix
        warning_threshold: Yellow threshold
        critical_threshold: Red threshold
        label_width: Width for label column

    Returns:
        Rich Text with "Label    ████░░░░ 67%"
    """
    text = Text()
    text.append(f"{label:<{label_width}}", style="bold")
    text.append(render_gauge(
        value,
        max_value=max_value,
        width=width,
        unit=unit,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    ))
    return text


def render_mini_gauge(
    value: float,
    max_value: float = 100,
    width: int = 5,
) -> Text:
    """Render a compact gauge without value display.

    Args:
        value: Current value
        max_value: Maximum value
        width: Bar width (default 5 for compact display)

    Returns:
        Compact gauge like "███░░"
    """
    return render_gauge(
        value,
        max_value=max_value,
        width=width,
        show_value=False,
    )


def _get_threshold_color(
    value: float,
    warning: Optional[float],
    critical: Optional[float],
    direction: str = "above",
) -> str:
    """Get color based on value and thresholds.

    Args:
        value: Current value
        warning: Warning threshold
        critical: Critical threshold
        direction: "above" (higher is worse) or "below" (lower is worse)

    Returns:
        Color name: "green", "yellow", or "red"
    """
    if direction == "above":
        if critical is not None and value >= critical:
            return "red"
        if warning is not None and value >= warning:
            return "yellow"
    else:
        if critical is not None and value <= critical:
            return "red"
        if warning is not None and value <= warning:
            return "yellow"

    return "green"
