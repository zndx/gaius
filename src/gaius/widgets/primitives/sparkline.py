"""Sparkline rendering using Unicode block characters.

Renders time series data as compact ASCII sparklines:
▁▂▃▄▅▆▇█

Example output:
    ▁▂▃▂▁▂▄▅▃▂▁  (20 chars, 8 levels)
"""

from typing import Sequence, Optional

from rich.text import Text

# Unicode block characters for sparklines (8 levels + space for 0)
# Using lower blocks: U+2581 to U+2588
SPARK_BLOCKS = " ▁▂▃▄▅▆▇█"


def render_sparkline(
    values: Sequence[float],
    width: int = 20,
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
    color: str = "green",
) -> Text:
    """Render a sparkline from a sequence of values.

    Args:
        values: Data points to visualize
        width: Target width in characters
        min_val: Minimum for scaling (auto-detect if None)
        max_val: Maximum for scaling (auto-detect if None)
        color: Rich color name for the sparkline

    Returns:
        Rich Text object with sparkline characters
    """
    if not values:
        return Text("─" * width, style="dim")

    # Resample to fit target width
    resampled = _resample(list(values), width)

    # Determine scale
    actual_min = min_val if min_val is not None else min(resampled)
    actual_max = max_val if max_val is not None else max(resampled)
    value_range = actual_max - actual_min

    # Handle flat line (all same value)
    if value_range == 0:
        # Use middle block for flat line
        return Text(SPARK_BLOCKS[4] * len(resampled), style=color)

    # Map values to block indices
    blocks = []
    for v in resampled:
        # Normalize to 0-1
        normalized = (v - actual_min) / value_range
        # Map to block index (0-8)
        idx = int(normalized * (len(SPARK_BLOCKS) - 1))
        idx = max(0, min(len(SPARK_BLOCKS) - 1, idx))
        blocks.append(SPARK_BLOCKS[idx])

    return Text("".join(blocks), style=color)


def _resample(values: list[float], target_width: int) -> list[float]:
    """Resample values to target width.

    Uses linear interpolation for upsampling and averaging for downsampling.

    Args:
        values: Original data points
        target_width: Desired number of points

    Returns:
        Resampled values
    """
    n = len(values)

    if n == target_width:
        return values

    if n == 0:
        return [0.0] * target_width

    if n == 1:
        return values * target_width

    if n > target_width:
        # Downsample by averaging buckets
        return _downsample(values, target_width)
    else:
        # Upsample by linear interpolation
        return _upsample(values, target_width)


def _downsample(values: list[float], target: int) -> list[float]:
    """Downsample by averaging buckets."""
    n = len(values)
    result = []
    bucket_size = n / target

    for i in range(target):
        start = int(i * bucket_size)
        end = int((i + 1) * bucket_size)
        end = min(end, n)
        if start < end:
            bucket = values[start:end]
            result.append(sum(bucket) / len(bucket))
        else:
            result.append(values[-1] if values else 0)

    return result


def _upsample(values: list[float], target: int) -> list[float]:
    """Upsample by linear interpolation."""
    n = len(values)
    result = []

    for i in range(target):
        # Map target index to source position
        src_pos = i * (n - 1) / (target - 1) if target > 1 else 0

        # Get surrounding source indices
        src_idx = int(src_pos)
        frac = src_pos - src_idx

        if src_idx >= n - 1:
            result.append(values[-1])
        else:
            # Linear interpolation
            v = values[src_idx] * (1 - frac) + values[src_idx + 1] * frac
            result.append(v)

    return result


def render_sparkline_with_bounds(
    values: Sequence[float],
    width: int = 20,
    color: str = "green",
    show_bounds: bool = True,
) -> Text:
    """Render sparkline with min/max bounds displayed.

    Args:
        values: Data points
        width: Sparkline width
        color: Color name
        show_bounds: Whether to show min/max values

    Returns:
        Rich Text with sparkline and optional bounds
    """
    if not values:
        return Text("─" * width, style="dim")

    sparkline = render_sparkline(values, width, color=color)

    if show_bounds:
        min_v = min(values)
        max_v = max(values)
        bounds = Text()
        bounds.append(f"{min_v:.0f}", style="dim")
        bounds.append(sparkline)
        bounds.append(f"{max_v:.0f}", style="dim")
        return bounds

    return sparkline
