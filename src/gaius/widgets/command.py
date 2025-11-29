"""Command input widget (Claude Code style)."""

from textual.widget import Widget
from textual.widgets import Input
from textual.containers import Horizontal
from textual.message import Message
from rich.text import Text

from ..core.state import AppState


class CommandSubmitted(Message):
    """Message sent when a command is submitted."""

    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command


class CommandInput(Widget):
    """Bottom command input bar.

    Supports:
    - Slash commands (/analyze, /domain, etc.)
    - History navigation (up/down arrows)
    - Tab completion (planned)
    """

    DEFAULT_CSS = """
    CommandInput {
        width: 100%;
        height: 3;
        dock: bottom;
        background: $surface-darken-1;
        border-top: solid $primary-darken-2;
    }

    CommandInput > Horizontal {
        width: 100%;
        height: 100%;
        padding: 0 1;
    }

    CommandInput .prompt {
        width: auto;
        height: 1;
        padding: 0 1 0 0;
        content-align: left middle;
    }

    CommandInput Input {
        width: 1fr;
        height: 1;
        border: none;
        background: transparent;
    }

    CommandInput Input:focus {
        border: none;
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
        self.can_focus = False  # Remove from tab cycle; use '/' to activate
        self.state = state
        self._prompt = ">"
        self._in_command_mode = False

    def compose(self):
        """Compose the command input."""
        with Horizontal():
            yield Input(placeholder="Press / for commands, ? for help", id="cmd-input")

    def on_mount(self) -> None:
        """Set up the input."""
        self._input = self.query_one("#cmd-input", Input)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command submission."""
        value = event.value.strip()
        if value:
            self.state.add_command(value)
            self.post_message(CommandSubmitted(value))
        self._input.value = ""
        self._in_command_mode = False

    def on_key(self, event) -> None:
        """Handle special keys for history navigation."""
        if event.key == "up":
            prev = self.state.prev_command()
            if prev is not None:
                self._input.value = prev
                self._input.cursor_position = len(prev)
                event.stop()
        elif event.key == "down":
            next_cmd = self.state.next_command()
            if next_cmd is not None:
                self._input.value = next_cmd
                self._input.cursor_position = len(next_cmd)
                event.stop()
        elif event.key == "escape":
            self._input.value = ""
            self._in_command_mode = False
            self.app.set_focus(None)
            event.stop()

    def enter_command_mode(self, initial: str = "") -> None:
        """Enter command mode and focus the input."""
        self._in_command_mode = True
        self._input.value = initial
        self._input.cursor_position = len(initial)
        self._input.focus()

    def set_prompt(self, prompt: str) -> None:
        """Update the prompt text."""
        self._prompt = prompt
        self.refresh()

    @property
    def in_command_mode(self) -> bool:
        """Check if currently in command mode."""
        return self._in_command_mode
