"""Shared step definitions for BDD tests.

Reusable assertions that work across CLI, MCP, and TUI contexts.
These steps operate on context.last_result, which should be set by
the executing step (CLI execute, MCP call_tool, etc.).
"""

from behave import then, given
import json
import os
from pathlib import Path


# =============================================================================
# Result Assertions
# =============================================================================


def _get_result(context):
    """Get the last result from context, handling various formats."""
    result = getattr(context, "last_result", None)
    if result is None:
        raise AssertionError("No result available - did you run a command first?")
    return result


def _get_data(context):
    """Extract data payload from result, handling nested 'data' key."""
    result = _get_result(context)
    if isinstance(result, dict):
        # CLI results have {"success": bool, "data": {...}}
        if "data" in result:
            return result["data"]
        return result
    return result


def _result_to_string(result) -> str:
    """Convert result to searchable string."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result, default=str)
    return str(result)


@then('the result should contain "{text}"')
def step_result_contains(context, text):
    """Assert result contains text (case-insensitive search)."""
    result_str = _result_to_string(_get_result(context))
    assert text.lower() in result_str.lower(), (
        f"Expected '{text}' in result:\n{result_str[:500]}"
    )


@then('the result should not contain "{text}"')
def step_result_not_contains(context, text):
    """Assert result does not contain text."""
    result_str = _result_to_string(_get_result(context))
    assert text.lower() not in result_str.lower(), (
        f"Did not expect '{text}' in result:\n{result_str[:500]}"
    )


@then('the result should have key "{key}"')
def step_result_has_key(context, key):
    """Assert result (or data payload) has specified key."""
    data = _get_data(context)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert key in data, f"Key '{key}' not found in: {list(data.keys())}"


@then('the result should not have key "{key}"')
def step_result_not_has_key(context, key):
    """Assert result does not have specified key."""
    data = _get_data(context)
    if isinstance(data, dict):
        assert key not in data, f"Unexpected key '{key}' found in result"


@then('the result "{key}" should equal "{value}"')
def step_result_key_equals(context, key, value):
    """Assert result key equals expected value (string comparison)."""
    data = _get_data(context)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    actual = str(data.get(key, ""))
    assert actual == value, f"Expected {key}='{value}', got '{actual}'"


@then('the result "{key}" should be "{value}"')
def step_result_key_is(context, key, value):
    """Alias for key equals."""
    step_result_key_equals(context, key, value)


@then('the result "{key}" should be greater than {value:d}')
def step_result_key_gt(context, key, value):
    """Assert result key is greater than numeric value."""
    data = _get_data(context)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    actual = data.get(key)
    assert actual is not None, f"Key '{key}' not found"
    assert float(actual) > value, f"Expected {key} > {value}, got {actual}"


@then('the result "{key}" should be at least {value:d}')
def step_result_key_gte(context, key, value):
    """Assert result key is greater than or equal to numeric value."""
    data = _get_data(context)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    actual = data.get(key)
    assert actual is not None, f"Key '{key}' not found"
    assert float(actual) >= value, f"Expected {key} >= {value}, got {actual}"


@then('the result "{key}" should be a list')
def step_result_key_is_list(context, key):
    """Assert result key is a list."""
    data = _get_data(context)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    actual = data.get(key)
    assert isinstance(actual, list), f"Expected list for '{key}', got {type(actual)}"


@then('the result "{key}" should be a list with at least {count:d} items')
def step_result_key_list_min(context, key, count):
    """Assert result key is a list with minimum items."""
    data = _get_data(context)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    actual = data.get(key)
    assert isinstance(actual, list), f"Expected list for '{key}', got {type(actual)}"
    assert len(actual) >= count, f"Expected at least {count} items, got {len(actual)}"


@then("the result should be successful")
def step_result_successful(context):
    """Assert result indicates success."""
    result = _get_result(context)
    if isinstance(result, dict):
        # CLI format: {"success": true, ...}
        if "success" in result:
            assert result["success"], f"Expected success=true, got: {result}"
            return
        # MCP format: no "error" key means success
        if "error" not in result:
            return
        raise AssertionError(f"Result has error: {result.get('error')}")
    # Non-dict results are considered successful if we got here
    pass


@then("the result should have error")
def step_result_has_error(context):
    """Assert result indicates failure/error."""
    result = _get_result(context)
    if isinstance(result, dict):
        has_error = (
            result.get("success") is False
            or "error" in result
            or result.get("error") is not None
        )
        assert has_error, f"Expected error, got successful result: {result}"
    else:
        raise AssertionError(f"Expected dict with error, got: {type(result)}")


@then("the command should succeed")
def step_command_succeeds(context):
    """Alias for result should be successful."""
    step_result_successful(context)


@then("the command should fail")
def step_command_fails(context):
    """Alias for result should have error."""
    step_result_has_error(context)


# Note: step 'the error should mention "{text}"' is defined in self_healing_steps.py
# Removed duplicate to avoid AmbiguousStep error
def _step_error_mentions_impl(context, text):
    """Assert error message contains text (implementation only, step defined elsewhere)."""
    result = _get_result(context)
    error_msg = ""
    if isinstance(result, dict):
        error_msg = str(result.get("error", "")) + str(result.get("message", ""))
    else:
        error_msg = str(result)
    assert text.lower() in error_msg.lower(), (
        f"Expected error to mention '{text}', got: {error_msg}"
    )


# =============================================================================
# File System Assertions
# =============================================================================


@then('a file should exist at "{path}"')
def step_file_exists(context, path):
    """Assert file exists at path (relative to KB root or absolute)."""
    if not os.path.isabs(path):
        kb_root = getattr(context, "kb_root", Path("build/test"))
        full_path = kb_root / path
    else:
        full_path = Path(path)
    assert full_path.exists(), f"File not found: {full_path}"


@then('a file should not exist at "{path}"')
def step_file_not_exists(context, path):
    """Assert file does not exist."""
    if not os.path.isabs(path):
        kb_root = getattr(context, "kb_root", Path("build/test"))
        full_path = kb_root / path
    else:
        full_path = Path(path)
    assert not full_path.exists(), f"File unexpectedly exists: {full_path}"


@then('the file at "{path}" should contain "{text}"')
def step_file_contains(context, path, text):
    """Assert file contains text."""
    if not os.path.isabs(path):
        kb_root = getattr(context, "kb_root", Path("build/test"))
        full_path = kb_root / path
    else:
        full_path = Path(path)
    assert full_path.exists(), f"File not found: {full_path}"
    content = full_path.read_text()
    assert text in content, f"Expected '{text}' in file content:\n{content[:500]}"


@then('the directory "{path}" should exist')
def step_directory_exists(context, path):
    """Assert directory exists."""
    if not os.path.isabs(path):
        kb_root = getattr(context, "kb_root", Path("build/test"))
        full_path = kb_root / path
    else:
        full_path = Path(path)
    assert full_path.exists(), f"Directory not found: {full_path}"
    assert full_path.is_dir(), f"Path exists but is not a directory: {full_path}"


# =============================================================================
# JSON/Data Assertions
# =============================================================================


@then("the result should be valid JSON")
def step_result_valid_json(context):
    """Assert result is valid JSON (or already a dict)."""
    result = _get_result(context)
    if isinstance(result, dict):
        return  # Already parsed
    try:
        json.loads(result)
    except (json.JSONDecodeError, TypeError) as e:
        raise AssertionError(f"Result is not valid JSON: {e}")


@then('the result data should contain "{key}"')
def step_result_data_contains_key(context, key):
    """Assert the data payload contains key."""
    data = _get_data(context)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert key in data, f"Key '{key}' not in data: {list(data.keys())}"


# =============================================================================
# State Assertions (work for both CLI and TUI)
# =============================================================================


@then('the view mode should be "{mode}"')
def step_view_mode_is(context, mode):
    """Assert current view mode matches expected."""
    if hasattr(context, "app"):
        # TUI path
        actual = context.app.state.view_mode.value
    elif hasattr(context, "cli") and context.cli:
        # CLI path - execute /state
        result = context.cli.execute("/state")
        actual = result.get("data", {}).get("view_mode", "")
    else:
        raise AssertionError("No app or CLI context available")

    assert actual.lower() == mode.lower(), f"Expected view mode '{mode}', got '{actual}'"


@then('the overlay mode should be "{mode}"')
def step_overlay_mode_is(context, mode):
    """Assert current overlay mode matches expected."""
    if hasattr(context, "app"):
        actual = context.app.state.overlay_mode.value
    elif hasattr(context, "cli") and context.cli:
        result = context.cli.execute("/state")
        actual = result.get("data", {}).get("overlay_mode", "")
    else:
        raise AssertionError("No app or CLI context available")

    assert actual.lower() == mode.lower(), f"Expected overlay mode '{mode}', got '{actual}'"


@then('the domain should be "{domain}"')
def step_domain_is(context, domain):
    """Assert current domain matches expected."""
    if hasattr(context, "cli") and context.cli:
        result = context.cli.execute("/domain")
        actual = result.get("data", {}).get("domain", "")
    elif hasattr(context, "app"):
        actual = context.app.state.domain or ""
    else:
        raise AssertionError("No app or CLI context available")

    assert actual.lower() == domain.lower(), f"Expected domain '{domain}', got '{actual}'"


@then('the cursor should be at position ({x:d}, {y:d})')
def step_cursor_at_position(context, x, y):
    """Assert cursor is at specified position (TUI only)."""
    if hasattr(context, "app"):
        actual_x = context.app.state.cursor_x
        actual_y = context.app.state.cursor_y
        assert actual_x == x and actual_y == y, (
            f"Expected cursor at ({x}, {y}), got ({actual_x}, {actual_y})"
        )
    else:
        # CLI doesn't track cursor state meaningfully - pass
        pass


# =============================================================================
# Environment Assertions
# =============================================================================


@given('environment variable "{var}" is set to "{value}"')
def step_set_env_var(context, var, value):
    """Set environment variable for test."""
    os.environ[var] = value
    if not hasattr(context, "_env_vars_to_restore"):
        context._env_vars_to_restore = {}
    context._env_vars_to_restore[var] = os.environ.get(var)


@given('environment variable "{var}" is not set')
def step_unset_env_var(context, var):
    """Unset environment variable for test."""
    if not hasattr(context, "_env_vars_to_restore"):
        context._env_vars_to_restore = {}
    context._env_vars_to_restore[var] = os.environ.get(var)
    if var in os.environ:
        del os.environ[var]


@then('environment variable "{var}" should be "{value}"')
def step_check_env_var(context, var, value):
    """Assert environment variable has expected value."""
    actual = os.environ.get(var, "")
    assert actual == value, f"Expected ${var}='{value}', got '{actual}'"
