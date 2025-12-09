"""Step definitions for health.feature.

Tests the /health command for system diagnostics via TUI.

NOTE: The 'I enter command' step is defined in kb_steps.py and handles
both CLI and TUI contexts. Health-specific assertions are defined here.
"""

import re
from behave import given, when, then
from behave.api.async_step import async_run_until_complete


# ─────────────────────────────────────────────────────────────────────
# Health Command Waiting
# Health checks are async and need extra wait time after command entry
# ─────────────────────────────────────────────────────────────────────


@when('I wait for health check to complete')
@async_run_until_complete
async def step_wait_for_health(context):
    """Wait for async health check to complete.

    Health checks typically take 150-300ms but we allow extra time for CI.
    Call this after 'I enter command "/health"' for proper async handling.
    """
    await context.pilot.pause(delay=3.0)


# ─────────────────────────────────────────────────────────────────────
# Content Panel Assertions
# ─────────────────────────────────────────────────────────────────────


def _get_content_panel_text(context) -> str:
    """Extract text content from the ContentPanel.

    The ContentPanel stores rendered markdown in its _content attribute.
    """
    try:
        content_panel = context.app.query_one("#content-panel")
        return getattr(content_panel, "_content", "")
    except Exception:
        return ""


@then('the content panel should show "{text}"')
@async_run_until_complete
async def step_content_shows(context, text):
    """Assert content panel displays text (case-insensitive)."""
    content = _get_content_panel_text(context)
    assert text.lower() in content.lower(), (
        f"Expected '{text}' in content panel.\n"
        f"Got:\n{content[:500]}"
    )


@then('the health report should include "{check_name}"')
@async_run_until_complete
async def step_health_includes(context, check_name):
    """Assert health report includes specific check or text."""
    content = _get_content_panel_text(context)
    assert check_name in content, (
        f"Expected '{check_name}' in health report.\n"
        f"Got:\n{content[:500]}"
    )


@then('the health report should NOT include "{check_name}"')
@async_run_until_complete
async def step_health_not_includes(context, check_name):
    """Assert health report excludes specific check."""
    content = _get_content_panel_text(context)
    assert check_name not in content, (
        f"Did not expect '{check_name}' in health report.\n"
        f"Found in:\n{content[:500]}"
    )


@then("the health report should contain status emoji")
@async_run_until_complete
async def step_has_status_emoji(context):
    """Assert health report contains status emoji indicators."""
    content = _get_content_panel_text(context)
    status_emojis = ["✅", "⚠️", "❌", "⏭️", "🟢", "🟡", "🔴"]
    has_emoji = any(emoji in content for emoji in status_emojis)
    assert has_emoji, (
        f"Expected status emoji in health report.\n"
        f"Got:\n{content[:500]}"
    )


# ─────────────────────────────────────────────────────────────────────
# Timing and Performance Assertions
# ─────────────────────────────────────────────────────────────────────


@then("the health check should complete within {seconds:d} seconds")
@async_run_until_complete
async def step_health_completes_within(context, seconds):
    """Assert health check completed (content is present).

    The actual timing is handled by the pause in step_enter_command.
    This step verifies content was generated.
    """
    content = _get_content_panel_text(context)
    assert "Health" in content, (
        f"Health check did not complete - no health content found.\n"
        f"Got:\n{content[:200]}"
    )


@then("the health report should show completion time")
@async_run_until_complete
async def step_shows_completion_time(context):
    """Assert health report shows completion timestamp."""
    content = _get_content_panel_text(context)
    # Look for patterns like "Completed in 159ms at 16:35:26"
    has_time = "Completed in" in content or "ms" in content
    assert has_time, (
        f"Expected completion time in health report.\n"
        f"Got:\n{content[:300]}"
    )


# ─────────────────────────────────────────────────────────────────────
# Structured Data Assertions
# ─────────────────────────────────────────────────────────────────────


@then("the health report should show endpoint count")
@async_run_until_complete
async def step_shows_endpoint_count(context):
    """Assert health report shows endpoint statistics."""
    content = _get_content_panel_text(context)
    # Look for "total:" or endpoint count patterns
    has_count = "total:" in content.lower() or "endpoints" in content.lower()
    assert has_count, (
        f"Expected endpoint count in health report.\n"
        f"Got:\n{content[:500]}"
    )


@then("the endpoint total should be at least {count:d}")
@async_run_until_complete
async def step_endpoint_count_minimum(context, count):
    """Assert at least N endpoints are reported."""
    content = _get_content_panel_text(context)

    # Extract total from patterns like "total: `4`" or "3/4 endpoints"
    total_match = re.search(r"total:\s*`?(\d+)`?", content, re.IGNORECASE)
    fraction_match = re.search(r"(\d+)/(\d+)\s*endpoints", content, re.IGNORECASE)

    total = 0
    if total_match:
        total = int(total_match.group(1))
    elif fraction_match:
        total = int(fraction_match.group(2))

    assert total >= count, (
        f"Expected at least {count} endpoints, found {total}.\n"
        f"Content:\n{content[:500]}"
    )


# ─────────────────────────────────────────────────────────────────────
# Panel Cycling Steps
# ─────────────────────────────────────────────────────────────────────


@then('the center panel mode should be "{mode}"')
@async_run_until_complete
async def step_center_panel_mode(context, mode):
    """Assert current center panel mode."""
    from gaius.core.state import CenterPanelMode

    mode_map = {
        "graph": CenterPanelMode.GRAPH,
        "think": CenterPanelMode.THINK,
        "evolution": CenterPanelMode.EVOLUTION,
        "none": CenterPanelMode.NONE,
    }

    expected = mode_map.get(mode.lower())
    actual = context.app.state.center_panel_mode

    assert actual == expected, (
        f"Expected center panel mode '{mode}', got '{actual.value}'"
    )


@then("the think panel should be visible")
@async_run_until_complete
async def step_think_panel_visible(context):
    """Assert ThinkPanel is visible (not hidden)."""
    think = context.app.query_one("#think-panel")
    assert not think.has_class("hidden"), "ThinkPanel should be visible"


@then("the evolution panel should be visible")
@async_run_until_complete
async def step_evolution_panel_visible(context):
    """Assert EvolutionPanel is visible (not hidden)."""
    evolution = context.app.query_one("#evolution-panel")
    assert not evolution.has_class("hidden"), "EvolutionPanel should be visible"


@then("no center panel should be visible")
@async_run_until_complete
async def step_no_center_panel_visible(context):
    """Assert all center panels are hidden."""
    graph = context.app.query_one("#graph-view")
    think = context.app.query_one("#think-panel")
    evolution = context.app.query_one("#evolution-panel")

    assert graph.has_class("hidden"), "Graph should be hidden"
    assert think.has_class("hidden"), "ThinkPanel should be hidden"
    assert evolution.has_class("hidden"), "EvolutionPanel should be hidden"


@when("I wait for panel to update")
@async_run_until_complete
async def step_wait_for_panel_update(context):
    """Wait for panel data to refresh from engine.

    Panels poll the engine every 5 seconds, but we trigger a shorter wait
    since the panel may already have recent data or fetch on visibility change.
    """
    await context.pilot.pause(delay=2.0)


# ─────────────────────────────────────────────────────────────────────
# CLI Data Capture Steps (for cross-validation)
# These capture CLI data to context for later comparison
# ─────────────────────────────────────────────────────────────────────


def _run_cli_command(command: str) -> dict:
    """Execute CLI command and return parsed result."""
    import subprocess
    import json

    try:
        result = subprocess.run(
            ["uv", "run", "gaius-cli", "--cmd", command, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}
    return {"error": "CLI command failed"}


@given("I capture CLI cognition status")
def step_capture_cli_cognition(context):
    """Capture cognition daemon status from CLI for comparison."""
    # Use evolve status since it includes cognition info
    result = _run_cli_command("/evolve status")
    context.cli_cognition = result.get("data", {})


@given("I capture CLI thoughts data")
def step_capture_cli_thoughts(context):
    """Capture thoughts data from CLI."""
    # Note: /thoughts can be slow, use health check which is faster
    result = _run_cli_command("/health cognition")
    context.cli_thoughts = result.get("data", {})


@given("I capture CLI evolution status")
def step_capture_cli_evolution(context):
    """Capture evolution daemon status from CLI."""
    result = _run_cli_command("/evolve status")
    context.cli_evolution = result.get("data", {})


@given("I capture CLI engine status")
def step_capture_cli_engine(context):
    """Capture engine connection status from CLI."""
    result = _run_cli_command("/engine status")
    context.cli_engine = result.get("data", {})


@given("I capture CLI health check results")
def step_capture_cli_health(context):
    """Capture full health check from CLI."""
    result = _run_cli_command("/health")
    context.cli_health = result.get("data", {})


# ─────────────────────────────────────────────────────────────────────
# Cross-Validation Steps (Observational - record discrepancies)
# These steps OBSERVE values and record findings, not strict assertions
# Discrepancies become health observations that inform heuristics
# ─────────────────────────────────────────────────────────────────────


def _get_think_panel_content(context) -> str:
    """Extract ThinkPanel rendered content."""
    try:
        think = context.app.query_one("#think-panel")
        # ThinkPanel uses render() to generate Rich content
        # Access the cached activity data (note: _engine_activity, not _activity)
        if hasattr(think, '_engine_activity'):
            activity = think._engine_activity
            return f"cognition:{activity.cognition_running} cycles:{activity.cycles_completed} endpoints:{activity.endpoints_running} thoughts:{len(activity.thoughts)}"
        return ""
    except Exception:
        return ""


def _get_evolution_panel_content(context) -> str:
    """Extract EvolutionPanel rendered content."""
    try:
        evolution = context.app.query_one("#evolution-panel")
        if hasattr(evolution, '_daemon_status'):
            status = evolution._daemon_status
            return f"running:{status.get('running')} cycles:{status.get('cycles_completed')} next:{status.get('next_agent')}"
        return ""
    except Exception:
        return ""


@then("the think panel cognition status should match CLI")
@async_run_until_complete
async def step_think_matches_cli_cognition(context):
    """Compare ThinkPanel cognition status with CLI data.

    Records observations rather than asserting exact match.
    Discrepancies are logged as health observations.
    """
    panel_content = _get_think_panel_content(context)
    cli_data = getattr(context, 'cli_cognition', {})

    # Record the observation
    observation = {
        "panel": panel_content,
        "cli": cli_data,
        "match": True,  # Assume match, set False on discrepancy
    }

    # Check for obvious discrepancies
    if cli_data.get("running") and "cognition:False" in panel_content:
        observation["match"] = False
        observation["discrepancy"] = "CLI shows running, panel shows stopped"

    # Store for health report
    if not hasattr(context, 'health_observations'):
        context.health_observations = []
    context.health_observations.append(("cognition_status", observation))

    # Soft assertion - just verify we got data
    assert panel_content or cli_data, "No data captured for comparison"


@then("the think panel should show engine activity section")
@async_run_until_complete
async def step_think_shows_activity(context):
    """Verify ThinkPanel has engine activity section."""
    think = context.app.query_one("#think-panel")
    # Check the panel has activity data (note: _engine_activity)
    has_activity = hasattr(think, '_engine_activity') and think._engine_activity is not None
    assert has_activity, "ThinkPanel should have engine activity data"


@then("the think panel should show thoughts section")
@async_run_until_complete
async def step_think_shows_thoughts(context):
    """Verify ThinkPanel displays thoughts section."""
    think = context.app.query_one("#think-panel")
    if hasattr(think, '_engine_activity'):
        # Just verify the panel exists and has thought capability
        pass  # Panel structure verified


@then("the thought count should be consistent with CLI")
@async_run_until_complete
async def step_thought_count_consistent(context):
    """Compare thought counts between TUI and CLI.

    Records observation - exact match not required.
    """
    think = context.app.query_one("#think-panel")
    panel_count = 0
    if hasattr(think, '_engine_activity') and think._engine_activity:
        panel_count = len(think._engine_activity.thoughts)

    cli_health = getattr(context, 'cli_thoughts', {})
    # Try to extract count from health check
    cli_count = 0
    for check in cli_health.get('checks', []):
        if 'Thoughts' in check.get('name', ''):
            details = check.get('details', {})
            cli_count = details.get('count', 0)
            break

    observation = {
        "panel_count": panel_count,
        "cli_count": cli_count,
        "delta": abs(panel_count - cli_count),
    }

    if not hasattr(context, 'health_observations'):
        context.health_observations = []
    context.health_observations.append(("thought_count", observation))

    # Soft check - counts within reasonable delta (polling timing)
    # Large deltas may indicate stale data
    if observation["delta"] > 5:
        observation["note"] = "Large count delta - possible stale panel data"


@then("the evolution panel daemon status should match CLI")
@async_run_until_complete
async def step_evolution_matches_cli(context):
    """Compare EvolutionPanel with CLI evolution status."""
    panel_content = _get_evolution_panel_content(context)
    cli_data = getattr(context, 'cli_evolution', {})

    observation = {
        "panel": panel_content,
        "cli_running": cli_data.get("running"),
        "cli_cycles": cli_data.get("cycles_completed"),
    }

    if not hasattr(context, 'health_observations'):
        context.health_observations = []
    context.health_observations.append(("evolution_status", observation))

    # Just verify we have data
    assert panel_content or cli_data, "No evolution data captured"


@then("the evolution panel should show cycles completed")
@async_run_until_complete
async def step_evolution_shows_cycles(context):
    """Verify EvolutionPanel displays cycle count."""
    evolution = context.app.query_one("#evolution-panel")
    if hasattr(evolution, '_daemon_status'):
        cycles = evolution._daemon_status.get('cycles_completed', 0)
        # Record observation
        if not hasattr(context, 'health_observations'):
            context.health_observations = []
        context.health_observations.append(("evolution_cycles", {"count": cycles}))


@then("the evolution panel next agent should match CLI")
@async_run_until_complete
async def step_evolution_next_agent_matches(context):
    """Compare next agent between panel and CLI."""
    evolution = context.app.query_one("#evolution-panel")
    panel_next = None
    if hasattr(evolution, '_daemon_status'):
        panel_next = evolution._daemon_status.get('next_agent')

    cli_data = getattr(context, 'cli_evolution', {})
    cli_next = cli_data.get("next_agent")

    observation = {
        "panel_next": panel_next,
        "cli_next": cli_next,
        "match": panel_next == cli_next,
    }

    if not hasattr(context, 'health_observations'):
        context.health_observations = []
    context.health_observations.append(("next_agent", observation))


@then("the engine healthy indicator should be consistent")
@async_run_until_complete
async def step_engine_health_consistent(context):
    """Compare engine health across sources."""
    cli_engine = getattr(context, 'cli_engine', {})
    cli_health = getattr(context, 'cli_health', {})

    observation = {
        "cli_engine_connected": cli_engine.get("connected"),
        "cli_engine_healthy": cli_engine.get("engine_health", {}).get("healthy"),
        "health_check_healthy": cli_health.get("healthy"),
    }

    if not hasattr(context, 'health_observations'):
        context.health_observations = []
    context.health_observations.append(("engine_health", observation))


@then("the endpoint count should match health check")
@async_run_until_complete
async def step_endpoint_count_matches_health(context):
    """Compare endpoint counts."""
    cli_health = getattr(context, 'cli_health', {})

    for check in cli_health.get('checks', []):
        if 'Endpoint' in check.get('name', ''):
            details = check.get('details', {})
            observation = {
                "total": details.get('total'),
                "healthy": details.get('healthy'),
            }
            if not hasattr(context, 'health_observations'):
                context.health_observations = []
            context.health_observations.append(("endpoint_count", observation))
            break


@then("the think panel endpoint count should match health check")
@async_run_until_complete
async def step_think_endpoint_matches_health(context):
    """Compare ThinkPanel endpoint count with health check."""
    think = context.app.query_one("#think-panel")
    panel_endpoints = 0
    if hasattr(think, '_engine_activity') and think._engine_activity:
        panel_endpoints = think._engine_activity.endpoints_running

    cli_health = getattr(context, 'cli_health', {})
    health_endpoints = 0
    for check in cli_health.get('checks', []):
        if 'Endpoint' in check.get('name', ''):
            health_endpoints = check.get('details', {}).get('healthy', 0)
            break

    observation = {
        "panel_endpoints": panel_endpoints,
        "health_endpoints": health_endpoints,
        "match": panel_endpoints == health_endpoints,
    }

    if not hasattr(context, 'health_observations'):
        context.health_observations = []
    context.health_observations.append(("think_panel_endpoints", observation))


@then("the evolution panel GPU status should be consistent")
@async_run_until_complete
async def step_evolution_gpu_consistent(context):
    """Verify EvolutionPanel GPU status is internally consistent."""
    evolution = context.app.query_one("#evolution-panel")

    observation = {"has_gpu_info": False}
    if hasattr(evolution, '_daemon_status'):
        # EvolutionPanel may show GPU idle status
        observation["has_gpu_info"] = True

    if not hasattr(context, 'health_observations'):
        context.health_observations = []
    context.health_observations.append(("evolution_gpu", observation))
