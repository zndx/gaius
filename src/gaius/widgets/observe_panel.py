"""Observe Panel - Operational health monitoring dashboard.

Displays real-time metrics from Prometheus and engine gRPC:
- Sparklines for time series (latency, throughput)
- Gauges for current state (GPU memory)
- Status indicators for health

Layout:
┌─ Observe ──────────────────────────────────┐
│ Latency p95 ▁▂▃▂▁▂▄▅▃▂▁  142ms            │
│ Infer/min   ▃▃▄▅▆▅▄▃▃▄▅  12.3             │
│ Search/min  ▂▂▃▃▄▃▂▂▃▃▄  8.7              │
│ Errors      0.2%                           │
│─────────────────────────────────────────────│
│ GPU 0 Mem   ████████░░░░  67%              │
│ GPU 1 Mem   ██████░░░░░░  52%              │
│ Endpoints   3 healthy                      │
│ Evolution   847 cycles                     │
└─────────────────────────────────────────────┘
"""

import asyncio
import logging
import math
from typing import Optional, TYPE_CHECKING

from rich.panel import Panel
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from ..observability.sources.base import MetricSeries, MetricSource
from ..observability.sources.prometheus import PrometheusSource
from ..observability.sources.engine import EngineSource
from ..observability.metrics import (
    OBSERVE_METRICS,
    MetricDefinition,
    MetricDisplay,
)
from .primitives.sparkline import render_sparkline
from .primitives.gauge import render_gauge

if TYPE_CHECKING:
    from ..core.state import AppState

logger = logging.getLogger(__name__)


def format_compact(value: float, precision: int = 1) -> str:
    """Format large numbers in compact notation (K, M, B).

    Examples:
        1234 -> "1.2K"
        1234567 -> "1.2M"
        1234567890 -> "1.2B"
        123 -> "123"
    """
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{precision}f}B"
    elif abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.{precision}f}M"
    elif abs(value) >= 10_000:
        return f"{value / 1_000:.{precision}f}K"
    elif abs(value) >= 1_000:
        return f"{value / 1_000:.{precision}f}K"
    else:
        return f"{value:.{precision}f}"


class ObservePanel(Widget):
    """Operational health monitoring panel.

    Polls Prometheus and engine for metrics, renders sparklines and gauges.
    Also shows endpoint status and gRPC connection (info from InitPanel).
    Updates every POLL_INTERVAL seconds when visible.
    """

    POLL_INTERVAL = 5.0  # seconds

    # CSS for sizing - match other center panels height
    DEFAULT_CSS = """
    ObservePanel {
        width: 42;
        height: auto;
        min-height: 18;
    }
    ObservePanel.hidden {
        display: none;
    }
    """

    # Reactive to trigger refresh when availability changes
    _available = reactive(False)

    def __init__(
        self,
        state: "AppState",
        metrics: Optional[list[MetricDefinition]] = None,
        **kwargs,
    ):
        """Initialize ObservePanel.

        Args:
            state: Application state
            metrics: Optional custom metric definitions (default: OBSERVE_METRICS)
            **kwargs: Widget arguments
        """
        super().__init__(**kwargs)
        self.state = state
        self.metrics_config = metrics or OBSERVE_METRICS
        self._metric_data: dict[str, MetricSeries] = {}
        self._prometheus: Optional[PrometheusSource] = None
        self._engine: Optional[EngineSource] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._endpoint_status: dict = {}  # Cached endpoint status
        self._grpc_connected: bool = False

    def on_mount(self) -> None:
        """Start polling when mounted."""
        # Initial fetch
        self.run_worker(self._initial_fetch())
        # Set up periodic polling
        self.set_interval(self.POLL_INTERVAL, self._poll_metrics)

    async def _initial_fetch(self) -> None:
        """Fetch metrics immediately on mount."""
        await self._refresh_metrics()

    async def _poll_metrics(self) -> None:
        """Periodic polling callback."""
        # Only poll if panel is visible
        if not self.has_class("hidden"):
            await self._refresh_metrics()

    async def _refresh_metrics(self) -> None:
        """Fetch all configured metrics from sources."""
        # Check Prometheus availability
        prometheus = await self._get_prometheus()
        prom_available = await prometheus.health_check()

        if not prom_available:
            self._available = False
            # Still try to fetch endpoint status even without Prometheus
            await self._fetch_endpoint_status()
            self.refresh()
            return

        self._available = True

        # Fetch metrics by source
        for defn in self.metrics_config:
            try:
                if defn.source == "prometheus":
                    series = await prometheus.query_range(
                        defn.query,
                        duration_seconds=300,
                        step_seconds=15,
                    )
                    self._metric_data[defn.id] = series
                elif defn.source == "engine":
                    engine = await self._get_engine()
                    series = await engine.query_range(defn.query)
                    self._metric_data[defn.id] = series
            except Exception as e:
                logger.debug(f"Metric fetch failed for {defn.id}: {e}")
                # Keep stale data rather than clearing

        # Fetch endpoint status for the status section
        await self._fetch_endpoint_status()

        self.refresh()

    async def _fetch_endpoint_status(self) -> None:
        """Fetch current endpoint status from engine."""
        try:
            from ..client.engine_proxy import get_health_proxy, use_engine_proxy

            if not use_engine_proxy():
                self._grpc_connected = False
                self._endpoint_status = {}
                return

            health = await get_health_proxy()
            status = await health.check()

            self._grpc_connected = True
            self._endpoint_status = status.get("endpoints", {})
        except Exception as e:
            logger.debug(f"Endpoint status fetch failed: {e}")
            self._grpc_connected = False
            self._endpoint_status = {}

    async def _get_prometheus(self) -> PrometheusSource:
        """Get or create Prometheus source."""
        if self._prometheus is None:
            self._prometheus = PrometheusSource()
        return self._prometheus

    async def _get_engine(self) -> EngineSource:
        """Get or create Engine source."""
        if self._engine is None:
            self._engine = EngineSource()
        return self._engine

    def render(self) -> Panel:
        """Render the observe panel."""
        lines: list[Text] = []

        if not self._available:
            lines.append(Text("Metrics unavailable", style="dim italic"))
            lines.append(Text(""))
            lines.append(Text("Waiting for Prometheus...", style="dim"))
            lines.append(Text("  http://localhost:9090", style="dim"))
        else:
            # Group metrics by source for visual separation
            prometheus_metrics = [m for m in self.metrics_config if m.source == "prometheus"]
            engine_metrics = [m for m in self.metrics_config if m.source == "engine"]

            # Render Prometheus metrics (sparklines)
            for defn in prometheus_metrics:
                series = self._metric_data.get(defn.id)
                lines.append(self._render_metric_row(defn, series))

            # Separator
            if prometheus_metrics and engine_metrics:
                lines.append(Text("─" * 38, style="dim"))

            # Render Engine metrics (gauges/counters)
            for defn in engine_metrics:
                series = self._metric_data.get(defn.id)
                lines.append(self._render_metric_row(defn, series))

        # Separator before status section
        lines.append(Text("─" * 38, style="dim"))

        # Endpoint status section (from InitPanel)
        lines.append(self._render_endpoint_status())

        # gRPC connection status
        lines.append(self._render_connection_status())

        # Join lines with newlines
        content = Text()
        for i, line in enumerate(lines):
            if i > 0:
                content.append("\n")
            content.append(line)

        return Panel(
            content,
            title="[bold cyan]Observe[/bold cyan]",
            title_align="left",
            border_style="cyan",
            padding=(0, 1),
        )

    def _render_endpoint_status(self) -> Text:
        """Render compact endpoint status line showing unhealthy endpoints."""
        line = Text()
        line.append("Endpoints   ", style="bold")

        if not self._endpoint_status:
            line.append("--", style="dim")
            return line

        # Count by status and track unhealthy names
        healthy = 0
        starting = 0
        unhealthy = 0
        unhealthy_names = []
        total = 0

        for name, ep_data in self._endpoint_status.items():
            if isinstance(ep_data, dict):
                total += 1
                status = ep_data.get("status", "unknown")
                if status == "healthy":
                    healthy += 1
                elif status in ("starting", "stopping"):
                    starting += 1
                else:
                    unhealthy += 1
                    unhealthy_names.append(name)

        # Compact format: "3/4 ready" or "3● 1○ (embedding)"
        if starting == 0 and unhealthy == 0:
            # All healthy
            line.append(f"{healthy}/{total}", style="green")
            line.append(" ready", style="dim")
        else:
            # Show breakdown with unhealthy names
            line.append(f"{healthy}●", style="green")
            if starting > 0:
                line.append(f" {starting}◎", style="yellow")
            if unhealthy > 0:
                line.append(f" {unhealthy}○", style="red")
                # Show which endpoints are down (truncate if too long)
                if unhealthy_names:
                    names_str = ",".join(unhealthy_names[:2])  # Max 2 names
                    if len(unhealthy_names) > 2:
                        names_str += "..."
                    line.append(f" ({names_str})", style="red dim")

        return line

    def _render_connection_status(self) -> Text:
        """Render gRPC connection status line."""
        line = Text()

        if self._grpc_connected:
            line.append("● ", style="green")
            line.append("gRPC: ", style="dim")
            line.append("connected", style="green")
        else:
            line.append("○ ", style="red")
            line.append("gRPC: ", style="dim")
            line.append("disconnected", style="red")

        return line

    def _render_metric_row(
        self,
        defn: MetricDefinition,
        series: Optional[MetricSeries],
    ) -> Text:
        """Render a single metric row based on display type.

        Args:
            defn: Metric definition
            series: Metric data series (may be None)

        Returns:
            Formatted Rich Text line
        """
        row = Text()

        # Label (left-aligned, 12 chars)
        row.append(f"{defn.name:<12}", style="bold")

        if series is None or series.current is None:
            row.append("  --", style="dim")
            return row

        current = series.current

        # Handle NaN values (e.g., from histogram_quantile with no data)
        if math.isnan(current):
            row.append("  --", style="dim")
            return row
        color = defn.get_color(current)

        if defn.display == MetricDisplay.SPARKLINE:
            # Sparkline + current value (compact notation for large numbers)
            sparkline = render_sparkline(
                series.sparkline_data,
                width=defn.width,
                color=color,
            )
            row.append(sparkline)
            formatted = format_compact(current, defn.precision)
            row.append(f"  {formatted}{defn.unit}", style=color)

        elif defn.display == MetricDisplay.GAUGE:
            # Horizontal gauge bar
            gauge = render_gauge(
                current,
                max_value=defn.max_value,
                width=defn.width,
                unit=defn.unit,
                warning_threshold=defn.warning_threshold,
                critical_threshold=defn.critical_threshold,
                precision=defn.precision,
            )
            row.append(gauge)

        elif defn.display == MetricDisplay.PERCENTAGE:
            # Simple percentage value with color
            row.append(f"  {current:.{defn.precision}f}{defn.unit}", style=color)

        else:  # COUNTER
            # Simple numeric value
            row.append(f"  {current:.{defn.precision}f}{defn.unit}", style=color)

        return row

    async def on_unmount(self) -> None:
        """Clean up resources when unmounted."""
        if self._prometheus:
            await self._prometheus.close()
        if self._engine:
            await self._engine.close()
