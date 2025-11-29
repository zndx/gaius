"""Note editor widget for Zettelkasten scratch notes with vim-style editing."""

import time
from pathlib import Path

from textual.widget import Widget
from textual.widgets import TextArea, Static
from textual.containers import Vertical
from textual.reactive import reactive
from textual.message import Message
from textual.binding import Binding
from textual import events


class VimTextArea(TextArea):
    """TextArea that sends ESC to parent for vim-style mode switching."""

    class EscapePressed(Message):
        """Sent when ESC is pressed in the TextArea."""
        pass

    def _on_key(self, event: events.Key) -> None:
        """Intercept ESC before TextArea handles it."""
        if event.key == "escape":
            self.post_message(self.EscapePressed())
            event.prevent_default()
            event.stop()
            return
        # Let TextArea handle other keys normally
        super()._on_key(event)


class NoteEditor(Widget, can_focus=True):
    """Vim-style modal editor for scratch notes.

    Uses Zettelkasten naming: Unix timestamp as filename.
    Notes are saved to build/dev/scratch/{date}/{timestamp}.md

    Vim keys:
    - ESC: Exit insert mode (enter normal mode)
    - i: Insert at cursor
    - I: Insert at line beginning
    - A: Append at line end
    - o: Open line below
    - O: Open line above
    - :q or :wq: Close editor (auto-saves, so w is no-op)
    """

    DEFAULT_CSS = """
    NoteEditor {
        width: 100%;
        height: 100%;
        background: $surface-darken-1;
        border: solid $primary-darken-2;
    }

    NoteEditor TextArea {
        width: 100%;
        height: 1fr;
    }

    NoteEditor .mode-indicator {
        width: 100%;
        height: 1;
        background: $primary-darken-3;
        color: $text;
        padding: 0 1;
    }

    NoteEditor .mode-indicator.insert-mode {
        background: $success-darken-2;
    }

    NoteEditor .command-line {
        width: 100%;
        height: 1;
        background: $surface-darken-2;
        color: $text;
        padding: 0 1;
    }

    NoteEditor .command-line.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("escape", "normal_mode", "Normal", show=False),
    ]

    current_file: reactive[str | None] = reactive(None)
    insert_mode: reactive[bool] = reactive(False)
    command_buffer: reactive[str] = reactive("")

    class NoteSaved(Message):
        """Emitted when a note is saved."""
        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class NoteCreated(Message):
        """Emitted when a new note is created."""
        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class EditorClosed(Message):
        """Emitted when editor is closed via :q."""
        pass

    def __init__(
        self,
        scratch_dir: str = "build/dev/scratch",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.scratch_dir = Path(scratch_dir)
        self._editor: TextArea | None = None
        self._mode_indicator: Static | None = None
        self._command_line: Static | None = None
        self._in_command_mode = False

    def compose(self):
        """Compose the editor widget."""
        with Vertical():
            # Mode indicator at top
            self._mode_indicator = Static("NORMAL", classes="mode-indicator")
            yield self._mode_indicator

            # VimTextArea for editing (sends ESC to parent)
            self._editor = VimTextArea(
                "",
                id="note-text",
                soft_wrap=True,
                tab_behavior="indent",
                show_line_numbers=False,
            )
            yield self._editor

            # Command line at bottom (for :commands)
            self._command_line = Static("", classes="command-line hidden")
            yield self._command_line

    def on_vim_text_area_escape_pressed(self, event: VimTextArea.EscapePressed) -> None:
        """Handle ESC from TextArea - switch to normal mode."""
        self.action_normal_mode()

    def on_mount(self) -> None:
        """Initialize on mount."""
        self._update_mode_display()
        # Start in normal mode - TextArea not focusable
        if self._editor:
            self._editor.read_only = True
            self._editor.can_focus = False

    def _update_mode_display(self) -> None:
        """Update the mode indicator."""
        if self._mode_indicator:
            if self._in_command_mode:
                self._mode_indicator.update(f":{self.command_buffer}")
            elif self.insert_mode:
                self._mode_indicator.update("-- INSERT --")
                self._mode_indicator.add_class("insert-mode")
            else:
                self._mode_indicator.update(f"NORMAL  {self.filename}")
                self._mode_indicator.remove_class("insert-mode")

    def watch_insert_mode(self, value: bool) -> None:
        """React to insert mode changes."""
        if self._editor:
            self._editor.read_only = not value
            # In normal mode, disable TextArea focus so NoteEditor gets keys
            self._editor.can_focus = value
            if value:
                self._editor.focus()
            else:
                # Focus the NoteEditor widget itself for normal mode
                self.focus()
        self._update_mode_display()

    def watch_command_buffer(self, value: str) -> None:
        """React to command buffer changes."""
        self._update_mode_display()

    def action_normal_mode(self) -> None:
        """Exit insert mode, enter normal mode."""
        if self._in_command_mode:
            self._in_command_mode = False
            self.command_buffer = ""
        self.insert_mode = False
        self._update_mode_display()
        # Keep focus on the widget for normal mode commands
        self.focus()

    def _enter_insert_mode(self, position: str = "cursor") -> None:
        """Enter insert mode at specified position."""
        if not self._editor:
            return

        self.insert_mode = True

        # Position cursor based on vim command
        if position == "line_start":
            # I - insert at beginning of line
            row, _ = self._editor.cursor_location
            self._editor.cursor_location = (row, 0)
        elif position == "line_end":
            # A - append at end of line
            row, _ = self._editor.cursor_location
            line = self._editor.document.get_line(row)
            self._editor.cursor_location = (row, len(line))
        elif position == "line_below":
            # o - open line below
            row, _ = self._editor.cursor_location
            line = self._editor.document.get_line(row)
            self._editor.cursor_location = (row, len(line))
            self._editor.insert("\n")
        elif position == "line_above":
            # O - open line above
            row, _ = self._editor.cursor_location
            self._editor.cursor_location = (row, 0)
            self._editor.insert("\n")
            self._editor.cursor_location = (row, 0)
        # else: cursor - insert at current position (i)

    def _enter_command_mode(self) -> None:
        """Enter ex command mode (:)."""
        self._in_command_mode = True
        self.command_buffer = ""
        self._update_mode_display()

    def _execute_command(self, cmd: str) -> None:
        """Execute an ex command."""
        cmd = cmd.strip().lower()

        if cmd in ("q", "wq", "q!", "wq!"):
            # Close editor (w is no-op since we auto-save)
            self.close_editor()
            self.post_message(self.EditorClosed())
        elif cmd == "w":
            # Explicit save (no-op, but acknowledge)
            self._update_mode_display()

        self._in_command_mode = False
        self.command_buffer = ""

    def on_key(self, event: events.Key) -> None:
        """Handle key presses for vim-style navigation."""
        # In insert mode, only handle ESC to exit to normal mode
        if self.insert_mode:
            if event.key == "escape":
                self.action_normal_mode()
                event.prevent_default()
                event.stop()
            return

        # In command mode, build command string
        if self._in_command_mode:
            if event.key == "enter":
                self._execute_command(self.command_buffer)
                event.prevent_default()
                event.stop()
            elif event.key == "escape":
                self._in_command_mode = False
                self.command_buffer = ""
                self._update_mode_display()
                event.prevent_default()
                event.stop()
            elif event.key == "backspace":
                if self.command_buffer:
                    self.command_buffer = self.command_buffer[:-1]
                else:
                    self._in_command_mode = False
                self._update_mode_display()
                event.prevent_default()
                event.stop()
            elif event.character and event.character.isprintable():
                self.command_buffer += event.character
                self._update_mode_display()
                event.prevent_default()
                event.stop()
            return

        # Normal mode commands
        if event.character == "i":
            self._enter_insert_mode("cursor")
            event.prevent_default()
            event.stop()
        elif event.character == "I":
            self._enter_insert_mode("line_start")
            event.prevent_default()
            event.stop()
        elif event.character == "A":
            self._enter_insert_mode("line_end")
            event.prevent_default()
            event.stop()
        elif event.character == "a":
            # Append after cursor
            if self._editor:
                row, col = self._editor.cursor_location
                line = self._editor.document.get_line(row)
                if col < len(line):
                    self._editor.cursor_location = (row, col + 1)
            self._enter_insert_mode("cursor")
            event.prevent_default()
            event.stop()
        elif event.character == "o":
            self._enter_insert_mode("line_below")
            event.prevent_default()
            event.stop()
        elif event.character == "O":
            self._enter_insert_mode("line_above")
            event.prevent_default()
            event.stop()
        elif event.character == ":":
            self._enter_command_mode()
            event.prevent_default()
            event.stop()
        # Navigation in normal mode (hjkl)
        elif event.character == "h" and self._editor:
            row, col = self._editor.cursor_location
            if col > 0:
                self._editor.cursor_location = (row, col - 1)
            event.prevent_default()
            event.stop()
        elif event.character == "j" and self._editor:
            row, col = self._editor.cursor_location
            if row < self._editor.document.line_count - 1:
                self._editor.cursor_location = (row + 1, col)
            event.prevent_default()
            event.stop()
        elif event.character == "k" and self._editor:
            row, col = self._editor.cursor_location
            if row > 0:
                self._editor.cursor_location = (row - 1, col)
            event.prevent_default()
            event.stop()
        elif event.character == "l" and self._editor:
            row, col = self._editor.cursor_location
            line = self._editor.document.get_line(row)
            if col < len(line) - 1:
                self._editor.cursor_location = (row, col + 1)
            event.prevent_default()
            event.stop()

    def new_note(self) -> str:
        """Create a new Zettelkasten note with timestamp filename."""
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        date_dir = self.scratch_dir / today
        date_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        filename = f"{timestamp}.md"
        filepath = date_dir / filename
        filepath.touch()

        self.current_file = str(filepath)

        if self._editor:
            self._editor.clear()

        # Start in insert mode for new notes
        self._enter_insert_mode("cursor")

        self.post_message(self.NoteCreated(str(filepath)))
        return str(filepath)

    def open_note(self, path: str) -> None:
        """Open an existing note for editing."""
        filepath = Path(path)
        if filepath.exists():
            content = filepath.read_text()
            if self._editor:
                self._editor.load_text(content)
                self._editor.read_only = True  # Start in normal mode
            self.current_file = str(filepath)
            self.insert_mode = False
            self._update_mode_display()
            self.focus()

    def close_editor(self) -> None:
        """Close the editor and clear state."""
        self.current_file = None
        self.insert_mode = False
        self._in_command_mode = False
        self.command_buffer = ""
        if self._editor:
            self._editor.clear()
            self._editor.read_only = True
        self.add_class("hidden")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Auto-save on every change."""
        if self.current_file and self._editor:
            filepath = Path(self.current_file)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(self._editor.text)

    @property
    def filename(self) -> str:
        """Get the current filename for display."""
        if self.current_file:
            return Path(self.current_file).name
        return "(no file)"

    def focus_editor(self) -> None:
        """Focus the editor (enters normal mode)."""
        self.focus()
        self._update_mode_display()
