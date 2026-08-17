"""Tenuki marks and Ricci κ live on the same 19×19 board."""

from __future__ import annotations

from gaius.core.state import AppState, OverlayMode
from gaius.static.explain import generate_explanation
from gaius.widgets.grid import MainGrid


def test_curvature_at_cursor() -> None:
    state = AppState()
    state.curvature_map = [[0.0] * 19 for _ in range(19)]
    state.curvature_map[9][9] = -0.42
    state.cursor_x, state.cursor_y = 9, 9
    assert state.cursor_kappa == -0.42
    assert state.curvature_at(0, 0) == 0.0
    assert state.curvature_at(99, 99) is None


def test_tenuki_annotations_on_geometry_board() -> None:
    state = AppState()
    state.overlay_mode = OverlayMode.GEOMETRY
    state.curvature_map = [[0.0] * 19 for _ in range(19)]
    state.curvature_map[4][4] = -0.5
    state.tenuki_visited = {(3, 3), (4, 4)}
    state.tenuki_target = (4, 4)
    grid = MainGrid(state)._build_grid()
    assert grid[4][4] == ("☆", "bold magenta")
    assert grid[3][3][0] == "∘"


def test_explanation_surfaces_cognition_and_tenuki() -> None:
    text = generate_explanation(state_view(), OverlayMode.GEOMETRY, 9, 9)
    assert "### Cognition" in text
    assert "one next question" in text
    assert "Tenuki" in text
    assert "Ollivier-Ricci" in text


def state_view():
    from gaius.core.state import ViewMode

    return ViewMode.GO
