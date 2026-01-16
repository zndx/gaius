"""Step definitions for MCP server integration testing.

These steps test MCP tools using the MCP protocol via FastMCP's call_tool method,
which provides proper MCP protocol compliance for in-memory testing.

Reference: https://gist.github.com/jlowin/FastMCP-testing
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from behave import given, when, then
from behave.api.async_step import async_run_until_complete


# ─────────────────────────────────────────────────────────────────────
# MCP Protocol Tool Helper
# ─────────────────────────────────────────────────────────────────────

async def call_mcp_tool(server, name: str, arguments: dict) -> dict:
    """Call an MCP tool using the MCP protocol via FastMCP server.

    FastMCP's server.call_tool() method provides proper MCP protocol
    compliance for testing without subprocess overhead.
    """
    try:
        result = await server.call_tool(name, arguments)

        # FastMCP returns (list[TextContent], dict) tuple
        if result and len(result) >= 2:
            # Get result from the dict in position 1
            result_dict = result[1]
            if 'result' in result_dict:
                return json.loads(result_dict['result'])
            # Or from the TextContent list in position 0
            content_list = result[0]
            if content_list and hasattr(content_list[0], 'text'):
                try:
                    return json.loads(content_list[0].text)
                except json.JSONDecodeError:
                    return {"response": content_list[0].text}

        # Handle other response formats
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {"response": result}

        if isinstance(result, dict):
            return result

        return {"response": str(result)}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────
# MCP Server Initialization Steps
# ─────────────────────────────────────────────────────────────────────

@given("the MCP server is initialized")
@async_run_until_complete
async def step_mcp_server_init(context):
    """Initialize MCP server for testing via MCP protocol."""
    from gaius.mcp_server import create_server

    context.mcp_server = create_server()
    context.mcp_results = []
    context.last_mcp_result = None


@given("the MCP server is initialized with test KB root")
@async_run_until_complete
async def step_mcp_server_test_kb(context):
    """Initialize MCP server with test KB root using MCP protocol."""
    # Set environment for test KB
    os.environ["GAIUS_KB_ROOT"] = str(context.kb_root)
    os.environ["GAIUS_KB_BACKEND"] = "filesystem"

    # Reset storage singleton to pick up new KB root
    try:
        from gaius.storage.factory import reset_storage
        reset_storage()
    except ImportError:
        pass  # Module may not have reset function

    from gaius.mcp_server import create_server

    context.mcp_server = create_server()
    context.mcp_results = []
    context.last_mcp_result = None


# ─────────────────────────────────────────────────────────────────────
# Generic MCP Tool Invocation Steps
# ─────────────────────────────────────────────────────────────────────

@when('I call MCP tool "{tool_name}" with')
@async_run_until_complete
async def step_call_mcp_tool_with_table(context, tool_name):
    """Call an MCP tool with parameters from a table via MCP protocol.

    Table format:
      | parameter | value |
      | query     | test  |
      | limit     | 10    |
    """
    arguments = {}
    for row in context.table:
        key = row['parameter']
        value = row['value']
        # Parse JSON values (objects, arrays)
        if value.startswith('{') or value.startswith('['):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass  # Keep as string if not valid JSON
        # Parse numbers
        elif value.isdigit():
            value = int(value)
        elif value.replace('.', '', 1).isdigit():
            value = float(value)
        # Parse booleans
        elif value.lower() in ('true', 'false'):
            value = value.lower() == 'true'
        arguments[key] = value

    context.last_mcp_result = await call_mcp_tool(
        context.mcp_server, tool_name, arguments
    )
    context.mcp_results.append(context.last_mcp_result)


@when('I call MCP tool "{tool_name}" with argument "{arg_name}" = "{arg_value}"')
@async_run_until_complete
async def step_call_mcp_tool_single_arg(context, tool_name, arg_name, arg_value):
    """Call an MCP tool with a single argument via MCP protocol."""
    # Parse value
    if arg_value.isdigit():
        arg_value = int(arg_value)
    elif arg_value.lower() in ('true', 'false'):
        arg_value = arg_value.lower() == 'true'

    context.last_mcp_result = await call_mcp_tool(
        context.mcp_server, tool_name, {arg_name: arg_value}
    )
    context.mcp_results.append(context.last_mcp_result)


@when('I call MCP tool "{tool_name}" without arguments')
@async_run_until_complete
async def step_call_mcp_tool_no_args(context, tool_name):
    """Call an MCP tool with no arguments via MCP protocol."""
    context.last_mcp_result = await call_mcp_tool(
        context.mcp_server, tool_name, {}
    )
    context.mcp_results.append(context.last_mcp_result)


# ─────────────────────────────────────────────────────────────────────
# MCP Result Assertion Steps
# ─────────────────────────────────────────────────────────────────────

@then("the MCP result should be successful")
def step_mcp_result_success(context):
    """Verify MCP tool call succeeded (no error key)."""
    assert context.last_mcp_result is not None, "No MCP result available"
    assert "error" not in context.last_mcp_result, (
        f"MCP call failed: {context.last_mcp_result.get('error')}"
    )


@then("the MCP result should have error")
def step_mcp_result_error(context):
    """Verify MCP tool call returned an error."""
    assert context.last_mcp_result is not None, "No MCP result available"
    assert "error" in context.last_mcp_result, (
        f"Expected error but got success: {context.last_mcp_result}"
    )


@then('the MCP result should contain "{key}"')
def step_mcp_result_contains_key(context, key):
    """Verify MCP result contains a specific key."""
    assert context.last_mcp_result is not None, "No MCP result available"
    assert key in context.last_mcp_result, (
        f"Expected key '{key}' not found in result: {list(context.last_mcp_result.keys())}"
    )


@then('the MCP result "{key}" should equal "{value}"')
def step_mcp_result_key_equals(context, key, value):
    """Verify MCP result key equals expected value."""
    assert context.last_mcp_result is not None, "No MCP result available"
    actual = context.last_mcp_result.get(key)
    assert str(actual) == value, (
        f"Expected {key}='{value}', got '{actual}'"
    )


@then('the MCP result "{key}" should be greater than {value:d}')
def step_mcp_result_key_gt(context, key, value):
    """Verify MCP result numeric key is greater than value."""
    assert context.last_mcp_result is not None, "No MCP result available"
    actual = context.last_mcp_result.get(key, 0)
    assert actual > value, (
        f"Expected {key} > {value}, got {actual}"
    )


@then('the MCP result "{key}" should be at least {value:d}')
def step_mcp_result_key_gte(context, key, value):
    """Verify MCP result numeric key is at least value."""
    assert context.last_mcp_result is not None, "No MCP result available"
    actual = context.last_mcp_result.get(key, 0)
    assert actual >= value, (
        f"Expected {key} >= {value}, got {actual}"
    )


@then('the MCP result "{key}" should be a list')
def step_mcp_result_key_is_list(context, key):
    """Verify MCP result key is a list."""
    assert context.last_mcp_result is not None, "No MCP result available"
    actual = context.last_mcp_result.get(key)
    assert isinstance(actual, list), (
        f"Expected {key} to be a list, got {type(actual).__name__}"
    )


@then('the MCP result "{key}" should not be empty')
def step_mcp_result_key_not_empty(context, key):
    """Verify MCP result key is not empty (for lists/strings/dicts)."""
    assert context.last_mcp_result is not None, "No MCP result available"
    actual = context.last_mcp_result.get(key)
    assert actual, f"Expected {key} to not be empty, got {actual}"


@then('the MCP error should mention "{text}"')
def step_mcp_error_mentions(context, text):
    """Verify error message contains specific text."""
    assert context.last_mcp_result is not None, "No MCP result available"
    error = context.last_mcp_result.get("error", "")
    assert text.lower() in error.lower(), (
        f"Expected error to mention '{text}', got: {error}"
    )


# ─────────────────────────────────────────────────────────────────────
# KB Test Fixture Steps
# ─────────────────────────────────────────────────────────────────────

@given('a KB note exists at "{path}" with content')
def step_kb_note_with_docstring(context, path):
    """Create a KB note with content from docstring."""
    full_path = context.kb_root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(context.text)
    context.test_note_path = full_path


@given('a test KB note at "{path}" contains "{content}"')
def step_kb_note_with_inline_content(context, path, content):
    """Create a KB note with inline content."""
    full_path = context.kb_root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(f"# Test Note\n\n{content}")
    context.test_note_path = full_path


@then('the file "{path}" should exist')
def step_file_exists(context, path):
    """Verify file exists."""
    full_path = context.kb_root / path
    assert full_path.exists(), f"File should exist: {full_path}"


@then('the file "{path}" should not exist')
def step_file_not_exists(context, path):
    """Verify file does not exist."""
    full_path = context.kb_root / path
    assert not full_path.exists(), f"File should not exist: {full_path}"


@then('the file "{path}" should contain "{text}"')
def step_file_contains(context, path, text):
    """Verify file contains specific text."""
    full_path = context.kb_root / path
    assert full_path.exists(), f"File does not exist: {full_path}"
    content = full_path.read_text()
    assert text in content, f"Expected '{text}' in file content"


# ─────────────────────────────────────────────────────────────────────
# Agent Version Fixture Steps
# ─────────────────────────────────────────────────────────────────────

@given('an agent "{agent_id}" has an active version')
@async_run_until_complete
async def step_agent_has_version(context, agent_id):
    """Ensure an agent has an active version for testing."""
    result = await call_mcp_tool(context.mcp_server, "save_agent_version", {
        "agent_id": agent_id,
        "system_prompt": f"Test agent prompt for {agent_id}",
        "temperature": 0.7,
        "change_notes": "Test fixture version",
    })
    context.test_agent_version = result.get("version_id")


# ─────────────────────────────────────────────────────────────────────
# Async Job Handling Steps
# ─────────────────────────────────────────────────────────────────────

@then("I wait for the job to complete")
@async_run_until_complete
async def step_wait_for_job(context):
    """Wait for async scheduler job to complete."""
    job_id = context.last_mcp_result.get("job_id")
    assert job_id, "No job_id in last result"
    context.last_job_id = job_id

    for _ in range(30):  # 30 second timeout
        result = await call_mcp_tool(
            context.mcp_server, "scheduler_get_result", {"job_id": job_id}
        )
        if result.get("status") != "pending":
            context.last_mcp_result = result
            return
        await asyncio.sleep(1)

    raise TimeoutError(f"Job {job_id} did not complete in 30 seconds")


@then('the job status should be "{status}"')
def step_job_status(context, status):
    """Verify job has expected status."""
    actual = context.last_mcp_result.get("status")
    assert actual == status, f"Expected job status '{status}', got '{actual}'"


# ─────────────────────────────────────────────────────────────────────
# Debug Steps
# ─────────────────────────────────────────────────────────────────────

@then("print the MCP result")
def step_print_mcp_result(context):
    """Print MCP result for debugging."""
    print(f"\n=== MCP Result ===\n{json.dumps(context.last_mcp_result, indent=2)}\n")
