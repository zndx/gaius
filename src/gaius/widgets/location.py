"""Location indicator widget - maps grid position to hypersphere coordinates."""

import math
from textual.widget import Widget
from textual.reactive import reactive


class LocationIndicator(Widget):
    """Displays celestial coordinates for the current grid position.

    Maps the 19×19 grid to a hypersphere (3-sphere in 4D) using
    celestial-inspired coordinates:

    - RA (Right Ascension): 0h 00m to 23h 59m (longitude on sphere)
    - Dec (Declination): -90° to +90° (latitude on sphere)
    - ψ (Psi): 0° to 180° (hypersphere elevation - the 4th dimension)
    """

    DEFAULT_CSS = """
    LocationIndicator {
        width: 100%;
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        text-align: center;
        padding: 0 1;
    }
    """

    cursor_x: reactive[int] = reactive(9)
    cursor_y: reactive[int] = reactive(9)

    def __init__(self, x: int = 9, y: int = 9, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cursor_x = x
        self.cursor_y = y

    def _grid_to_hypersphere(self, x: int, y: int) -> tuple[float, float, float]:
        """Map grid coordinates to hypersphere celestial coordinates.

        The 19×19 grid maps to a 3-sphere (hypersphere) via:
        - x → Right Ascension (0h to 24h, full circle)
        - y → Declination (-90° to +90°)
        - radial distance from center → Psi (elevation in 4th dimension)

        Returns:
            (ra_hours, ra_minutes, dec_degrees, psi_degrees)
        """
        # Right Ascension: x maps to 0-24 hours
        ra_total_hours = (x / 18.0) * 24.0
        ra_hours = int(ra_total_hours)
        ra_minutes = int((ra_total_hours - ra_hours) * 60)

        # Declination: y maps to +90° (top) to -90° (bottom)
        dec = 90.0 - (y / 18.0) * 180.0

        # Psi (hypersphere elevation): based on distance from center
        # Center (9,9) = 90° (equator of hypersphere)
        # Corners = 0° or 180° (poles of hypersphere)
        dx = x - 9
        dy = y - 9
        dist = math.sqrt(dx * dx + dy * dy)
        max_dist = math.sqrt(9 * 9 + 9 * 9)  # ~12.73
        psi = 90.0 - (dist / max_dist) * 90.0

        return (ra_hours, ra_minutes, dec, psi)

    def render(self) -> str:
        """Render the coordinate display."""
        ra_h, ra_m, dec, psi = self._grid_to_hypersphere(self.cursor_x, self.cursor_y)

        # Format declination with sign
        dec_sign = "+" if dec >= 0 else ""

        # Quadrant indicator based on position
        if self.cursor_x < 9 and self.cursor_y < 9:
            quadrant = "NW"
        elif self.cursor_x >= 9 and self.cursor_y < 9:
            quadrant = "NE"
        elif self.cursor_x < 9 and self.cursor_y >= 9:
            quadrant = "SW"
        else:
            quadrant = "SE"

        return f"◉ [{self.cursor_x:2d},{self.cursor_y:2d}] │ RA {ra_h:02d}h{ra_m:02d}m │ Dec {dec_sign}{dec:5.1f}° │ ψ {psi:5.1f}° │ {quadrant}"

    def update_position(self, x: int, y: int) -> None:
        """Update the cursor position."""
        self.cursor_x = x
        self.cursor_y = y
        self.refresh()
