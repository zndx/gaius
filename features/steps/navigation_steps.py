"""Step definitions for navigation.feature."""

from behave import given, when, then
from behave.api.async_step import async_run_until_complete


@given("the Gaius TUI is running")
@async_run_until_complete
async def step_gaius_running(context):
    """Start the Gaius TUI application."""
    from features.environment import start_app

    await start_app(context)
    # Wait for app to be ready
    await context.pilot.pause()


@given('the cursor is at position ({x:d}, {y:d})')
@async_run_until_complete
async def step_cursor_at_position(context, x, y):
    """Set cursor to specific position."""
    context.app.state.cursor_x = x
    context.app.state.cursor_y = y


@when('I press "{key}" {count:d} times')
@async_run_until_complete
async def step_press_key_times(context, key, count):
    """Press a key multiple times."""
    for _ in range(count):
        await context.pilot.press(key)
        await context.pilot.pause()


@when('I press "{key}"')
@async_run_until_complete
async def step_press_key(context, key):
    """Press a single key."""
    await context.pilot.press(key)
    await context.pilot.pause()


@then('the cursor should be at position ({x:d}, {y:d})')
def step_cursor_should_be_at(context, x, y):
    """Verify cursor position."""
    assert context.app.state.cursor_x == x, (
        f"Expected cursor_x={x}, got {context.app.state.cursor_x}"
    )
    assert context.app.state.cursor_y == y, (
        f"Expected cursor_y={y}, got {context.app.state.cursor_y}"
    )


@given('the left panel is visible')
@async_run_until_complete
async def step_left_panel_visible(context):
    """Ensure left panel is visible."""
    context.app.state.left_panel_visible = True
    panel = context.app.query_one("#left-panel")
    panel.remove_class("hidden")


@given('the right panel is visible')
@async_run_until_complete
async def step_right_panel_visible(context):
    """Ensure right panel is visible."""
    context.app.state.right_panel_visible = True
    panel = context.app.query_one("#right-panel")
    panel.remove_class("hidden")


@then('the left panel should be hidden')
@async_run_until_complete
async def step_left_panel_hidden(context):
    """Verify left panel is hidden."""
    panel = context.app.query_one("#left-panel")
    assert panel.has_class("hidden"), "Left panel should be hidden"


@then('the right panel should be hidden')
@async_run_until_complete
async def step_right_panel_hidden(context):
    """Verify right panel is hidden."""
    panel = context.app.query_one("#right-panel")
    assert panel.has_class("hidden"), "Right panel should be hidden"


@then('the left panel should be visible')
@async_run_until_complete
async def step_left_panel_should_be_visible(context):
    """Verify left panel is visible."""
    panel = context.app.query_one("#left-panel")
    assert not panel.has_class("hidden"), "Left panel should be visible"


@then('the right panel should be visible')
@async_run_until_complete
async def step_right_panel_should_be_visible(context):
    """Verify right panel is visible."""
    panel = context.app.query_one("#right-panel")
    assert not panel.has_class("hidden"), "Right panel should be visible"


@given('the view mode is "{mode}"')
def step_view_mode_is(context, mode):
    """Set the view mode."""
    from gaius.core.state import ViewMode

    mode_map = {
        "go": ViewMode.GO,
        "pension": ViewMode.PENSION,
        "swarm": ViewMode.SWARM,
    }
    context.app.state.view_mode = mode_map[mode.lower()]


@then('the view mode should be "{mode}"')
def step_view_mode_should_be(context, mode):
    """Verify the view mode."""
    from gaius.core.state import ViewMode

    mode_map = {
        "go": ViewMode.GO,
        "pension": ViewMode.PENSION,
        "swarm": ViewMode.SWARM,
    }
    expected = mode_map[mode.lower()]
    assert context.app.state.view_mode == expected, (
        f"Expected view_mode={expected}, got {context.app.state.view_mode}"
    )


@given('the overlay mode is "{mode}"')
def step_overlay_mode_is(context, mode):
    """Set the overlay mode."""
    from gaius.core.state import OverlayMode

    mode_map = {
        "none": OverlayMode.NONE,
        "risk": OverlayMode.RISK,
        "h1": OverlayMode.H1,
        "h2": OverlayMode.H2,
        "agents": OverlayMode.AGENTS,
        "temporal": OverlayMode.TEMPORAL,
    }
    context.app.state.overlay_mode = mode_map[mode.lower()]


@then('the overlay mode should be "{mode}"')
def step_overlay_mode_should_be(context, mode):
    """Verify the overlay mode."""
    from gaius.core.state import OverlayMode

    mode_map = {
        "none": OverlayMode.NONE,
        "risk": OverlayMode.RISK,
        "h1": OverlayMode.H1,
        "h2": OverlayMode.H2,
        "agents": OverlayMode.AGENTS,
        "temporal": OverlayMode.TEMPORAL,
    }
    expected = mode_map[mode.lower()]
    assert context.app.state.overlay_mode == expected, (
        f"Expected overlay_mode={expected}, got {context.app.state.overlay_mode}"
    )


@given('the graph panel is hidden')
@async_run_until_complete
async def step_graph_panel_hidden(context):
    """Ensure graph panel is hidden."""
    graph = context.app.query_one("#graph-view")
    graph.add_class("hidden")


@then('the graph panel should be visible')
@async_run_until_complete
async def step_graph_panel_should_be_visible(context):
    """Verify graph panel is visible."""
    graph = context.app.query_one("#graph-view")
    assert not graph.has_class("hidden"), "Graph panel should be visible"


@then('command input should be focused')
@async_run_until_complete
async def step_command_input_focused(context):
    """Verify command input is focused."""
    cmd_input = context.app.query_one("#command-input")
    assert context.app.focused == cmd_input, "Command input should be focused"
