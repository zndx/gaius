"""Info panel for displaying brief contextual information."""

from textual.widget import Widget
from textual.widgets import Static, Markdown
from textual.containers import VerticalScroll
from textual.binding import Binding
from rich.text import Text
from rich.markdown import Markdown as RichMarkdown

from ..core.state import AppState


class InfoPanel(Widget, can_focus=True):
    """Right panel for displaying brief contextual information.

    Shows:
    - Transient status messages and progress indicators
    - Agent output during swarm rounds
    - Contextual information based on cursor position

    For heavy/final output, use NoteEditor via _show_output() instead.
    Arrow keys scroll content when focused (without entering edit mode).
    """

    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("pageup", "page_up", "Page up", show=False),
        Binding("pagedown", "page_down", "Page down", show=False),
        Binding("home", "scroll_home", "Scroll to top", show=False),
        Binding("end", "scroll_end", "Scroll to bottom", show=False),
    ]

    DEFAULT_CSS = """
    InfoPanel {
        width: 100%;
        height: 100%;
        background: $surface;
        border-left: solid $primary-darken-2;
    }

    InfoPanel > VerticalScroll {
        width: 100%;
        height: 100%;
    }

    InfoPanel .content-header {
        background: $primary-darken-3;
        padding: 0 1;
        text-style: bold;
    }

    InfoPanel .content-body {
        padding: 1;
    }

    InfoPanel .agent-output {
        border-bottom: dashed $surface-lighten-1;
        padding: 1;
        margin-bottom: 1;
    }

    InfoPanel .agent-name {
        text-style: bold;
    }
    """

    def __init__(
        self,
        state: AppState,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.state = state
        self._content = ""
        self._content_type = "text"  # "text", "markdown", "agent"
        self._title = "Content"

    def compose(self):
        """Compose the content panel."""
        yield Static(self._title, classes="content-header", id="content-header")
        with VerticalScroll():
            yield Static("Select a file or agent to view content.",
                        classes="content-body", id="content-body")

    def show_file(self, path: str, content: str) -> None:
        """Display file content."""
        self._title = path.split("/")[-1]
        self._content = content
        self._content_type = "markdown" if path.endswith(".md") else "text"

        header = self.query_one("#content-header", Static)
        header.update(f"📄 {self._title}")

        body = self.query_one("#content-body", Static)
        if self._content_type == "markdown":
            body.update(RichMarkdown(content))
        else:
            body.update(content)

    def show_agent(self, name: str, role: str, output: str, color: str = "white") -> None:
        """Display agent information and output."""
        self._title = f"Agent: {name}"
        self._content_type = "agent"

        header = self.query_one("#content-header", Static)
        header.update(f"🤖 {name}")

        text = Text()
        text.append("Role: ", style="dim")
        text.append(role, style="italic")
        text.append("\n\n")
        text.append("Last Output:\n", style="dim")
        text.append(output, style=color)

        body = self.query_one("#content-body", Static)
        body.update(text)

    def show_position_info(self, x: int, y: int, hint: str) -> None:
        """Display information about a grid position."""
        coord = self._coord_string(x, y)
        self._title = f"Position {coord}"

        header = self.query_one("#content-header", Static)
        header.update(f"📍 {coord}")

        text = Text()
        text.append(f"Coordinates: ", style="dim")
        text.append(f"{coord} ({x}, {y})\n\n", style="bold")
        text.append("Context:\n", style="dim")
        text.append(hint)

        body = self.query_one("#content-body", Static)
        body.update(text)

    def show_swarm_output(self, agents_output: list[tuple[str, str, str]]) -> None:
        """Display output from a swarm round.

        Args:
            agents_output: List of (name, color, output) tuples
        """
        self._title = "Swarm Round"
        self._content_type = "swarm"

        header = self.query_one("#content-header", Static)
        header.update("🐝 Swarm Output")

        text = Text()
        for name, color, output in agents_output:
            text.append(f"[{name}]", style=f"bold {color}")
            text.append("\n")
            text.append(output)
            text.append("\n\n")

        body = self.query_one("#content-body", Static)
        body.update(text)

    def clear(self) -> None:
        """Clear the content panel."""
        header = self.query_one("#content-header", Static)
        header.update("Content")

        body = self.query_one("#content-body", Static)
        body.update("Select a file or agent to view content.")

    def _coord_string(self, x: int, y: int) -> str:
        """Convert x, y to Go coordinate string."""
        col = chr(65 + x + (1 if x >= 8 else 0))  # Skip 'I'
        row = 19 - y
        return f"{col}{row}"

    # ─────────────────────────────────────────────────────────────────────
    # Scroll Actions (arrow keys when focused)
    # ─────────────────────────────────────────────────────────────────────

    def action_scroll_up(self) -> None:
        """Scroll content up by one line."""
        scroll = self.query_one(VerticalScroll)
        scroll.scroll_relative(y=-2)

    def action_scroll_down(self) -> None:
        """Scroll content down by one line."""
        scroll = self.query_one(VerticalScroll)
        scroll.scroll_relative(y=2)

    def action_page_up(self) -> None:
        """Scroll content up by one page."""
        scroll = self.query_one(VerticalScroll)
        scroll.scroll_page_up()

    def action_page_down(self) -> None:
        """Scroll content down by one page."""
        scroll = self.query_one(VerticalScroll)
        scroll.scroll_page_down()

    def action_scroll_home(self) -> None:
        """Scroll to top of content."""
        scroll = self.query_one(VerticalScroll)
        scroll.scroll_home()

    def action_scroll_end(self) -> None:
        """Scroll to bottom of content."""
        scroll = self.query_one(VerticalScroll)
        scroll.scroll_end()
