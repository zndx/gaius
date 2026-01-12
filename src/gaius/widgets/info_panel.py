"""Info panel for displaying brief contextual information."""

import re
import logging
from textual.widget import Widget
from textual.widgets import Static, Markdown
from textual.containers import VerticalScroll
from textual.binding import Binding
from rich.text import Text
from rich.markdown import Markdown as RichMarkdown

from ..core.state import AppState

logger = logging.getLogger(__name__)

# Regex to detect emoji characters that may break TUI rendering.
# Covers common emoji ranges: emoticons, symbols, dingbats, transport, misc.
# Note: This is not exhaustive but catches the most common TUI-breaking emojis.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F9FF"  # Misc Symbols, Emoticons, Dingbats, etc.
    "\U00002600-\U000027BF"  # Misc symbols (sun, stars, arrows, etc.)
    "\U0001FA00-\U0001FAFF"  # Chess, symbols
    "\U00002300-\U000023FF"  # Misc technical (hourglass, keyboard, etc.)
    "\U0001F600-\U0001F64F"  # Emoticons
    "]+",
    flags=re.UNICODE,
)


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
        self._emoji_warning_emitted: set[str] = set()  # Dedupe warnings per content hash

    def _check_emoji_content(self, content: str, source: str) -> None:
        """Check content for emojis and emit OTel event if found.

        Emojis break TUI rendering and should be replaced with ASCII
        text markers before reaching the InfoPanel. This detection
        provides fail-fast observability so developers can fix the
        source of emoji content.

        Args:
            content: The content string to check
            source: Identifier for the content source (e.g., "show_file:health_fix.md")
        """
        matches = _EMOJI_PATTERN.findall(content)
        if not matches:
            return

        # Dedupe: only warn once per unique (source, emoji_set) combination
        emoji_key = f"{source}:{','.join(sorted(set(''.join(matches))))}"
        if emoji_key in self._emoji_warning_emitted:
            return
        self._emoji_warning_emitted.add(emoji_key)

        # Extract unique emojis found
        unique_emojis = sorted(set("".join(matches)))
        emoji_sample = "".join(unique_emojis[:5])  # Show first 5 unique

        # Log warning with actionable context
        logger.warning(
            "Emoji content detected in InfoPanel - will break TUI rendering. "
            "Guru Meditation: #TUI.00000001.EMOJI | "
            f"source={source} emojis={emoji_sample!r} count={len(matches)}"
        )

        # Emit OTel metric for Observe panel visibility
        try:
            from ..engine.metrics import record_exception_caught
            record_exception_caught(
                component="tui",
                operation="info_panel_render",
                exception_type="EmojiContentWarning",
                failure_mode_id="TUI_001",
                guru_code="#TUI.00000001.EMOJI",
            )
        except ImportError:
            # Engine metrics not available (e.g., standalone widget test)
            pass

    def compose(self):
        """Compose the content panel."""
        yield Static(self._title, classes="content-header", id="content-header")
        with VerticalScroll():
            yield Static("Select a file or agent to view content.",
                        classes="content-body", id="content-body")

    def show_file(self, path: str, content: str) -> None:
        """Display file content."""
        # Check for emoji content and emit OTel warning if found
        self._check_emoji_content(content, f"show_file:{path}")

        self._title = path.split("/")[-1]
        self._content = content
        self._content_type = "markdown" if path.endswith(".md") else "text"

        header = self.query_one("#content-header", Static)
        header.update(f"[FILE] {self._title}")

        body = self.query_one("#content-body", Static)
        if self._content_type == "markdown":
            body.update(RichMarkdown(content))
        else:
            body.update(content)

    def show_agent(self, name: str, role: str, output: str, color: str = "white") -> None:
        """Display agent information and output."""
        # Check for emoji content and emit OTel warning if found
        self._check_emoji_content(output, f"show_agent:{name}")

        self._title = f"Agent: {name}"
        self._content_type = "agent"

        header = self.query_one("#content-header", Static)
        header.update(f"[AGENT] {name}")

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
        # Check for emoji content and emit OTel warning if found
        self._check_emoji_content(hint, f"show_position_info:{x},{y}")

        coord = self._coord_string(x, y)
        self._title = f"Position {coord}"

        header = self.query_one("#content-header", Static)
        header.update(f"[POS] {coord}")

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
        # Check for emoji content in all agent outputs
        for name, _color, output in agents_output:
            self._check_emoji_content(output, f"show_swarm_output:{name}")

        self._title = "Swarm Round"
        self._content_type = "swarm"

        header = self.query_one("#content-header", Static)
        header.update("[SWARM] Output")

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
