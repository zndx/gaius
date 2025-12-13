"""Connection status indicator for thin TUI architecture.

Displays connection status to the Engine, showing:
- Pending: Not yet attempted (○)
- Connecting: Connection in progress (◐)
- Connected: Successfully connected (●)
- Offline: Engine unavailable, using cached state (◯)
- Error: Connection failed with error (✗)
"""

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from ..client.state_client import ConnectionStatus


class ConnectionIndicator(Static):
    """Connection status indicator widget.

    Shows a compact status icon that updates based on connection state.
    Designed to be placed in the header/footer area.

    Attributes:
        status: Current connection status
    """

    DEFAULT_CSS = """
    ConnectionIndicator {
        height: 1;
        width: auto;
        padding: 0 1;
    }
    """

    ICONS = {
        ConnectionStatus.PENDING: ("○", "dim"),
        ConnectionStatus.CONNECTING: ("◐", "yellow"),
        ConnectionStatus.CONNECTED: ("●", "green"),
        ConnectionStatus.OFFLINE: ("◯", "dim white"),
        ConnectionStatus.ERROR: ("✗", "red"),
    }

    LABELS = {
        ConnectionStatus.PENDING: "Pending",
        ConnectionStatus.CONNECTING: "Connecting",
        ConnectionStatus.CONNECTED: "Connected",
        ConnectionStatus.OFFLINE: "Offline",
        ConnectionStatus.ERROR: "Error",
    }

    status: reactive[ConnectionStatus] = reactive(ConnectionStatus.PENDING)

    def __init__(
        self,
        show_label: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ):
        """Initialize connection indicator.

        Args:
            show_label: Whether to show text label next to icon
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(id=id, classes=classes)
        self._show_label = show_label

    def render(self) -> str:
        """Render the connection indicator."""
        icon, color = self.ICONS.get(self.status, ("?", "red"))
        label = self.LABELS.get(self.status, "Unknown")

        if self._show_label:
            return f"[{color}]{icon}[/] {label}"
        else:
            return f"[{color}]{icon}[/]"

    def watch_status(self, old_value: ConnectionStatus, new_value: ConnectionStatus) -> None:
        """Handle status changes."""
        self.refresh()


class ConnectionStatusBar(Static):
    """Extended connection status bar with details.

    Shows icon, status text, and optional details like:
    - Generation number
    - Last update time
    - Cache indicator
    """

    DEFAULT_CSS = """
    ConnectionStatusBar {
        height: 1;
        width: 100%;
        background: $surface;
        padding: 0 1;
    }

    ConnectionStatusBar.offline {
        background: $surface-darken-1;
    }

    ConnectionStatusBar.error {
        background: $error-darken-2;
    }
    """

    status: reactive[ConnectionStatus] = reactive(ConnectionStatus.PENDING)
    generation: reactive[int] = reactive(0)
    from_cache: reactive[bool] = reactive(False)

    ICONS = {
        ConnectionStatus.PENDING: ("○", "dim"),
        ConnectionStatus.CONNECTING: ("◐", "yellow"),
        ConnectionStatus.CONNECTED: ("●", "green"),
        ConnectionStatus.OFFLINE: ("◯", "dim white"),
        ConnectionStatus.ERROR: ("✗", "red"),
    }

    def render(self) -> str:
        """Render the status bar."""
        icon, color = self.ICONS.get(self.status, ("?", "red"))

        parts = [f"[{color}]{icon}[/]"]

        if self.status == ConnectionStatus.CONNECTED:
            parts.append("[green]Engine[/]")
            if self.generation > 0:
                parts.append(f"[dim]gen:{self.generation}[/]")
        elif self.status == ConnectionStatus.OFFLINE:
            parts.append("[dim]Offline[/]")
            if self.from_cache:
                parts.append("[dim italic](cached)[/]")
        elif self.status == ConnectionStatus.CONNECTING:
            parts.append("[yellow]Connecting...[/]")
        elif self.status == ConnectionStatus.ERROR:
            parts.append("[red]Connection Error[/]")
        else:
            parts.append("[dim]Pending[/]")

        return " ".join(parts)

    def watch_status(self, old_value: ConnectionStatus, new_value: ConnectionStatus) -> None:
        """Handle status changes."""
        # Update CSS classes based on status
        self.remove_class("offline", "error")
        if new_value == ConnectionStatus.OFFLINE:
            self.add_class("offline")
        elif new_value == ConnectionStatus.ERROR:
            self.add_class("error")
        self.refresh()

    def watch_generation(self) -> None:
        """Handle generation changes."""
        self.refresh()

    def watch_from_cache(self) -> None:
        """Handle cache indicator changes."""
        self.refresh()
