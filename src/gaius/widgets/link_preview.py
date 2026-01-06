"""Link preview widget - shows foreknowledge of what graph nodes will do."""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text


class LinkPreview(Widget):
    """Displays preview of what a selected graph node will open or execute.

    Shows compact, literal display of the target:
    - ◉ current file path
    - ○ forward link document path
    - ● backlink document path
    - ◇ action:/command args

    Single line, exactly aligned with LocationIndicator below MainGrid.
    Matches LocationIndicator's visual style.
    """

    DEFAULT_CSS = """
    LinkPreview {
        width: 40;
        height: 1;
    }
    """

    node_type: reactive[str] = reactive("none")
    target_path: reactive[str] = reactive("")
    action_command: reactive[str] = reactive("")

    def watch_node_type(self, old_value: str, new_value: str) -> None:
        """React to node_type changes by refreshing."""
        self.refresh()

    def watch_target_path(self, old_value: str, new_value: str) -> None:
        """React to target_path changes by refreshing."""
        self.refresh()

    def render(self) -> Text:
        """Render the link preview display."""
        # Empty state - return space to ensure widget background renders
        if self.node_type == "none" or (not self.target_path and not self.action_command):
            return Text(" ")

        # Symbol prefix based on node type
        if self.node_type == "current":
            symbol = "◉"
        elif self.node_type == "forward":
            symbol = "○"
        elif self.node_type == "backlink":
            symbol = "●"
        elif self.node_type == "action":
            symbol = "◇"
        else:
            symbol = " "

        # Content: path for documents, command for actions
        if self.node_type == "action" and self.action_command:
            content = f"action:{self.action_command}"
        else:
            # Strip KB root prefix (build/dev/) for cleaner display
            content = self.target_path
            if content.startswith("build/dev/"):
                content = content[10:]  # len("build/dev/") == 10

        return Text(f"{symbol} {content}")

    def update_from_node(
        self,
        node_type: str,
        filepath: str | None = None,
        command: str | None = None,
    ) -> None:
        """Update the preview from graph node data.

        Args:
            node_type: One of "current", "forward", "backlink", "action", "none"
            filepath: Document path for document nodes
            command: Slash command for action nodes
        """
        self.node_type = node_type
        self.target_path = filepath or ""
        self.action_command = command or ""
        # Force full refresh to ensure render is called
        self.refresh(layout=True)

    def clear(self) -> None:
        """Clear the preview (no selection)."""
        self.node_type = "none"
        self.target_path = ""
        self.action_command = ""
        self.refresh()
