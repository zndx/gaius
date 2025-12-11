"""Splash screen widget - demoscene-style loading display.

Shows ASCII art and animated loading indicator while the app initializes.
Dismisses automatically when the app is ready for input (tab focus works).
"""

from rich.align import Align
from rich.console import Group, RenderableType
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget


# Demoscene-style ASCII art logo
GAIUS_LOGO = """\
     ╔══════════════════════════════════════════════════════════╗
     ║                                                          ║
     ║    ▄████▄      ▄████▄     ▀████▀   ██    ██    ▄█████▄   ║
     ║   ██    ██    ██    ██      ██     ██    ██   ██     ▀   ║
     ║   ██          ████████      ██     ██    ██    ▀█████▄   ║
     ║   ██  ▄███    ██    ██      ██     ██    ██         ██   ║
     ║   ██    ██    ██    ██      ██     ██    ██   █     ██   ║
     ║    ▀████▀     ██    ██    ▄████▄    ▀████▀     ▀█████▀   ║
     ║                                                          ║
     ╚══════════════════════════════════════════════════════════╝"""

# Attribution text
ATTRIBUTION = """\
     ╔══════════════════════════════════════════════════════════╗
     ║    G A I U S  ─  Topological Knowledge Navigator         ║
     ║──────────────────────────────────────────────────────────║
     ║    "The only system of knowledge that has any value      ║
     ║     is one we can understand and apply."                 ║
     ║                            ─ Gaius Plinius Secundus      ║
     ╚══════════════════════════════════════════════════════════╝"""

# Spinner frames (demoscene style)
SPINNER_FRAMES = [
    "▰▱▱▱▱▱▱▱",
    "▰▰▱▱▱▱▱▱",
    "▰▰▰▱▱▱▱▱",
    "▰▰▰▰▱▱▱▱",
    "▰▰▰▰▰▱▱▱",
    "▰▰▰▰▰▰▱▱",
    "▰▰▰▰▰▰▰▱",
    "▰▰▰▰▰▰▰▰",
    "▱▰▰▰▰▰▰▰",
    "▱▱▰▰▰▰▰▰",
    "▱▱▱▰▰▰▰▰",
    "▱▱▱▱▰▰▰▰",
    "▱▱▱▱▱▰▰▰",
    "▱▱▱▱▱▱▰▰",
    "▱▱▱▱▱▱▱▰",
    "▱▱▱▱▱▱▱▱",
]


class SplashScreen(Widget):
    """Full-screen splash with ASCII art and loading animation.

    Displays during app initialization and dismisses when ready.
    Uses a single render() method to avoid multi-widget refresh issues.
    """

    DEFAULT_CSS = """
    SplashScreen {
        width: 100%;
        height: 100%;
        background: $surface;
        layer: splash;
        content-align: center middle;
    }

    SplashScreen.hidden {
        display: none;
    }
    """

    # Reactive properties for animation
    spinner_frame = reactive(0)
    status_message = reactive("Initializing...")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ready = False

    def on_mount(self) -> None:
        """Start animation on mount."""
        self.set_interval(0.08, self._advance_spinner)  # ~12fps

    def _advance_spinner(self) -> None:
        """Advance spinner frame."""
        if not self._ready:
            self.spinner_frame = (self.spinner_frame + 1) % len(SPINNER_FRAMES)

    def render(self) -> RenderableType:
        """Render the entire splash as a single composed element."""
        spinner = SPINNER_FRAMES[self.spinner_frame]

        # Build the complete splash content
        logo = Text(GAIUS_LOGO, style="cyan")
        attribution = Text(ATTRIBUTION, style="dim")

        # Centered loading line
        loading_text = f"{spinner}  Loading  {spinner}"
        loading = Text(loading_text, style="green")

        # Centered status line
        status = Text(self.status_message, style="dim")

        # Compose vertically with proper spacing
        content = Text()
        content.append(logo)
        content.append("\n\n")
        content.append(attribution)
        content.append("\n\n")
        # Center the loading line by padding
        logo_width = max(len(line) for line in GAIUS_LOGO.split('\n'))
        loading_padding = (logo_width - len(loading_text)) // 2
        content.append(" " * loading_padding)
        content.append(loading)
        content.append("\n\n")
        # Center the status line
        status_padding = (logo_width - len(self.status_message)) // 2
        content.append(" " * max(0, status_padding))
        content.append(status)

        return Align.center(content, vertical="middle")

    def set_status(self, message: str) -> None:
        """Update the status message."""
        self.status_message = message

    def dismiss(self) -> None:
        """Hide the splash screen."""
        self._ready = True
        self.add_class("hidden")
