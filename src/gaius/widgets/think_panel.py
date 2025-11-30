"""Think Panel widget for displaying reasoning traces.

This widget shows aggregated reasoning traces from agent and inference operations,
providing observability into the AI's thinking process. It occupies the same space
as the GraphView (40x21) and is toggled via the 'g' key cycling.
"""

from datetime import datetime

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text

from textual.widget import Widget
from textual.reactive import reactive

from ..core.state import AppState, ReasoningTrace


class ThinkPanel(Widget):
    """Displays reasoning traces and active thinking.

    Layout:
    +- Active Reasoning ----------------------------------------+
    | > Analyzing query: distributed consensus                  |
    | > Searching KB for: consensus, paxos, raft                |
    | > Found 12 KB results, 5 web results                      |
    | > Synthesizing with cot_reflection...                     |
    +-----------------------------------------------------------+
    +- Recent Traces (condensed) -------------------------------+
    | 14:32 synthesis: raft-consensus (3 sources, 847 tokens)   |
    | 14:28 search: byzantine fault tolerance (7 KB, 3 web)     |
    | 14:15 synthesis: cap-theorem (5 sources, 1.2k tokens)     |
    +-----------------------------------------------------------+
    """

    DEFAULT_CSS = """
    ThinkPanel {
        width: 40;
        height: 21;
        background: $surface-lighten-1;
        overflow: hidden;
    }
    """

    # Reactive to trigger refresh when traces change
    trace_count = reactive(0)

    def __init__(
        self,
        state: AppState,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.state = state

    def render(self) -> RenderableType:
        """Render the think panel content."""
        lines = []

        # Active reasoning section (top half)
        lines.append(Text("Active Reasoning", style="bold cyan"))
        lines.append(Text("─" * 36, style="dim"))

        if self.state.active_reasoning:
            # Split active reasoning into lines
            active_lines = self.state.active_reasoning.split("\n")
            for line in active_lines[:6]:  # Max 6 lines for active
                text = Text()
                text.append("> ", style="green")
                text.append(line[:34], style="white")
                lines.append(text)
        else:
            lines.append(Text("  (no active reasoning)", style="dim"))

        # Padding to fill active section
        while len(lines) < 9:
            lines.append(Text(""))

        # Recent traces section (bottom half)
        lines.append(Text(""))
        lines.append(Text("Recent Traces", style="bold yellow"))
        lines.append(Text("─" * 36, style="dim"))

        # Show most recent traces (newest first)
        traces = list(reversed(self.state.reasoning_traces[-8:]))
        if traces:
            for trace in traces:
                line = self._format_trace(trace)
                lines.append(line)
        else:
            lines.append(Text("  (no traces yet)", style="dim"))

        # Combine all lines
        content = Text("\n").join(lines)
        return Panel(
            content,
            title="[bold]Think[/bold]",
            title_align="left",
            border_style="cyan",
            padding=(0, 1),
        )

    def _format_trace(self, trace: ReasoningTrace) -> Text:
        """Format a single trace line."""
        text = Text()

        # Timestamp (HH:MM)
        time_str = trace.timestamp.strftime("%H:%M")
        text.append(f"{time_str} ", style="dim")

        # Operation type with color coding
        op_colors = {
            "search": "blue",
            "synthesis": "green",
            "inference": "yellow",
            "swarm": "magenta",
        }
        color = op_colors.get(trace.operation, "white")
        text.append(f"{trace.operation}: ", style=color)

        # Query (truncated)
        query_max = 18
        query = trace.query[:query_max]
        if len(trace.query) > query_max:
            query = query[:-1] + "…"
        text.append(query, style="white")

        # Stats
        stats = []
        if trace.sources:
            stats.append(f"{trace.sources}src")
        if trace.tokens:
            if trace.tokens >= 1000:
                stats.append(f"{trace.tokens // 1000}k tok")
            else:
                stats.append(f"{trace.tokens}tok")
        if stats:
            text.append(f" ({', '.join(stats)})", style="dim")

        return text

    def stream_reasoning(self, text: str) -> None:
        """Append text to active reasoning display.

        Called during inference to show real-time thinking.
        """
        if self.state.active_reasoning:
            self.state.active_reasoning += "\n" + text
        else:
            self.state.active_reasoning = text

        # Keep only last N lines
        lines = self.state.active_reasoning.split("\n")
        if len(lines) > 10:
            self.state.active_reasoning = "\n".join(lines[-10:])

        self.refresh()

    def complete_trace(
        self,
        operation: str,
        query: str,
        summary: str,
        tokens: int = 0,
        sources: int = 0,
        technique: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Complete the current reasoning and add to history.

        Called when an inference/search operation completes.
        """
        trace = ReasoningTrace(
            timestamp=datetime.now(),
            operation=operation,
            query=query,
            summary=summary,
            tokens=tokens,
            sources=sources,
            technique=technique,
            duration_ms=duration_ms,
            full_trace=self.state.active_reasoning or "",
        )

        self.state.add_reasoning_trace(trace)
        self.state.active_reasoning = None
        self.trace_count = len(self.state.reasoning_traces)
        self.refresh()

    def clear_active(self) -> None:
        """Clear the active reasoning display."""
        self.state.active_reasoning = None
        self.refresh()

    def update_state(self, state: AppState) -> None:
        """Update the state reference and refresh."""
        self.state = state
        self.trace_count = len(self.state.reasoning_traces)
        self.refresh()
