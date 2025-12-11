"""Reusable rendering primitives for TUI widgets.

Provides:
- render_sparkline: Unicode block character time series
- render_gauge: Horizontal bar with threshold coloring
- render_status_indicator: Colored status dots
"""

from .sparkline import render_sparkline
from .gauge import render_gauge
from .indicator import render_status_indicator, StatusLevel

__all__ = [
    "render_sparkline",
    "render_gauge",
    "render_status_indicator",
    "StatusLevel",
]
