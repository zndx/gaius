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

from ..engine.generated.gaius_service_pb2 import InitEvent

from textual.widget import Widget
from textual.reactive import reactive
from textual.message import Message

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

    class XBAuthCompleted(Message):
        """Posted when XB OAuth authentication completes.

        This message bubbles up to the app to dismiss the QR code modal.
        """

        def __init__(self, username: str) -> None:
            self.username = username
            super().__init__()

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

    # Reactive for XB countdown timer (triggers refresh every second)
    xb_countdown_seconds = reactive(0)

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
            lines.append(Text("[=] PAUSED (user request)", style="yellow"))

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

        # ── X Bookmarks Status Section (always show) ──
        lines.append(Text(""))
        lines.append(Text("X Bookmarks", style="bold cyan"))
        lines.append(Text("-" * 36, style="dim"))

        # Auth status: shows authenticated user or auth needed
        auth_line = Text()
        auth_line.append("  Auth: ", style="dim")
        if init_state.xb_authenticated and init_state.xb_username:
            # Show username - TOKEN_EXPIRING is just a warning, token still works
            if init_state.xb_action_required == "TOKEN_EXPIRED":
                # Token actually expired - reauth required
                auth_line.append("reauth needed", style="yellow")
            elif init_state.xb_action_required == "TOKEN_EXPIRING":
                # Token expiring soon - show username with warning
                auth_line.append(f"@{init_state.xb_username}", style="yellow")
            else:
                # Token is healthy
                auth_line.append(f"@{init_state.xb_username}", style="green")
        elif init_state.xb_action_required:
            # Not authenticated - show specific action needed
            action_display = {
                "NOT_AUTHENTICATED": "auth needed",
                "TOKEN_EXPIRED": "reauth needed",
            }.get(init_state.xb_action_required, init_state.xb_action_required.lower())
            auth_line.append(action_display, style="yellow")
        else:
            auth_line.append("auth needed", style="yellow")
        lines.append(auth_line)

        # Queue depth (only show if items pending)
        if init_state.xb_queue_depth > 0:
            queue_line = Text()
            queue_line.append("  Queue: ", style="dim")
            queue_line.append(f"{init_state.xb_queue_depth}", style="white")
            queue_line.append(" pending", style="dim")
            lines.append(queue_line)

        # Cooldown timer (only show if active)
        if init_state.xb_cooldown_end and self.xb_countdown_seconds > 0:
            mins, secs = divmod(self.xb_countdown_seconds, 60)
            timer_line = Text()
            timer_line.append("  Cooldown: ", style="dim")
            timer_line.append(f"{mins:02d}:{secs:02d}", style="yellow")
            lines.append(timer_line)

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
        elif init_state.phase == "reconnecting":
            conn_line.append("◌ ", style="yellow")
            conn_line.append("gRPC: ", style="yellow")
            conn_line.append("reconnecting", style="yellow")
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
        elif init_state.phase == "reconnecting":
            border_style = "yellow"
            title = "[bold yellow]◌[/bold yellow] [bold]Init[/bold]"
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

    def _friendly_endpoint_name(self, name: str) -> str:
        """Convert internal endpoint name to user-friendly display name.

        Strips internal prefixes like 'cap_' that are implementation details.
        """
        if name.startswith("cap_"):
            return name[4:]  # Remove "cap_" prefix
        return name

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

        # Name (truncated) - use friendly name for display
        friendly_name = self._friendly_endpoint_name(name)
        name_display = friendly_name[:12].ljust(12)
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
        """Start the gRPC stream and countdown timer when mounted."""
        self._stream_task = asyncio.create_task(self._connect_init_stream())
        # Start 1-second countdown timer for XB cooldown display
        self.set_interval(1.0, self._tick_xb_countdown)

    def on_unmount(self) -> None:
        """Clean up the stream task."""
        if self._stream_task:
            self._stream_task.cancel()

    def _tick_xb_countdown(self) -> None:
        """Decrement XB countdown timer and refresh display.

        Called every second by set_interval. Calculates remaining time
        from xb_cooldown_end and updates the reactive countdown value.
        """
        from datetime import datetime, timezone

        init_state = self.state.initialization_state
        if init_state.xb_cooldown_end:
            now = datetime.now(timezone.utc)
            remaining = (init_state.xb_cooldown_end - now).total_seconds()
            if remaining > 0:
                self.xb_countdown_seconds = int(remaining)
            else:
                # Cooldown expired
                self.xb_countdown_seconds = 0
                init_state.xb_cooldown_end = None
                init_state.xb_can_request = True

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

            # Subscribe to init stream - keep listening for XB events even after READY
            async for event in client.init_stream():
                self._update_from_event(event)
                self.init_progress = self.state.initialization_state.overall_progress  # type: ignore[misc] - Reactive property assignment
                self.refresh()
                # Don't break on READY - we need to keep listening for XB events
                # The stream stays open until panel is unmounted

        except Exception as e:
            logger.debug(f"InitStream error: {e}")
            # Fall back to polling if stream fails
            await self._poll_init_status()

    async def _poll_init_status(self) -> None:
        """Fallback: poll for init status if streaming fails.

        Polls forever to handle dynamic connection state changes (engine
        restarts, network reconnections). Uses exponential backoff during
        failures to avoid spamming logs.
        """
        logger.debug("InitPanel falling back to polling mode")

        consecutive_failures = 0
        base_retry_interval = 5.0
        max_retry_interval = 30.0

        while True:  # Poll forever - connection may come and go
            try:
                from ..client.engine_proxy import get_health_proxy

                health = await get_health_proxy()
                status = await health.check()

                # Update state from health check
                init_state = self.state.initialization_state
                init_state.connected = True
                init_state.error = None  # Clear any previous error

                # Log reconnection if we were previously disconnected
                if consecutive_failures > 0:
                    logger.info(f"InitPanel: reconnected after {consecutive_failures} failures")

                consecutive_failures = 0  # Reset on success

                # Populate endpoints from health status
                endpoints = status.get("endpoints", {})
                healthy_count = 0

                # Track which endpoints are still active
                active_endpoints = set()

                for ep_name, ep_data in endpoints.items():
                    active_endpoints.add(ep_name)
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

                # Remove endpoints that are no longer in the health response
                stale_endpoints = [name for name in init_state.endpoints if name not in active_endpoints]
                for name in stale_endpoints:
                    del init_state.endpoints[name]

                if healthy_count > 0:
                    init_state.is_ready = True
                    init_state.overall_progress = 1.0
                    init_state.phase = "ready"
                    init_state.message = f"{healthy_count} endpoint{'s' if healthy_count != 1 else ''} healthy"
                else:
                    init_state.is_ready = False
                    init_state.phase = "waiting"
                    init_state.message = "No healthy endpoints"

                # Fetch XB queue status for cooldown timer
                await self._fetch_xb_queue_status(init_state)

                self.refresh()

                # Poll every 5 seconds when healthy, 2 seconds during init
                poll_interval = 5.0 if init_state.is_ready else 2.0
                await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                logger.debug("InitPanel polling cancelled")
                return

            except Exception as e:
                consecutive_failures += 1
                init_state = self.state.initialization_state
                init_state.connected = False
                init_state.phase = "reconnecting"

                # Show retry attempt in message
                init_state.message = f"Reconnecting... (attempt {consecutive_failures})"
                init_state.error = str(e)[:40]

                # Only log first failure and then periodically
                if consecutive_failures == 1:
                    logger.debug(f"InitPanel: gRPC connection lost: {e}")
                elif consecutive_failures % 10 == 0:
                    logger.debug(f"InitPanel: still reconnecting after {consecutive_failures} attempts")

                self.refresh()

                # Exponential backoff with cap
                retry_interval = min(
                    base_retry_interval * (1.5 ** min(consecutive_failures - 1, 5)),
                    max_retry_interval
                )
                await asyncio.sleep(retry_interval)

    async def _fetch_xb_queue_status(self, init_state: InitializationState) -> None:
        """Fetch XB queue and auth status from engine.

        Non-fatal: if fetch fails, we just don't update the status.
        Fetches both queue status (for cooldown) and auth status (for auth state).
        """
        try:
            from datetime import datetime
            from ..client.grpc_client import get_grpc_client

            client = await get_grpc_client()

            # Fetch queue status for cooldown timer
            queue_status = await client.call("XBookmarks", "queue_status", {})

            init_state.xb_queue_depth = queue_status.get("queue_depth", 0)
            init_state.xb_can_request = queue_status.get("can_request", True)

            cooldown_end_iso = queue_status.get("cooldown_end_iso", "")
            if cooldown_end_iso:
                init_state.xb_cooldown_end = datetime.fromisoformat(cooldown_end_iso)
            else:
                init_state.xb_cooldown_end = None

            # Fetch auth status to show actual auth state
            auth_status = await client.call("XBookmarks", "auth_status", {})

            init_state.xb_authenticated = auth_status.get("authenticated", False)
            init_state.xb_username = auth_status.get("username", "")
            init_state.xb_action_required = auth_status.get("action_required", "")

        except Exception as e:
            # Non-fatal: just log and continue
            logger.debug(f"XB status fetch failed (non-fatal): {e}")

    def _update_from_event(self, event: dict) -> None:
        """Update initialization state from an InitEvent."""
        init_state = self.state.initialization_state
        init_state.connected = True

        # Use proto enum for type comparison when available, fall back to string
        event_type_enum = event.get("type_enum")
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

        # ── X Bookmarks Events (real-time push from engine) ──
        # Use proto enum for comparison when available
        # These events are traced with OTel for end-to-end visibility
        elif event_type_enum == InitEvent.Type.XB_AUTH_COMPLETED:
            self._handle_xb_auth_completed(init_state, data)

        elif event_type_enum == InitEvent.Type.XB_AUTH_FAILED:
            self._handle_xb_auth_failed(init_state, data)

        elif event_type_enum == InitEvent.Type.XB_STATUS_CHANGED:
            self._handle_xb_status_changed(init_state, data)

    def _handle_xb_auth_completed(
        self, init_state: InitializationState, data: dict | None
    ) -> None:
        """Handle XB_AUTH_COMPLETED event with OTel tracing.

        This is the final span in the XB auth event trace:
          trigger -> emit -> broadcast -> panel_update
        """
        from gaius.core.telemetry import get_tracer, XBAuthAttrs

        tracer = get_tracer()
        with tracer.start_as_current_span("xb.auth_event.panel_update") as span:
            span.set_attribute(XBAuthAttrs.EVENT_TYPE, "XB_AUTH_COMPLETED")

            username = data.get("username", "") if data else ""
            span.set_attribute(XBAuthAttrs.USERNAME, username)

            # Update state
            init_state.xb_authenticated = True
            init_state.xb_username = username
            init_state.xb_action_required = ""  # Clear any pending action

            span.add_event("xb.panel.state_updated", {
                "xb_authenticated": True,
                "xb_username": username,
            })

            self.refresh()
            span.add_event("xb.panel.refresh_triggered")

            logger.info(f"XB auth completed: @{username}")

            # Dismiss QR modal if showing (via app reference)
            # Import here to avoid circular import at module level
            from ..app import QRCodeModal
            if isinstance(self.app.screen, QRCodeModal):
                logger.info(f"Dismissing QR modal for @{username}")
                self.app.screen.dismiss()
                span.add_event("xb.qr_modal.dismissed")
            else:
                # Still post message for any other listeners
                self.post_message(self.XBAuthCompleted(username))
                span.add_event("xb.auth_completed.message_posted")

    def _handle_xb_auth_failed(
        self, init_state: InitializationState, data: dict | None
    ) -> None:
        """Handle XB_AUTH_FAILED event with OTel tracing."""
        from gaius.core.telemetry import get_tracer, XBAuthAttrs

        tracer = get_tracer()
        with tracer.start_as_current_span("xb.auth_event.panel_update") as span:
            span.set_attribute(XBAuthAttrs.EVENT_TYPE, "XB_AUTH_FAILED")

            error_msg = data.get("error", "unknown") if data else "unknown"

            # Update state
            init_state.xb_authenticated = False
            init_state.xb_action_required = "AUTH_FAILED"

            span.add_event("xb.panel.state_updated", {
                "xb_authenticated": False,
                "error": error_msg,
            })

            self.refresh()
            span.add_event("xb.panel.refresh_triggered")

            logger.warning(f"XB auth failed: {error_msg}")

    def _handle_xb_status_changed(
        self, init_state: InitializationState, data: dict | None
    ) -> None:
        """Handle XB_STATUS_CHANGED event with OTel tracing."""
        from gaius.core.telemetry import get_tracer, XBAuthAttrs

        tracer = get_tracer()
        with tracer.start_as_current_span("xb.auth_event.panel_update") as span:
            span.set_attribute(XBAuthAttrs.EVENT_TYPE, "XB_STATUS_CHANGED")

            if data:
                init_state.xb_queue_depth = data.get("queue_depth", init_state.xb_queue_depth)
                init_state.xb_can_request = data.get("can_request", init_state.xb_can_request)

                span.add_event("xb.panel.state_updated", {
                    "queue_depth": init_state.xb_queue_depth,
                    "can_request": init_state.xb_can_request,
                })

            self.refresh()
            span.add_event("xb.panel.refresh_triggered")

    def update_state(self, state: AppState) -> None:
        """Update the state reference and refresh."""
        self.state = state
        self.refresh()
