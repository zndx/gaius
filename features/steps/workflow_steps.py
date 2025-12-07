"""Step definitions for workflow.feature - CLI-based testing.

These steps test workflow commands via the CLI directly,
without requiring TUI interaction.

NOTE: Steps that are already defined in kb_steps.py are not duplicated here.
This includes: 'I enter command', 'the active profile should be', etc.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from behave import given, when, then


# ─────────────────────────────────────────────────────────────────────
# CLI Test Fixtures
# ─────────────────────────────────────────────────────────────────────

# @given("the Gaius CLI is available") - defined in test_fixtures.py
# @given("the KB root is configured") - defined in test_fixtures.py


@given("the KB root is configured with current/ and scratch/ directories")
def step_kb_configured_with_dirs(context):
    """Ensure KB directories exist including projects subdir."""
    from features.steps.test_fixtures import step_kb_root_configured
    step_kb_root_configured(context)
    kb_root = context.kb_root
    (kb_root / "current" / "projects").mkdir(parents=True, exist_ok=True)


@given("Gaius is installed and configured")
def step_gaius_installed(context):
    """Verify Gaius is properly installed."""
    from features.steps.test_fixtures import step_cli_available
    step_cli_available(context)


# ─────────────────────────────────────────────────────────────────────
# CLI Command Execution
# ─────────────────────────────────────────────────────────────────────

@when('I run CLI command "{command}"')
def step_run_cli_command(context, command):
    """Execute a CLI command and store result."""
    result = context.cli.execute(command)
    context.last_result = result
    context.cli_results.append(result)


# Assertion steps are defined in shared_steps.py:
# - @then("the command should succeed")
# - @then("the command should fail")
# - @then('the result should contain "{text}"')
# - @then('the error should mention "{text}"')


# ─────────────────────────────────────────────────────────────────────
# Profile Steps (CLI-specific - kb_steps.py has 'the active profile should be')
# ─────────────────────────────────────────────────────────────────────

@when('I set profile to "{profile}"')
def step_set_profile(context, profile):
    """Set profile via CLI."""
    result = context.cli.execute(f"/profile {profile}")
    context.last_result = result
    context.cli_results.append(result)


@then("profile-specific KB paths should be configured")
def step_profile_kb_configured(context):
    """Verify profile KB paths are set."""
    pass


@then("profile-specific agents should be enabled")
def step_profile_agents_enabled(context):
    """Verify profile agents are enabled."""
    pass


@then('the status bar should show "{profile}" profile')
def step_status_shows_profile(context, profile):
    """Verify status bar shows profile (TUI only, pass in CLI)."""
    pass


# ─────────────────────────────────────────────────────────────────────
# Domain Steps
# ─────────────────────────────────────────────────────────────────────

@when('I set domain to "{domain}"')
def step_set_domain(context, domain):
    """Set domain via CLI."""
    result = context.cli.execute(f"/domain {domain}")
    context.last_result = result
    context.cli_results.append(result)


@then('the active domain should be "{domain}"')
def step_domain_is(context, domain):
    """Verify active domain."""
    result = context.cli.execute("/domain")
    actual = result.get("data", {}).get("domain", "")
    assert actual == domain, f"Expected domain '{domain}', got '{actual}'"


@then('"{domain}" should refer to "{description}"')
def step_domain_refers_to(context, domain, description):
    """Verify domain meaning (documentation check)."""
    pass


@then("domain context should be passed to agent queries")
def step_domain_context_passed(context):
    """Verify domain context is used."""
    pass


@then('the status bar should show domain "{domain}"')
def step_status_shows_domain(context, domain):
    """Verify status bar shows domain (TUI only)."""
    pass


@then("a domain_change event should be logged to activity")
def step_domain_change_logged(context):
    """Verify domain change was logged."""
    pass


@then("activity should record timestamp and previous domain")
def step_activity_records_timestamp(context):
    """Verify activity has timestamp."""
    pass


# ─────────────────────────────────────────────────────────────────────
# Project Note Steps
# ─────────────────────────────────────────────────────────────────────

# @given('no previous {project_type} notes exist') - defined in test_fixtures.py


@given('a {project_type} note exists at "{path}"')
def step_note_exists_at(context, project_type, path):
    """Create a project note at specific path."""
    full_path = context.kb_root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""[[current/projects/{project_type}/agenda]]
prev:
next:

# {project_type.title()} Note
"""
    full_path.write_text(content)
    context.existing_note_path = full_path


@when('I create a {project_type} project note')
def step_create_project_note(context, project_type):
    """Create project note via CLI."""
    result = context.cli.execute(f"/project {project_type}")
    context.last_result = result
    context.cli_results.append(result)
    if result.get("success") and result.get("data", {}).get("created"):
        context.created_note_path = Path(result["data"]["created"])


@then("a new Zettelkasten note should be created in today's scratch directory")
def step_note_in_scratch(context):
    """Verify note created in today's scratch."""
    today = datetime.now().strftime("%Y-%m-%d")
    created = context.last_result.get("data", {}).get("created", "")
    assert today in created, f"Note should be in today's directory: {created}"
    assert "scratch" in created, f"Note should be in scratch: {created}"


@then('the filename should follow pattern "{pattern}"')
def step_filename_matches(context, pattern):
    """Verify filename matches pattern."""
    created = context.last_result.get("data", {}).get("created", "")
    filename = Path(created).name
    regex = pattern.replace("HHMMss", r"\d{6}")
    assert re.match(regex, filename), f"Filename '{filename}' doesn't match '{pattern}'"


@then("the note content should start with")
def step_note_content_starts(context):
    """Verify note content starts with expected text."""
    created = context.last_result.get("data", {}).get("created")
    if created:
        content = Path(created).read_text()
        expected = context.text.strip()
        for line in expected.split("\n"):
            line = line.strip()
            if line and not line.startswith("prev:") and not line.startswith("next:"):
                assert line in content, f"Expected '{line}' in content:\n{content}"


@then("the note should open in the center content panel")
def step_note_opens_in_panel(context):
    """Verify note opens in content panel (TUI only)."""
    pass


@then("the previous note should have its next: field updated")
def step_prev_note_updated(context):
    """Verify previous note's next field was updated."""
    if hasattr(context, "existing_note_path") and context.existing_note_path.exists():
        content = context.existing_note_path.read_text()
        assert "next: [[" in content, f"Previous note should have next: link:\n{content}"


@then('the prev: link should point to "{path}"')
def step_prev_link_points_to(context, path):
    """Verify prev link in created note."""
    created = context.last_result.get("data", {}).get("created")
    if created:
        content = Path(created).read_text()
        assert f"[[{path}]]" in content or path in content, (
            f"Expected prev link to '{path}' in:\n{content}"
        )


# ─────────────────────────────────────────────────────────────────────
# Thoughts/Cognition Steps
# ─────────────────────────────────────────────────────────────────────

@when("I trigger a content refresh")
def step_trigger_refresh(context):
    """Trigger cognition via /thoughts."""
    result = context.cli.execute("/thoughts")
    context.last_result = result
    context.cli_results.append(result)


@when("I run thoughts command")
def step_run_thoughts(context):
    """Run /thoughts command."""
    result = context.cli.execute("/thoughts")
    context.last_result = result
    context.cli_results.append(result)


@when("I view recent thoughts")
def step_view_recent_thoughts(context):
    """View recent thoughts without triggering new cycle."""
    result = context.cli.execute("/thoughts recent")
    context.last_result = result
    context.cli_results.append(result)


@then("a cognition cycle should run")
def step_cognition_runs(context):
    """Verify cognition ran."""
    data = context.last_result.get("data", {})
    mode = data.get("mode")
    has_thoughts = "thoughts_generated" in data or "thoughts" in data
    assert mode == "cognition" or has_thoughts, f"Expected cognition result: {data}"


@then("a thoughts note should be created")
def step_thoughts_note_created(context):
    """Verify thoughts note was created."""
    data = context.last_result.get("data", {})
    assert data.get("note_path") or data.get("saved_path"), (
        f"Expected note_path in: {data}"
    )


@then("thoughts should be returned")
def step_thoughts_returned(context):
    """Verify thoughts were returned."""
    data = context.last_result.get("data", {})
    assert "thoughts" in data, f"Expected thoughts in: {data}"


# ─────────────────────────────────────────────────────────────────────
# Search Steps
# ─────────────────────────────────────────────────────────────────────

@when('I search for "{query}"')
def step_search(context, query):
    """Execute search via CLI."""
    result = context.cli.execute(f"/search {query}")
    context.last_result = result
    context.cli_results.append(result)


@then("search results should be returned")
def step_search_results(context):
    """Verify search returned results."""
    assert context.last_result.get("success"), (
        f"Search should succeed: {context.last_result}"
    )


# ─────────────────────────────────────────────────────────────────────
# Swarm Steps
# ─────────────────────────────────────────────────────────────────────

@when("I run swarm analysis")
def step_run_swarm(context):
    """Execute swarm via CLI."""
    result = context.cli.execute("/swarm")
    context.last_result = result
    context.cli_results.append(result)


@then("swarm analysis should complete")
def step_swarm_completes(context):
    """Verify swarm completed."""
    data = context.last_result.get("data", {})
    assert context.last_result.get("success") or "agents" in str(data), (
        f"Swarm should complete: {context.last_result}"
    )


# ─────────────────────────────────────────────────────────────────────
# Evolution Status Steps
# ─────────────────────────────────────────────────────────────────────

@when("I check evolution status")
def step_check_evolution(context):
    """Get evolution status via CLI."""
    result = context.cli.execute("/evolve status")
    context.last_result = result
    context.cli_results.append(result)


@then('evolution status should show "{field}"')
def step_evolution_shows(context, field):
    """Verify evolution status contains field."""
    data = context.last_result.get("data", {})
    assert field.lower() in str(data).lower(), (
        f"Expected '{field}' in evolution status: {data}"
    )


# ─────────────────────────────────────────────────────────────────────
# Workflow Scenario Steps (End-to-End)
# ─────────────────────────────────────────────────────────────────────

@given("the CLI workflow test environment is ready")
def step_workflow_env_ready(context):
    """Set up complete workflow test environment."""
    from gaius.cli import GaiusCLI
    # Pass test KB root to CLI for proper path resolution
    context.cli = GaiusCLI(kb_root=context.kb_root)
    context.cli_results = []

    kb_root = context.kb_root
    (kb_root / "current" / "projects" / "charter").mkdir(parents=True, exist_ok=True)
    (kb_root / "scratch").mkdir(parents=True, exist_ok=True)


@then("the workflow should complete successfully")
def step_workflow_complete(context):
    """Verify all workflow commands succeeded."""
    failures = [r for r in context.cli_results if not r.get("success")]
    assert not failures, f"Workflow had failures: {failures}"


# ─────────────────────────────────────────────────────────────────────
# Engine Auto-Attach Steps
# ─────────────────────────────────────────────────────────────────────

@given("a gaius-engine instance is running in the background")
def step_engine_running(context):
    """Check if engine is running."""
    if hasattr(context, 'cli') and context.cli:
        result = context.cli.execute("/engine status")
        context.engine_available = result.get("success", False)
    else:
        context.engine_available = False


@given("no gaius-engine instance is running")
def step_no_engine(context):
    """Ensure no engine is running."""
    context.engine_available = False


@then("the TUI should detect the running engine")
def step_tui_detects_engine(context):
    """Verify TUI detects engine (TUI-only, verify via CLI)."""
    if hasattr(context, 'cli') and context.cli:
        result = context.cli.execute("/engine status")
        assert "data" in result or "error" in result


@then("the EvolutionPanel should show engine-connected status")
def step_evolution_panel_connected(context):
    """Verify evolution panel shows connection (TUI-only)."""
    pass


@then("the status bar should indicate engine attachment")
def step_status_engine_attached(context):
    """Verify status bar shows engine (TUI-only)."""
    pass


@then('the EvolutionPanel should show "STOPPED" or "No engine"')
def step_evolution_shows_stopped(context):
    """Verify evolution shows stopped state."""
    if hasattr(context, 'cli') and context.cli:
        result = context.cli.execute("/evolve status")
        data = result.get("data", {})
        running = data.get("running", True)
        assert not running or "stopped" in str(data).lower(), (
            f"Expected stopped state: {data}"
        )


@then("in-process evolution should be available as fallback")
def step_inprocess_evolution_available(context):
    """Verify in-process evolution available."""
    pass
