"""Step definitions for engine integration testing.

These steps test gaius-engine lifecycle, connectivity, and service handlers.
"""

import asyncio
import os
import sys
from pathlib import Path

from behave import given, when, then
from behave.api.async_step import async_run_until_complete

# Add steps directory to path for imports
steps_dir = Path(__file__).parent
if str(steps_dir) not in sys.path:
    sys.path.insert(0, str(steps_dir))

from engine_fixtures import get_engine_manager, reset_engine_manager


# ─────────────────────────────────────────────────────────────────────
# Engine Lifecycle Steps
# ─────────────────────────────────────────────────────────────────────

@given("gaius-engine is running")
def step_engine_running(context):
    """Ensure gaius-engine is running.

    This step will start the engine if not already running.
    Tests fail (not skip) if engine cannot be started.
    """
    manager = get_engine_manager()
    if not manager.is_running():
        started = manager.start()
        if not started:
            raise AssertionError(
                "Could not start gaius-engine. "
                "Check logs and ensure gaius-engine is properly configured. "
                "Tests require real engine, not mocks."
            )
    context.engine_manager = manager
    # Store that engine is actually running for assertions
    context.engine_available = True


@given("gaius-engine is not running")
def step_engine_not_running(context):
    """Ensure gaius-engine is NOT running."""
    manager = get_engine_manager()
    # Only stop if we started it - don't fail if it wasn't running
    if manager._started_by_us:
        manager.stop()
    # Just verify it's not running, don't assert
    context.engine_running = manager.is_running()
    context.engine_manager = manager


@when("I start gaius-engine")
def step_start_engine(context):
    """Start the gaius-engine daemon."""
    manager = get_engine_manager()
    context.engine_start_result = manager.start()
    context.engine_manager = manager


@when("I stop gaius-engine")
def step_stop_engine(context):
    """Stop the gaius-engine daemon."""
    manager = get_engine_manager()
    context.engine_stop_result = manager.stop()


@then("the engine should be accepting connections")
def step_engine_accepting(context):
    """Verify engine is accepting connections."""
    manager = get_engine_manager()
    assert manager.is_running(), "Engine should be accepting connections"


@then("the engine should not be accepting connections")
def step_engine_not_accepting(context):
    """Verify engine is not accepting connections."""
    manager = get_engine_manager()
    assert not manager.is_running(), "Engine should not be accepting connections"


# ─────────────────────────────────────────────────────────────────────
# Engine Status Response Steps
# ─────────────────────────────────────────────────────────────────────

def _get_data(result: dict) -> dict:
    """Extract data from CLI result (handles nested 'data' key)."""
    if isinstance(result, dict):
        return result.get("data", result)
    return result


@then("the response should show engine is connected")
def step_response_engine_connected(context):
    """Verify response shows engine is connected."""
    # Skip if engine wasn't available
    if not getattr(context, 'engine_available', False):
        context.scenario.skip("Engine not available for connection test")
        return

    result = context.last_result
    assert result is not None, "No result available"
    data = _get_data(result)
    assert data.get("connected") or data.get("status") == "connected", \
        f"Expected engine connected, got: {data}"


@then("the response should show engine is not connected")
def step_response_engine_not_connected(context):
    """Verify response shows engine is not connected."""
    result = context.last_result
    assert result is not None, "No result available"
    data = _get_data(result)
    connected = data.get("connected", False)
    assert not connected, f"Expected engine not connected, got: {data}"


@then("the response should show transport type")
def step_response_transport_type(context):
    """Verify response shows transport type."""
    result = context.last_result
    assert result is not None, "No result available"
    data = _get_data(result)
    transport = data.get("transport") or data.get("transport_type")
    assert transport is not None, f"Expected transport type, got: {data}"


@then("the response should show engine health")
def step_response_engine_health(context):
    """Verify response shows engine health."""
    result = context.last_result
    assert result is not None, "No result available"
    data = _get_data(result)
    health = data.get("engine_health") or data.get("health") or data.get("status")
    assert health is not None, f"Expected health status, got: {data}"


@then('the response should suggest "{text}"')
def step_response_suggests(context, text):
    """Verify response suggests specific action."""
    result = context.last_result
    assert result is not None, "No result available"
    # Check in both error message and data
    data = _get_data(result)
    error = result.get("error", "") if isinstance(result, dict) else ""
    result_str = (str(data) + " " + error).lower()
    assert text.lower() in result_str, f"Expected suggestion '{text}' in: {result}"


# ─────────────────────────────────────────────────────────────────────
# Aeron and Socket Availability Steps
# ─────────────────────────────────────────────────────────────────────

@given("aeronmd is running")
def step_aeronmd_running(context):
    """Ensure aeronmd is running (skip if not available)."""
    # Check if aeronmd is running by looking for the process
    import subprocess
    result = subprocess.run(["pgrep", "-x", "aeronmd"], capture_output=True)
    if result.returncode != 0:
        # Mark test as skipped
        context.scenario.skip("aeronmd not running")


@given("the Unix socket exists")
def step_socket_exists(context):
    """Ensure the Unix socket exists."""
    manager = get_engine_manager()
    # Socket is created when engine starts
    if not manager.is_running():
        manager.start()
    assert os.path.exists(manager.socket_path), \
        f"Socket should exist at {manager.socket_path}"


@then("the response should show aeron_running is true")
def step_aeron_running_true(context):
    """Verify aeron is shown as running."""
    result = context.last_result
    if isinstance(result, dict):
        aeron_running = result.get("aeron_running", False)
        assert aeron_running, f"Expected aeron_running=true, got: {result}"


@then("the response should show socket_available is true")
def step_socket_available_true(context):
    """Verify socket is shown as available."""
    result = context.last_result
    if isinstance(result, dict):
        socket_available = result.get("socket_available", False)
        assert socket_available, f"Expected socket_available=true, got: {result}"


# ─────────────────────────────────────────────────────────────────────
# Engine Test and Reconnect Steps
# ─────────────────────────────────────────────────────────────────────

@then("the response should show test passed")
def step_test_passed(context):
    """Verify engine test passed."""
    result = context.last_result
    data = _get_data(result) if isinstance(result, dict) else result
    if isinstance(data, dict):
        # Check various keys: test="passed", passed=True, success=True
        passed = (
            data.get("test") == "passed"
            or data.get("passed") is True
            or data.get("success") is True
        )
        assert passed, f"Expected test passed, got: {data}"


@then("the response should show latency in milliseconds")
def step_latency_shown(context):
    """Verify latency is shown."""
    result = context.last_result
    data = _get_data(result) if isinstance(result, dict) else result
    if isinstance(data, dict):
        latency = data.get("latency_ms") or data.get("latency")
        assert latency is not None, f"Expected latency, got: {data}"


@then("the response should show test failed")
def step_test_failed(context):
    """Verify engine test failed."""
    result = context.last_result
    if isinstance(result, dict):
        passed = result.get("passed") or result.get("success")
        assert not passed, f"Expected test failed, got: {result}"


@then("the response should show connection error")
def step_connection_error(context):
    """Verify connection error is shown."""
    result = context.last_result
    if isinstance(result, dict):
        error = result.get("error") or result.get("message")
        assert error is not None, f"Expected error message, got: {result}"


@then("the response should show reconnected is true")
def step_reconnected_true(context):
    """Verify reconnection succeeded."""
    result = context.last_result
    data = _get_data(result) if isinstance(result, dict) else result
    if isinstance(data, dict):
        reconnected = data.get("reconnected", False)
        assert reconnected, f"Expected reconnected=true, got: {data}"


@then("the response should show reconnected is false")
def step_reconnected_false(context):
    """Verify reconnection failed."""
    result = context.last_result
    data = _get_data(result) if isinstance(result, dict) else result
    if isinstance(data, dict):
        reconnected = data.get("reconnected", True)
        assert not reconnected, f"Expected reconnected=false, got: {data}"


@then("the transport type should be shown")
def step_transport_shown(context):
    """Verify transport type is in response."""
    step_response_transport_type(context)


# ─────────────────────────────────────────────────────────────────────
# Service Status via Engine Steps (using gRPC)
# ─────────────────────────────────────────────────────────────────────

@when("I request Orchestrator status via engine")
@async_run_until_complete
async def step_orchestrator_status(context):
    """Request orchestrator status via gRPC engine client."""
    try:
        from gaius.client.grpc_client import GrpcEngineClient
        client = GrpcEngineClient()
        if await client.connect():
            context.last_result = await client.call("Orchestrator", "status", {})
            await client.disconnect()
        else:
            context.last_result = {"error": "Failed to connect to engine"}
    except Exception as e:
        context.last_result = {"error": str(e)}


@when("I request Scheduler status via engine")
@async_run_until_complete
async def step_scheduler_status(context):
    """Request scheduler status via gRPC engine client."""
    try:
        from gaius.client.grpc_client import GrpcEngineClient
        client = GrpcEngineClient()
        if await client.connect():
            context.last_result = await client.call("Scheduler", "status", {})
            await client.disconnect()
        else:
            context.last_result = {"error": "Failed to connect to engine"}
    except Exception as e:
        context.last_result = {"error": str(e)}


@when("I request Evolution status via engine")
@async_run_until_complete
async def step_evolution_status(context):
    """Request evolution status via gRPC engine client."""
    try:
        from gaius.client.grpc_client import GrpcEngineClient
        client = GrpcEngineClient()
        if await client.connect():
            context.last_result = await client.call("Evolution", "status", {})
            await client.disconnect()
        else:
            context.last_result = {"error": "Failed to connect to engine"}
    except Exception as e:
        context.last_result = {"error": str(e)}


@then("the response should include GPU count")
def step_gpu_count(context):
    """Verify GPU count in orchestrator response."""
    result = context.last_result
    assert isinstance(result, dict), "No result available"
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert "total_gpus" in result or "available_gpus" in result, \
        f"Expected GPU count, got: {result.keys()}"


@then("the response should be successful")
def step_response_successful(context):
    """Verify response was successful (no error)."""
    result = context.last_result
    assert isinstance(result, dict), "No result available"
    assert "error" not in result, f"Got error: {result.get('error')}"


@then("the response should include evolution mode")
def step_evolution_mode(context):
    """Verify evolution mode in response."""
    result = context.last_result
    assert isinstance(result, dict), "No result available"
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert "mode" in result, f"Expected mode, got: {result.keys()}"


@then("the response should include health status")
def step_health_status(context):
    """Verify health status in response."""
    result = context.last_result
    data = _get_data(result) if isinstance(result, dict) else result
    if isinstance(data, dict):
        # Check for health in various keys
        health = (
            data.get("engine_health")
            or data.get("health")
            or data.get("response")  # /engine test returns response with health
            or data.get("status")
        )
        assert health is not None, f"Expected health status, got: {data}"


# ─────────────────────────────────────────────────────────────────────
# Platform Diagnostics Steps
# ─────────────────────────────────────────────────────────────────────

@then("diagnostics should include engine health")
def step_diagnostics_engine_health(context):
    """Verify diagnostics include engine health."""
    result = context.last_result
    result_str = str(result).lower()
    assert "engine" in result_str or "health" in result_str, \
        f"Expected engine health in diagnostics: {result}"


@then("engine telemetry should be included")
def step_engine_telemetry(context):
    """Verify engine telemetry is included."""
    result = context.last_result
    result_str = str(result).lower()
    assert "telemetry" in result_str or "trace" in result_str or "span" in result_str, \
        f"Expected telemetry in result: {result}"


@then("diagnostics should check gaius-engine component")
def step_check_engine_component(context):
    """Verify gaius-engine component is checked."""
    result = context.last_result
    result_str = str(result).lower()
    assert "gaius-engine" in result_str or "engine" in result_str, \
        f"Expected engine component check: {result}"


@then("service status should be reported")
def step_service_status_reported(context):
    """Verify service status is reported."""
    result = context.last_result
    result_str = str(result).lower()
    assert "status" in result_str or "service" in result_str, \
        f"Expected service status: {result}"
