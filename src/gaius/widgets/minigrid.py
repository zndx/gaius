"""9x9 orthographic projection mini-grids."""

from textual.widget import Widget
from rich.text import Text

from ..core.state import AppState


class MiniGrid(Widget):
    """A 9x9 mini-grid for orthographic projections.

    Used in CAD-style arrangement around the main 19x19 grid:
    - Right: Embedding neighborhood view
    - Bottom-Right: Isometric/3D projection
    - Bottom: Temporal evolution view
    """

    DEFAULT_CSS = """
    MiniGrid {
        width: 19;
        height: 10;
        border: solid $primary-darken-2;
        padding: 0;
    }

    MiniGrid.right {
        border-title-color: $success;
    }

    MiniGrid.bottom-right {
        border-title-color: $warning;
    }

    MiniGrid.bottom {
        border-title-color: $secondary;
    }
    """

    def __init__(
        self,
        title: str,
        data: list[list[float]] | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.border_title = title
        self._data = data or [[0.0] * 9 for _ in range(9)]

    def render(self) -> Text:
        """Render the 9x9 mini-grid."""
        text = Text()

        for y in range(9):
            for x in range(9):
                value = self._data[y][x] if self._data else 0.0
                char, style = self._value_to_cell(value)
                text.append(char, style=style)
                if x < 8:
                    text.append(" ")
            if y < 8:
                text.append("\n")

        return text

    def _value_to_cell(self, value: float) -> tuple[str, str]:
        """Convert a 0-1 value to a character and style."""
        if value > 0.8:
            return ("█", "bright_white")
        elif value > 0.6:
            return ("▓", "white")
        elif value > 0.4:
            return ("▒", "bright_black")
        elif value > 0.2:
            return ("░", "dim")
        elif value > 0.05:
            return ("·", "dim")
        else:
            return (" ", "")

    def update_data(self, data: list[list[float]]) -> None:
        """Update the grid data and refresh."""
        self._data = data
        self.refresh()
