"""Fast launcher with splash screen during imports.

Shows a minimal Textual splash screen immediately, then imports the
full GaiusApp in a worker thread and hands over control.

This achieves <100ms time-to-splash by deferring heavy imports.
"""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from textual.app import App, ComposeResult
from textual.widgets import Static
from textual.reactive import reactive
from rich.align import Align
from rich.text import Text


# Inline splash content (no external imports needed)
GAIUS_LOGO = """\
     ╔══════════════════════════════════════════════════════════════╗
     ║                                                              ║
     ║    ▄████▄      ▄████▄     ▀████▀   ██    ██    ▄█████▄       ║
     ║   ██    ██    ██    ██      ██     ██    ██   ██     ▀       ║
     ║   ██          ████████      ██     ██    ██    ▀█████▄       ║
     ║   ██  ▄███    ██    ██      ██     ██    ██         ██       ║
     ║   ██    ██    ██    ██      ██     ██    ██   █     ██       ║
     ║    ▀████▀     ██    ██    ▄████▄    ▀████▀     ▀█████▀       ║
     ║                                                              ║
     ╚══════════════════════════════════════════════════════════════╝"""

ATTRIBUTION = """\
     ╔══════════════════════════════════════════════════════════════╗
     ║    G A I U S  ─  Topological Knowledge Navigator             ║
     ║──────────────────────────────────────────────────────────────║
     ║    "The only system of knowledge that has any value          ║
     ║     is one we can understand and apply."                     ║
     ║                            ─ Gaius Plinius Secundus          ║
     ╚══════════════════════════════════════════════════════════════╝"""

SPINNER_FRAMES = ["▰▱▱▱▱▱▱▱", "▰▰▱▱▱▱▱▱", "▰▰▰▱▱▱▱▱", "▰▰▰▰▱▱▱▱",
                  "▰▰▰▰▰▱▱▱", "▰▰▰▰▰▰▱▱", "▰▰▰▰▰▰▰▱", "▰▰▰▰▰▰▰▰",
                  "▱▰▰▰▰▰▰▰", "▱▱▰▰▰▰▰▰", "▱▱▱▰▰▰▰▰", "▱▱▱▱▰▰▰▰",
                  "▱▱▱▱▱▰▰▰", "▱▱▱▱▱▱▰▰", "▱▱▱▱▱▱▱▰", "▱▱▱▱▱▱▱▱"]


class SplashWidget(Static):
    """Minimal splash widget with spinner animation."""

    spinner_frame = reactive(0)
    status = reactive("Loading modules...")

    def on_mount(self) -> None:
        self.set_interval(0.08, self._tick)

    def _tick(self) -> None:
        self.spinner_frame = (self.spinner_frame + 1) % len(SPINNER_FRAMES)

    def render(self) -> Text:
        spinner = SPINNER_FRAMES[self.spinner_frame]
        logo_width = max(len(line) for line in GAIUS_LOGO.split('\n'))

        content = Text()
        content.append(Text(GAIUS_LOGO, style="cyan"))
        content.append("\n\n")
        content.append(Text(ATTRIBUTION, style="dim"))
        content.append("\n\n")

        # Centered spinner line
        loading_text = f"{spinner}  Loading  {spinner}"
        padding = (logo_width - len(loading_text)) // 2
        content.append(" " * padding)
        content.append(Text(loading_text, style="green"))
        content.append("\n\n")

        # Centered status
        status_padding = (logo_width - len(self.status)) // 2
        content.append(" " * max(0, status_padding))
        content.append(Text(self.status, style="dim"))

        return Align.center(content, vertical="middle")


class LauncherApp(App):
    """Minimal launcher that shows splash during imports."""

    CSS = """
    Screen {
        background: $surface;
        align: center middle;
    }
    """

    def __init__(self):
        super().__init__()
        self._gaius_app = None
        self._import_error = None
        self._imports_done = False

    def compose(self) -> ComposeResult:
        yield SplashWidget(id="splash")

    def on_mount(self) -> None:
        """Start importing GaiusApp in background."""
        self.run_worker(self._import_app, thread=True)

    async def _import_app(self) -> None:
        """Import GaiusApp in background thread."""
        splash = self.query_one("#splash", SplashWidget)

        try:
            # Phase 1: Core imports
            splash.status = "Loading configuration..."
            from .core.config import get_config

            splash.status = "Loading state management..."
            from .core.state import AppState

            splash.status = "Loading storage layer..."
            from .storage.grid_state import load_current_state_fast_sync

            splash.status = "Loading widgets..."
            from .widgets.grid import MainGrid
            from .widgets.info_panel import InfoPanel

            splash.status = "Loading telemetry..."
            from .core.telemetry import init_from_config as init_telemetry

            # Phase 2: Import the full app (this triggers remaining imports)
            splash.status = "Initializing application..."
            from .app import GaiusApp

            # Create the app instance
            splash.status = "Starting Gaius..."
            self._gaius_app = GaiusApp

            self._imports_done = True
            splash.status = "Ready!"

            # Give user a moment to see "Ready!", then handover
            self.call_from_thread(self._schedule_handover)

        except Exception as e:
            self._import_error = str(e)
            splash.status = f"Error: {e}"
            self.call_from_thread(lambda: self.set_timer(2.0, self.exit))

    def _schedule_handover(self) -> None:
        """Schedule handover from main thread."""
        self.set_timer(0.3, self._handover)

    def _handover(self) -> None:
        """Exit launcher and signal main() to start the real app."""
        self.exit(result=self._gaius_app)


def main():
    """Entry point with splash-first startup."""
    import argparse
    import logging
    import os

    # Suppress noisy startup logs
    log_level = os.getenv("GAIUS_LOG_LEVEL", "ERROR")
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.ERROR),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Gaius TUI")
    parser.add_argument("--profile", help="Configuration profile")
    parser.add_argument("--headless", action="store_true", help="Run headless (for testing)")
    args = parser.parse_args()

    if args.headless:
        # Skip splash for headless mode
        from .app import GaiusApp
        app = GaiusApp(profile=args.profile)
        app.run(headless=True)
        return

    # Run the launcher first
    launcher = LauncherApp()
    gaius_app_class = launcher.run()

    # If launcher returned the app class, run it
    if gaius_app_class is not None:
        app = gaius_app_class(profile=args.profile)
        app.run()


if __name__ == "__main__":
    main()
