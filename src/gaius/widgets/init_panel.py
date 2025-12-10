"""Init Panel widget for displaying engine initialization progress.

This widget shows real-time initialization progress during the ~240s startup
phase when vLLM endpoints are preloading. It connects to the engine via
gRPC InitStream for bidirectional communication.

Layout:
+- Engine Initializing -------------------------+
|                                               |
| [=========>                    ] 35%          |
| Est. ~180s remaining                          |
|                                               |
| Endpoints                                     |
| ────────────────────────────────────────────|
| orchestrator [========>     ] 78%  ~45s       |
|   nvidia/Orchestrator-8B on GPUs 0,1          |
| fast         [              ] waiting         |
| reasoning    [==========] READY               |
|                                               |
| Services:                                     |
|   gRPC: READY | Scheduler: READY              |
|                                               |
| Press 'g' to cycle panels                     |
+-----------------------------------------------+
"""

import asyncio
import logging
from typing import Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TaskID
from rich.text import Text

from textual.widget import Widget
from textual.reactive import reactive

from ..core.state import AppState, InitializationState, EndpointInitProgress

logger = logging.getLogger(__name__)


class InitPanel(Widget):
    """Displays engine initialization progress.

    Shows real-time progress during startup:
    - Overall initialization progress bar
    - Per-endpoint status with indicators
    - Estimated time remaining
    - gRPC connection status

    Auto-hides when initialization completes.
    """

    DEFAULT_CSS = """
    InitPanel {
        width: 40;
        height: 21;
        overflow: hidden;
    }

    InitPanel.hidden {
        display: none;
    }
    """

    # Reactive to trigger refresh when init state changes
    init_progress = reactive(0.0)

    # Poll interval for gRPC stream (seconds)
    POLL_INTERVAL = 0.5

    def __init__(
        self,
        state: AppState,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.state = state
        self._stream_task: Optional[asyncio.Task] = None
        self._connected = False

    def render(self) -> RenderableType:
        """Render the init panel content."""
        lines = []
        init_state = self.state.initialization_state

        # ── Header ──
        if init_state.is_ready:
            lines.append(Text("Initialization Complete", style="bold green"))
        elif init_state.error:
            lines.append(Text("Initialization Error", style="bold red"))
        else:
            lines.append(Text("Engine Initializing", style="bold yellow"))

        lines.append(Text("─" * 36, style="dim"))

        # ── Overall Progress Bar ──
        progress_bar = self._render_progress_bar(init_state.overall_progress)
        lines.append(progress_bar)

        # Progress percentage and phase
        pct = int(init_state.overall_progress * 100)
        phase_line = Text()
        phase_line.append(f"{pct}%", style="bold")
        phase_line.append(f" - {init_state.phase}", style="dim")
        lines.append(phase_line)

        # Message
        if init_state.message:
            msg = init_state.message[:35]
            lines.append(Text(msg, style="cyan"))

        # Paused indicator
        if init_state.is_paused:
            lines.append(Text("⏸ PAUSED (user request)", style="yellow"))

        # Error message
        if init_state.error:
            lines.append(Text(f"Error: {init_state.error[:30]}", style="red"))

        # Padding
        while len(lines) < 7:
            lines.append(Text(""))

        # ── Endpoints Section ──
        lines.append(Text("Endpoints", style="bold cyan"))
        lines.append(Text("─" * 36, style="dim"))

        if init_state.endpoints:
            for name, ep in init_state.endpoints.items():
                ep_line = self._render_endpoint(name, ep)
                lines.append(ep_line)
        else:
            lines.append(Text("  (awaiting endpoint list)", style="dim"))

        # Padding
        while len(lines) < 15:
            lines.append(Text(""))

        # ── Connection Status ──
        lines.append(Text(""))
        conn_line = Text()
        if init_state.connected:
            conn_line.append("● ", style="bold green")
            conn_line.append("gRPC: ", style="cyan")
            conn_line.append("connected", style="green")
        else:
            conn_line.append("○ ", style="dim")
            conn_line.append("gRPC: ", style="dim")
            conn_line.append("connecting...", style="yellow")
        lines.append(conn_line)

        # Hint
        lines.append(Text(""))
        lines.append(Text("Press 'g' to cycle panels", style="dim"))

        # Combine all lines
        content = Text("\n").join(lines)

        # Panel styling based on state
        if init_state.is_ready:
            border_style = "green"
            title = "[bold green]✓[/bold green] [bold]Init[/bold]"
        elif init_state.error:
            border_style = "red"
            title = "[bold red]✗[/bold red] [bold]Init[/bold]"
        elif init_state.connected:
            border_style = "yellow"
            title = "[bold yellow]◉[/bold yellow] [bold]Init[/bold]"
        else:
            border_style = "dim"
            title = "[dim]○[/dim] [bold]Init[/bold]"

        return Panel(
            content,
            title=title,
            title_align="left",
            border_style=border_style,
            padding=(0, 1),
        )

    def _render_progress_bar(self, progress: float, width: int = 30) -> Text:
        """Render a simple ASCII progress bar."""
        filled = int(progress * width)
        empty = width - filled

        bar = Text()
        bar.append("[", style="dim")
        bar.append("=" * filled, style="green")
        if filled < width:
            bar.append(">", style="green")
            bar.append(" " * (empty - 1), style="dim")
        bar.append("]", style="dim")

        return bar

    def _render_endpoint(self, name: str, ep: EndpointInitProgress) -> Text:
        """Render a single endpoint status line."""
        line = Text()

        # Status indicator
        status_icons = {
            "pending": ("○ ", "dim"),
            "starting": ("◎ ", "yellow"),
            "ready": ("● ", "green"),
            "failed": ("✗ ", "red"),
            "cancelled": ("⊘ ", "dim"),
        }
        icon, style = status_icons.get(ep.status, ("? ", "dim"))
        line.append(icon, style=style)

        # Name (truncated)
        name_display = name[:12].ljust(12)
        line.append(name_display, style="white")

        # Mini progress bar or status
        if ep.status == "starting":
            mini_bar = self._mini_progress_bar(ep.progress)
            line.append(mini_bar)
        elif ep.status == "ready":
            line.append(" READY", style="green")
        elif ep.status == "failed":
            line.append(" FAIL", style="red")
        elif ep.status == "cancelled":
            line.append(" SKIP", style="dim")
        else:
            line.append(" waiting", style="dim")

        return line

    def _mini_progress_bar(self, progress: float, width: int = 10) -> Text:
        """Render a mini progress bar for endpoints."""
        filled = int(progress * width)
        empty = width - filled

        bar = Text()
        bar.append("[", style="dim")
        bar.append("=" * filled, style="cyan")
        if filled < width and filled > 0:
            bar.append(">", style="cyan")
            bar.append(" " * (empty - 1), style="dim")
        elif filled == 0:
            bar.append(" " * empty, style="dim")
        bar.append("]", style="dim")
        bar.append(f" {int(progress * 100)}%", style="dim")

        return bar

    # ─────────────────────────────────────────────────────────────────────────
    # gRPC Stream Connection
    # ─────────────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        """Start the gRPC stream when mounted."""
        self._stream_task = asyncio.create_task(self._connect_init_stream())

    def on_unmount(self) -> None:
        """Clean up the stream task."""
        if self._stream_task:
            self._stream_task.cancel()

    async def _connect_init_stream(self) -> None:
        """Connect to engine InitStream and update state."""
        try:
            from ..client.engine_proxy import use_engine_proxy

            # Wait a moment for app to initialize
            await asyncio.sleep(0.5)

            if not use_engine_proxy():
                # Engine not configured, show disconnected state
                self.state.initialization_state.error = "Engine not running"
                self.refresh()
                return

            # Try to connect to InitStream
            await self._stream_init_events()

        except asyncio.CancelledError:
            logger.debug("InitPanel stream cancelled")
        except Exception as e:
            logger.debug(f"InitPanel stream error: {e}")
            self.state.initialization_state.error = str(e)[:40]
            self.refresh()

    async def _stream_init_events(self) -> None:
        """Stream events from InitStream and update state."""
        try:
            from ..client.grpc_client import get_grpc_client

            client = await get_grpc_client()

            # Subscribe to init stream
            async for event in client.init_stream():
                self._update_from_event(event)
                self.init_progress = self.state.initialization_state.overall_progress
                self.refresh()

                # If ready, we can stop streaming (but panel stays visible for 'g' cycling)
                if self.state.initialization_state.is_ready:
                    logger.debug("InitPanel: received READY, stream complete")
                    break

        except Exception as e:
            logger.debug(f"InitStream error: {e}")
            # Fall back to polling if stream fails
            await self._poll_init_status()

    async def _poll_init_status(self) -> None:
        """Fallback: poll for init status if streaming fails."""
        logger.debug("InitPanel falling back to polling mode")

        max_retries = 5
        retry_count = 0
        consecutive_failures = 0

        while not self.state.initialization_state.is_ready:
            try:
                from ..client.engine_proxy import get_health_proxy

                health = await get_health_proxy()
                status = await health.check()

                # Update state from health check
                init_state = self.state.initialization_state
                init_state.connected = True
                consecutive_failures = 0  # Reset on success

                # Populate endpoints from health status
                endpoints = status.get("endpoints", {})
                healthy_count = 0
                for ep_name, ep_data in endpoints.items():
                    if isinstance(ep_data, dict):
                        ep_status = ep_data.get("status", "unknown")
                        is_healthy = ep_status == "healthy"
                        if is_healthy:
                            healthy_count += 1

                        # Create or update endpoint progress
                        if ep_name not in init_state.endpoints:
                            init_state.endpoints[ep_name] = EndpointInitProgress(name=ep_name)
                        ep = init_state.endpoints[ep_name]
                        ep.status = "ready" if is_healthy else ep_status
                        ep.progress = 1.0 if is_healthy else 0.5
                        ep.message = ep_data.get("model", "")

                if healthy_count > 0:
                    init_state.is_ready = True
                    init_state.overall_progress = 1.0
                    init_state.phase = "ready"
                    init_state.message = "All endpoints ready"

                self.refresh()

            except Exception as e:
                consecutive_failures += 1
                self.state.initialization_state.connected = False
                self.state.initialization_state.error = str(e)[:40]
                self.refresh()

                # Stop polling after too many consecutive failures
                if consecutive_failures >= max_retries:
                    logger.debug(f"InitPanel: stopping polling after {max_retries} failures")
                    self.state.initialization_state.phase = "disconnected"
                    self.state.initialization_state.message = "Engine unavailable"
                    self.refresh()
                    return

            retry_count += 1
            await asyncio.sleep(2.0)  # Poll every 2 seconds

    def _update_from_event(self, event: dict) -> None:
        """Update initialization state from an InitEvent."""
        init_state = self.state.initialization_state
        init_state.connected = True

        event_type = event.get("type", "")
        init_state.phase = event.get("phase", init_state.phase)
        init_state.overall_progress = event.get("progress", init_state.overall_progress)
        init_state.message = event.get("message", init_state.message)

        # Parse data payload if present (contains full status on SUBSCRIBE)
        data = event.get("data")
        if data and isinstance(data, dict):
            # Update from data payload (sent with SUBSCRIBE response)
            if data.get("is_ready"):
                init_state.is_ready = True
                init_state.overall_progress = data.get("overall_progress", 1.0)
            if data.get("is_paused"):
                init_state.is_paused = True
            # Populate endpoints from data payload
            endpoints_data = data.get("endpoints", {})
            for ep_name, ep_info in endpoints_data.items():
                if ep_name not in init_state.endpoints:
                    init_state.endpoints[ep_name] = EndpointInitProgress(name=ep_name)
                ep = init_state.endpoints[ep_name]
                ep.status = ep_info.get("status", ep.status)
                ep.progress = ep_info.get("progress", ep.progress)
                ep.message = ep_info.get("message", ep.message)

        # Handle specific event types
        if event_type == "READY":
            init_state.is_ready = True
            init_state.overall_progress = 1.0
        elif event_type == "PAUSED":
            init_state.is_paused = True
        elif event_type == "RESUMED":
            init_state.is_paused = False
        elif event_type == "ERROR":
            init_state.error = event.get("message", "Unknown error")
        elif event_type in ("ENDPOINT_STARTING", "PROGRESS"):
            endpoint = event.get("endpoint")
            if endpoint:
                if endpoint not in init_state.endpoints:
                    init_state.endpoints[endpoint] = EndpointInitProgress(name=endpoint)
                ep = init_state.endpoints[endpoint]
                ep.status = "starting"
                ep.progress = event.get("progress", ep.progress)
                ep.message = event.get("message", ep.message)
        elif event_type == "ENDPOINT_READY":
            endpoint = event.get("endpoint")
            if endpoint:
                if endpoint not in init_state.endpoints:
                    init_state.endpoints[endpoint] = EndpointInitProgress(name=endpoint)
                init_state.endpoints[endpoint].status = "ready"
                init_state.endpoints[endpoint].progress = 1.0
        elif event_type == "ENDPOINT_FAILED":
            endpoint = event.get("endpoint")
            if endpoint:
                if endpoint not in init_state.endpoints:
                    init_state.endpoints[endpoint] = EndpointInitProgress(name=endpoint)
                init_state.endpoints[endpoint].status = "failed"
        elif event_type == "CANCELLED":
            endpoint = event.get("endpoint")
            if endpoint:
                if endpoint not in init_state.endpoints:
                    init_state.endpoints[endpoint] = EndpointInitProgress(name=endpoint)
                init_state.endpoints[endpoint].status = "cancelled"

    def update_state(self, state: AppState) -> None:
        """Update the state reference and refresh."""
        self.state = state
        self.refresh()
