"""Progress Tracking for Cloudera Docs Sync.

Provides real-time progress visibility across CLI/MCP/TUI surfaces.

Architecture:
    - ProgressState: Dataclass representing current sync state
    - ProgressTracker: Thread-safe progress writer (updated by workers)
    - Progress file: JSON state at /tmp/gaius/cloudera_sync_progress.json

Usage in ParallelDocProcessor:
    tracker = ProgressTracker(product="csa", total=494)
    tracker.start()
    # ... in worker loop ...
    tracker.update(completed=10, failed=1)
    tracker.complete()

Query via MCP:
    cloudera_sync_progress() -> Returns current ProgressState as JSON
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any


# Progress file location - accessible to all surfaces
PROGRESS_DIR = Path("/tmp/gaius")
PROGRESS_FILE = PROGRESS_DIR / "cloudera_sync_progress.json"


@dataclass
class ProgressState:
    """Current sync progress state."""

    # Identification
    product: str
    workload_id: str

    # Counts
    total: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0

    # Timing
    started_at: str = ""
    updated_at: str = ""
    eta_seconds: float | None = None
    elapsed_seconds: float = 0.0

    # Rate
    rate_per_second: float = 0.0

    # Status
    status: str = "pending"  # pending, running, completed, failed, preempted
    error: str | None = None

    # Recent files (last 5)
    recent_files: list[str] = field(default_factory=list)

    @property
    def percent_complete(self) -> float:
        """Percentage completion (0-100)."""
        if self.total == 0:
            return 0.0
        return 100.0 * (self.completed + self.failed + self.skipped) / self.total

    @property
    def remaining(self) -> int:
        """Number of items remaining."""
        return max(0, self.total - self.completed - self.failed - self.skipped)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with computed properties."""
        d = asdict(self)
        d["percent_complete"] = round(self.percent_complete, 1)
        d["remaining"] = self.remaining
        return d

    def to_json(self) -> str:
        """JSON representation."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_file(cls, path: Path = PROGRESS_FILE) -> "ProgressState | None":
        """Load from progress file."""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            # Remove computed properties before constructing
            data.pop("percent_complete", None)
            data.pop("remaining", None)
            return cls(**data)
        except Exception:
            return None

    def save(self, path: Path = PROGRESS_FILE) -> None:
        """Save to progress file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())


class ProgressTracker:
    """Thread-safe progress tracker for sync operations.

    Updates a shared progress file that can be read by MCP/CLI/TUI.
    """

    def __init__(
        self,
        product: str,
        workload_id: str,
        total: int,
        progress_file: Path = PROGRESS_FILE,
    ):
        self.progress_file = progress_file
        self._lock = threading.Lock()
        self._start_time: datetime | None = None

        self._state = ProgressState(
            product=product,
            workload_id=workload_id,
            total=total,
            status="pending",
        )

    def start(self) -> None:
        """Mark sync as started."""
        with self._lock:
            self._start_time = datetime.now()
            self._state.started_at = self._start_time.isoformat()
            self._state.updated_at = self._start_time.isoformat()
            self._state.status = "running"
            self._state.save(self.progress_file)

    def update(
        self,
        completed: int | None = None,
        failed: int | None = None,
        skipped: int | None = None,
        recent_file: str | None = None,
    ) -> None:
        """Update progress counts and metrics."""
        with self._lock:
            if completed is not None:
                self._state.completed = completed
            if failed is not None:
                self._state.failed = failed
            if skipped is not None:
                self._state.skipped = skipped

            # Track recent files
            if recent_file:
                self._state.recent_files.append(recent_file)
                if len(self._state.recent_files) > 5:
                    self._state.recent_files = self._state.recent_files[-5:]

            # Compute timing
            now = datetime.now()
            self._state.updated_at = now.isoformat()

            if self._start_time:
                elapsed = (now - self._start_time).total_seconds()
                self._state.elapsed_seconds = elapsed

                done = self._state.completed + self._state.failed + self._state.skipped
                if done > 0 and elapsed > 0:
                    self._state.rate_per_second = done / elapsed
                    remaining = self._state.remaining
                    if self._state.rate_per_second > 0:
                        self._state.eta_seconds = remaining / self._state.rate_per_second

            self._state.save(self.progress_file)

    def complete(self, success: bool = True, error: str | None = None) -> None:
        """Mark sync as complete."""
        with self._lock:
            self._state.status = "completed" if success else "failed"
            self._state.error = error
            self._state.updated_at = datetime.now().isoformat()

            if self._start_time:
                self._state.elapsed_seconds = (
                    datetime.now() - self._start_time
                ).total_seconds()

            self._state.eta_seconds = 0.0
            self._state.save(self.progress_file)

    def preempt(self) -> None:
        """Mark sync as preempted."""
        with self._lock:
            self._state.status = "preempted"
            self._state.updated_at = datetime.now().isoformat()
            self._state.save(self.progress_file)

    @property
    def state(self) -> ProgressState:
        """Get current state (thread-safe copy)."""
        with self._lock:
            return ProgressState(**asdict(self._state))


def get_sync_progress() -> dict[str, Any] | None:
    """Get current sync progress for MCP/CLI.

    Returns:
        Progress dict or None if no sync in progress.
    """
    state = ProgressState.from_file()
    if state is None:
        return None
    return state.to_dict()


def format_progress_human(progress: dict[str, Any]) -> str:
    """Format progress for human-readable display.

    Returns multiline string suitable for CLI/TUI.
    """
    lines = []

    status = progress.get("status", "unknown")
    product = progress.get("product", "unknown")
    pct = progress.get("percent_complete", 0)

    # Header
    status_emoji = {
        "pending": "...",
        "running": ">>>",
        "completed": "[OK]",
        "failed": "[X]",
        "preempted": "[!]",
    }.get(status, "???")

    lines.append(f"{status_emoji} Cloudera Docs Sync: {product}")
    lines.append("=" * 50)

    # Progress bar
    bar_width = 40
    filled = int(bar_width * pct / 100)
    bar = "[" + "#" * filled + "-" * (bar_width - filled) + "]"
    lines.append(f"{bar} {pct:.1f}%")

    # Counts
    total = progress.get("total", 0)
    completed = progress.get("completed", 0)
    failed = progress.get("failed", 0)
    remaining = progress.get("remaining", 0)
    lines.append(f"  Completed: {completed}/{total}")
    if failed > 0:
        lines.append(f"  Failed: {failed}")
    lines.append(f"  Remaining: {remaining}")

    # Timing
    rate = progress.get("rate_per_second", 0)
    eta = progress.get("eta_seconds")
    elapsed = progress.get("elapsed_seconds", 0)

    lines.append(f"  Elapsed: {elapsed/60:.1f} min")
    if rate > 0:
        lines.append(f"  Rate: {rate:.2f} docs/sec")
    if eta and eta > 0:
        lines.append(f"  ETA: {eta/60:.1f} min")

    # Recent files
    recent = progress.get("recent_files", [])
    if recent:
        lines.append("")
        lines.append("Recent files:")
        for f in recent[-3:]:
            lines.append(f"  - {f}")

    return "\n".join(lines)


def clear_progress() -> None:
    """Clear progress file (for cleanup)."""
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()


# =============================================================================
# Rich Progress Bar Support (CLI)
# =============================================================================


def watch_progress_rich(poll_interval: float = 1.0) -> None:
    """Watch sync progress with Rich live display.

    Uses Rich's Progress widget for a proper animated progress bar with
    spinner, ETA, elapsed time, and transfer rate.

    Usage (CLI):
        uv run gaius-cli --cmd "/docs-sync progress"
    """
    try:
        from rich.progress import (
            Progress,
            SpinnerColumn,
            BarColumn,
            TaskProgressColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
            TextColumn,
            MofNCompleteColumn,
        )
        from rich.live import Live
        from rich.table import Table
        from rich.panel import Panel
        from rich.console import Console, Group
        from rich.text import Text
    except ImportError:
        print("Rich not installed. Using plain progress:")
        _watch_progress_plain(poll_interval)
        return

    import time

    console = Console()

    task_id = None
    last_state: ProgressState | None = None

    def make_display(state: ProgressState | None) -> Panel:
        """Create the full progress display."""
        table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        table.add_column(justify="left", ratio=3)
        table.add_column(justify="right", ratio=1)

        if state is None:
            table.add_row("[yellow]⏳ Waiting for sync to start...[/yellow]")
            return Panel(table, title="Cloudera Docs Sync", border_style="blue")

        # Status indicator
        status_style = {
            "pending": "yellow",
            "running": "green",
            "completed": "bold green",
            "failed": "bold red",
            "preempted": "orange1",
        }.get(state.status, "white")

        # Header with product and status
        table.add_row(
            f"[bold]{state.product}[/bold]",
            f"[{status_style}]● {state.status.upper()}[/{status_style}]",
        )

        # Progress bar using Rich's ProgressBar renderable
        from rich.progress_bar import ProgressBar
        pct = state.percent_complete / 100.0
        bar = ProgressBar(total=100, completed=state.percent_complete, width=50)
        table.add_row(bar, f"[bold]{state.percent_complete:.1f}%[/bold]")

        # Stats
        table.add_row(
            f"[green]{state.completed}[/green] done, "
            f"[red]{state.failed}[/red] failed, "
            f"[yellow]{state.remaining}[/yellow] remaining",
            f"[dim]{state.completed + state.failed}/{state.total}[/dim]",
        )

        # Timing
        elapsed_min = state.elapsed_seconds / 60
        rate_str = f"{state.rate_per_second:.2f}/s" if state.rate_per_second > 0 else "-"
        eta_str = f"{state.eta_seconds / 60:.1f} min" if state.eta_seconds else "-"
        table.add_row(
            f"[cyan]Elapsed:[/cyan] {elapsed_min:.1f} min  [cyan]Rate:[/cyan] {rate_str}",
            f"[cyan]ETA:[/cyan] {eta_str}",
        )

        # Recent files
        if state.recent_files:
            table.add_row("", "")
            for f in state.recent_files[-2:]:
                filename = f.split("/")[-1] if "/" in f else f
                if len(filename) > 60:
                    filename = "..." + filename[-57:]
                table.add_row(f"[dim]→ {filename}[/dim]", "")

        return Panel(table, title="Cloudera Docs Sync", border_style="blue")

    with Live(make_display(None), console=console, refresh_per_second=2) as live:
        while True:
            state = ProgressState.from_file()
            last_state = state

            live.update(make_display(state))

            # Exit conditions
            if state and state.status in ("completed", "failed"):
                time.sleep(1)
                break

            time.sleep(poll_interval)

    # Final message
    if last_state and last_state.status == "completed":
        console.print(
            f"\n[bold green]✓ Sync complete![/bold green] "
            f"{last_state.completed} docs in {last_state.elapsed_seconds/60:.1f} min"
        )
    elif last_state:
        console.print(f"\n[bold red]✗ Sync {last_state.status}[/bold red]")


def _watch_progress_plain(poll_interval: float = 1.0) -> None:
    """Fallback progress watcher without Rich."""
    import time

    while True:
        progress = get_sync_progress()
        if progress is None:
            print("No sync in progress...")
            time.sleep(poll_interval)
            continue

        # Clear screen (ANSI escape)
        print("\033[2J\033[H", end="")
        print(format_progress_human(progress))

        if progress.get("status") in ("completed", "failed"):
            break

        time.sleep(poll_interval)
