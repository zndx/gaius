"""Common test fixtures for BDD tests.

Setup steps that establish test preconditions across all tiers.
These fixtures handle KB setup, state initialization, and test data.
"""

from behave import given, when
from pathlib import Path
import os
import shutil
import uuid


# =============================================================================
# KB Fixtures
# =============================================================================


@given("the KB root is configured")
def step_kb_root_configured(context):
    """Ensure KB root is set up for testing."""
    if not hasattr(context, "kb_root"):
        context.kb_root = Path("build/test")
    context.kb_root.mkdir(parents=True, exist_ok=True)

    # Ensure standard directories exist
    for subdir in ["current", "scratch", "archive"]:
        (context.kb_root / subdir).mkdir(exist_ok=True)

    # Set environment variable
    os.environ["GAIUS_KB_ROOT"] = str(context.kb_root)


@given('a test KB note at "{path}" with content')
def step_kb_note_with_docstring(context, path):
    """Create a KB note with content from docstring."""
    content = context.text or ""
    _create_kb_note(context, path, content)


@given('a test KB note at "{path}" with content "{content}"')
def step_kb_note_inline(context, path, content):
    """Create a KB note with inline content."""
    _create_kb_note(context, path, content)


def _create_kb_note(context, path: str, content: str):
    """Helper to create KB note at path."""
    step_kb_root_configured(context)

    # Ensure path has .md extension
    if not path.endswith(".md"):
        path = path + ".md"

    full_path = context.kb_root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)

    # Track created files for cleanup
    if not hasattr(context, "_created_kb_files"):
        context._created_kb_files = []
    context._created_kb_files.append(full_path)


@given("a test KB directory structure exists")
def step_kb_directory_structure(context):
    """Create standard KB directory structure for testing."""
    step_kb_root_configured(context)

    # Create standard structure
    dirs = [
        "current/projects",
        "current/domains",
        "current/content",
        "scratch",
        "archive",
    ]
    for d in dirs:
        (context.kb_root / d).mkdir(parents=True, exist_ok=True)


@given('no previous {project_type} notes exist')
def step_no_previous_notes(context, project_type):
    """Clean up any existing project notes of specified type."""
    step_kb_root_configured(context)

    # Clean from current/projects/
    type_paths = {
        "charter": "current/projects/charter",
        "working": "current/projects/working",
        "agenda": "current/projects/agenda",
    }

    if project_type.lower() in type_paths:
        path = context.kb_root / type_paths[project_type.lower()]
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    # Also clean matching notes from scratch/ directories
    scratch = context.kb_root / "scratch"
    if scratch.exists():
        for date_dir in scratch.iterdir():
            if date_dir.is_dir():
                for note in date_dir.glob(f"*_{project_type}.md"):
                    note.unlink()


@given("the KB is empty")
def step_kb_empty(context):
    """Ensure KB has no content (clean slate)."""
    step_kb_root_configured(context)

    # Remove all content but keep directory structure
    for subdir in ["current", "scratch", "archive"]:
        path = context.kb_root / subdir
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


# =============================================================================
# State Fixtures
# =============================================================================


# @given('the cursor is at position ({x:d}, {y:d})') - defined in navigation_steps.py for TUI


@given('the domain is set to "{domain}"')
def step_domain_set(context, domain):
    """Set the domain context."""
    if hasattr(context, "cli") and context.cli:
        result = context.cli.execute(f"/domain {domain}")
        context.last_result = result
    elif hasattr(context, "app"):
        context.app.state.domain = domain


# @given('the view mode is "{mode}"') - defined in navigation_steps.py for TUI


# @given('the overlay mode is "{mode}"') - defined in navigation_steps.py for TUI


@given('the profile is set to "{profile}"')
def step_profile_set(context, profile):
    """Set the work profile."""
    if hasattr(context, "cli") and context.cli:
        result = context.cli.execute(f"/profile {profile}")
        context.last_result = result
    elif hasattr(context, "app"):
        context.app.state.profile = profile


# =============================================================================
# CLI Fixtures
# =============================================================================


@given("the Gaius CLI is available")
def step_cli_available(context):
    """Initialize CLI for testing."""
    # Ensure KB root is set up
    step_kb_root_configured(context)

    from gaius.cli import GaiusCLI
    context.cli = GaiusCLI(kb_root=context.kb_root)
    context.cli_results = []


@given("the CLI is in JSON output mode")
def step_cli_json_mode(context):
    """Configure CLI for JSON output."""
    if hasattr(context, "cli") and context.cli:
        context.cli.output_format = "json"


# =============================================================================
# Inference Fixtures
# =============================================================================


@given("inference is available")
def step_inference_available(context):
    """Verify inference stack is available (fail if not)."""
    import httpx

    optillm_url = os.environ.get("GAIUS_OPTILLM_URL", "http://localhost:8000")

    try:
        response = httpx.get(f"{optillm_url}/health", timeout=5.0)
        if response.status_code != 200:
            raise AssertionError(
                f"optillm not healthy at {optillm_url}: {response.status_code}"
            )
    except httpx.RequestError as e:
        raise AssertionError(
            f"Cannot connect to optillm at {optillm_url}: {e}\n"
            "Start inference stack with: uv run optillm --port 8000"
        )


@given('the technique is set to "{technique}"')
def step_technique_set(context, technique):
    """Set the inference technique."""
    if hasattr(context, "cli") and context.cli:
        result = context.cli.execute(f"/technique {technique}")
        context.last_result = result


# =============================================================================
# Engine Fixtures
# =============================================================================

# @given("gaius-engine is running") - defined in engine_steps.py
# @given("gaius-engine is not running") - defined in engine_steps.py


# =============================================================================
# MCP Fixtures
# =============================================================================

# @given("the MCP server is initialized") - defined in mcp_steps.py


# =============================================================================
# Test Isolation
# =============================================================================


@given("a clean test environment")
def step_clean_environment(context):
    """Set up completely clean test environment."""
    # Generate unique ID for this test
    context.test_id = str(uuid.uuid4())[:8]

    # Create isolated KB directory
    context.kb_root = Path("build/test") / context.test_id
    context.kb_root.mkdir(parents=True, exist_ok=True)

    # Set up standard structure
    step_kb_directory_structure(context)

    # Set environment
    os.environ["GAIUS_KB_ROOT"] = str(context.kb_root)


# =============================================================================
# Wait/Timing Fixtures
# =============================================================================

# @when('I wait for {seconds} second') - defined in grpc_steps.py
# @when('I wait for {seconds} seconds') - defined in grpc_steps.py
# @when('I wait for {ms:d}ms') - we can add this if needed
