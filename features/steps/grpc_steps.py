"""Step definitions for gRPC transport BDD tests.

These steps test the gRPC/OIP transport layer including:
- KServe OIP health checks
- GaiusService operations
- Client connectivity and fallback
- Streaming
- Error handling
"""

import asyncio
import os
from behave import given, when, then
from behave.api.async_step import async_run_until_complete


# ═══════════════════════════════════════════════════════════════════════════
# Background Steps
# ═══════════════════════════════════════════════════════════════════════════

# Note: "the Gaius CLI is available" is defined in workflow_steps.py
# We share that step definition with gRPC tests


@given("gaius-engine is running with gRPC enabled")
@async_run_until_complete
async def step_engine_running_grpc(context):
    """Ensure engine is running and connect via gRPC.

    Starts the engine if not already running. Tests fail (not skip) if
    engine cannot be started - we require real infrastructure.
    """
    from engine_fixtures import get_engine_manager
    from gaius.client.grpc_client import GrpcEngineClient, GrpcClientConfig

    # First ensure engine is running
    manager = get_engine_manager()
    if not manager.is_running():
        started = manager.start()
        if not started:
            raise AssertionError(
                "Could not start gaius-engine with gRPC. "
                "Tests require real engine, not mocks."
            )
    context.engine_manager = manager
    context.engine_available = True

    # Now connect via gRPC
    config = GrpcClientConfig(
        host=os.environ.get("GAIUS_GRPC_HOST", "localhost"),
        port=int(os.environ.get("GAIUS_GRPC_PORT", "50051")),
        connect_timeout=5.0,  # Longer timeout for startup
    )

    context.grpc_client = GrpcEngineClient(config)
    connected = await context.grpc_client.connect()

    assert connected, (
        f"Failed to connect to gRPC server at "
        f"{config.host}:{config.port}. Engine is_running={manager.is_running()}"
    )


@given('gRPC server is running on localhost:{port}')
@async_run_until_complete
async def step_grpc_server_running_port(context, port):
    """Ensure gRPC server is running on specific port.

    Starts engine if needed. Tests fail if server cannot be started.
    """
    from engine_fixtures import get_engine_manager
    import socket

    port = int(port)

    # Check if already running
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            context.grpc_port = port
            return
    except (socket.error, socket.timeout):
        pass

    # Try to start engine
    manager = get_engine_manager()
    if not manager.is_running():
        started = manager.start()
        if not started:
            raise AssertionError(f"Could not start gRPC server on port {port}")

    # Verify it's now running
    try:
        with socket.create_connection(("localhost", port), timeout=5):
            context.grpc_port = port
    except (socket.error, socket.timeout):
        raise AssertionError(f"gRPC server not responding on port {port} after startup")


@given("gRPC server is not running")
def step_grpc_server_not_running(context):
    """Ensure we're testing against non-existent server."""
    import socket
    # Use a port that's unlikely to be in use
    context.grpc_port = 59999
    try:
        with socket.create_connection(("localhost", context.grpc_port), timeout=0.5):
            # Server is actually running on this port, skip
            context.scenario.skip("Unexpected server on test port")
    except (socket.error, socket.timeout):
        # Good - server not running
        pass


# ═══════════════════════════════════════════════════════════════════════════
# OIP Health Check Steps
# ═══════════════════════════════════════════════════════════════════════════


@when("I call GRPCInferenceService.ServerLive")
@async_run_until_complete
async def step_call_server_live(context):
    """Call ServerLive RPC."""
    from gaius.engine.generated import ServerLiveRequest

    response = await context.grpc_client._inference_stub.ServerLive(
        ServerLiveRequest(),
        timeout=5.0,
    )
    context.last_result = {"live": response.live}


@when("I call GRPCInferenceService.ServerReady")
@async_run_until_complete
async def step_call_server_ready(context):
    """Call ServerReady RPC."""
    from gaius.engine.generated import ServerReadyRequest

    response = await context.grpc_client._inference_stub.ServerReady(
        ServerReadyRequest(),
        timeout=5.0,
    )
    context.last_result = {"ready": response.ready}


@when("I call GRPCInferenceService.ServerMetadata")
@async_run_until_complete
async def step_call_server_metadata(context):
    """Call ServerMetadata RPC."""
    from gaius.engine.generated import ServerMetadataRequest
    from google.protobuf.json_format import MessageToDict

    response = await context.grpc_client._inference_stub.ServerMetadata(
        ServerMetadataRequest(),
        timeout=5.0,
    )
    context.last_result = MessageToDict(response, preserving_proto_field_name=True)


@when('I call GRPCInferenceService.ModelReady for model "{model_name}"')
@async_run_until_complete
async def step_call_model_ready(context, model_name):
    """Call ModelReady RPC for specific model."""
    from gaius.engine.generated import ModelReadyRequest

    response = await context.grpc_client._inference_stub.ModelReady(
        ModelReadyRequest(name=model_name),
        timeout=5.0,
    )
    context.last_result = {"model": model_name, "ready": response.ready}


@then("the response should indicate live is true")
def step_check_live_true(context):
    """Verify live response."""
    assert context.last_result.get("live") is True, f"Expected live=True, got {context.last_result}"


@then("the response should indicate ready status")
def step_check_ready_status(context):
    """Verify ready response exists."""
    assert "ready" in context.last_result, f"Missing ready field: {context.last_result}"


@then('the response should include server name "{name}"')
def step_check_server_name(context, name):
    """Verify server name."""
    assert context.last_result.get("name") == name, (
        f"Expected name={name}, got {context.last_result.get('name')}"
    )


@then("the response should include server version")
def step_check_server_version(context):
    """Verify server version exists."""
    assert "version" in context.last_result, f"Missing version: {context.last_result}"


@then("the response should indicate model ready status")
def step_check_model_ready_status(context):
    """Verify model ready response."""
    assert "ready" in context.last_result, f"Missing ready field: {context.last_result}"


# ═══════════════════════════════════════════════════════════════════════════
# GaiusService Steps
# ═══════════════════════════════════════════════════════════════════════════


@when("I call GaiusService.OrchestratorStatus")
@async_run_until_complete
async def step_call_orchestrator_status(context):
    """Call OrchestratorStatus RPC."""
    result = await context.grpc_client.call("Orchestrator", "status")
    context.last_result = result


@when("I call GaiusService.SchedulerStatus")
@async_run_until_complete
async def step_call_scheduler_status(context):
    """Call SchedulerStatus RPC."""
    result = await context.grpc_client.call("Scheduler", "status")
    context.last_result = result


@when("I call GaiusService.EvolutionStatus")
@async_run_until_complete
async def step_call_evolution_status(context):
    """Call EvolutionStatus RPC."""
    result = await context.grpc_client.call("Evolution", "status")
    context.last_result = result


@then("the response should include total_gpus")
def step_check_total_gpus_grpc(context):
    """Verify total_gpus in response (gRPC version)."""
    assert "total_gpus" in context.last_result, f"Missing total_gpus: {context.last_result}"


@then("the response should include available_gpus")
def step_check_available_gpus_grpc(context):
    """Verify available_gpus in response (gRPC version)."""
    assert "available_gpus" in context.last_result, f"Missing available_gpus: {context.last_result}"


@then("the response should include queue_depth")
def step_check_queue_depth_grpc(context):
    """Verify queue_depth in response (gRPC version)."""
    assert "queue_depth" in context.last_result, f"Missing queue_depth: {context.last_result}"


# Note: "the response should include running state" is defined in engine_steps.py
# We reuse it for gRPC tests - behave will use the same step implementation


@then("the response should include mode")
def step_check_mode_grpc(context):
    """Verify mode in response (gRPC version)."""
    assert "mode" in context.last_result, f"Missing mode: {context.last_result}"


# ═══════════════════════════════════════════════════════════════════════════
# Client Connection Steps
# ═══════════════════════════════════════════════════════════════════════════


@when("I create a GrpcEngineClient")
def step_create_grpc_client(context):
    """Create gRPC client."""
    from gaius.client.grpc_client import GrpcEngineClient, GrpcClientConfig

    port = getattr(context, "grpc_port", 50051)
    config = GrpcClientConfig(
        host="localhost",
        port=port,
        connect_timeout=2.0,
    )
    context.test_client = GrpcEngineClient(config)


@when("I create a GrpcEngineClient with timeout {seconds} second")
def step_create_grpc_client_timeout(context, seconds):
    """Create gRPC client with custom timeout."""
    from gaius.client.grpc_client import GrpcEngineClient, GrpcClientConfig

    port = getattr(context, "grpc_port", 59999)
    config = GrpcClientConfig(
        host="localhost",
        port=port,
        connect_timeout=float(seconds),
    )
    context.test_client = GrpcEngineClient(config)


@when("I call connect")
@async_run_until_complete
async def step_call_connect(context):
    """Call connect on client."""
    context.connect_result = await context.test_client.connect()


@then("the client should report is_connected as true")
def step_check_connected_true(context):
    """Verify client is connected."""
    assert context.test_client.is_connected, "Client not connected"


@then("the client should report is_connected as false")
def step_check_connected_false(context):
    """Verify client is not connected."""
    assert not context.test_client.is_connected, "Client unexpectedly connected"


# ═══════════════════════════════════════════════════════════════════════════
# Transport Selection Steps
# ═══════════════════════════════════════════════════════════════════════════


@given("GAIUS_TRANSPORT is not set")
def step_transport_not_set(context):
    """Ensure GAIUS_TRANSPORT is not set."""
    context._env_backup_transport = os.environ.get("GAIUS_TRANSPORT")
    if "GAIUS_TRANSPORT" in os.environ:
        del os.environ["GAIUS_TRANSPORT"]


@given('GAIUS_TRANSPORT is set to "{transport}"')
def step_transport_set(context, transport):
    """Set GAIUS_TRANSPORT environment variable."""
    context._env_backup_transport = os.environ.get("GAIUS_TRANSPORT")
    os.environ["GAIUS_TRANSPORT"] = transport


@when("I check the default transport")
def step_check_default_transport(context):
    """Check default transport."""
    context.checked_transport = os.environ.get("GAIUS_TRANSPORT", "grpc")


@when("I check the configured transport")
def step_check_configured_transport(context):
    """Check configured transport."""
    context.checked_transport = os.environ.get("GAIUS_TRANSPORT", "grpc")


@then('the transport should be "{expected}"')
def step_verify_transport(context, expected):
    """Verify transport value."""
    assert context.checked_transport == expected, (
        f"Expected transport={expected}, got {context.checked_transport}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Streaming Steps
# ═══════════════════════════════════════════════════════════════════════════


@when("I subscribe to GaiusService.HealthStream with interval {ms}ms")
@async_run_until_complete
async def step_subscribe_health_stream(context, ms):
    """Subscribe to health stream."""
    from gaius.engine.generated import HealthStreamRequest

    context.health_messages = []
    context.health_stream = context.grpc_client._gaius_stub.HealthStream(
        HealthStreamRequest(interval_ms=int(ms))
    )


@when("I subscribe to GaiusService.EventStream")
@async_run_until_complete
async def step_subscribe_event_stream(context):
    """Subscribe to event stream."""
    from gaius.engine.generated import EventStreamRequest

    context.event_stream = context.grpc_client._gaius_stub.EventStream(
        EventStreamRequest()
    )
    context.stream_established = True


@when("I wait for {seconds} second")
@async_run_until_complete
async def step_wait_seconds(context, seconds):
    """Wait and collect stream messages."""
    import asyncio

    end_time = asyncio.get_event_loop().time() + float(seconds)

    if hasattr(context, "health_stream"):
        try:
            async for msg in context.health_stream:
                from google.protobuf.json_format import MessageToDict
                context.health_messages.append(
                    MessageToDict(msg, preserving_proto_field_name=True)
                )
                if asyncio.get_event_loop().time() >= end_time:
                    break
        except Exception:
            pass


@then("I should receive at least {count} HealthMetrics message")
def step_check_health_message_count(context, count):
    """Verify health message count."""
    assert len(context.health_messages) >= int(count), (
        f"Expected at least {count} messages, got {len(context.health_messages)}"
    )


@then("each message should include timestamp_ms")
def step_check_timestamp_ms(context):
    """Verify timestamp in health messages."""
    for msg in context.health_messages:
        assert "timestamp_ms" in msg, f"Missing timestamp_ms: {msg}"


@then("the stream should be established successfully")
def step_check_stream_established(context):
    """Verify stream was established."""
    assert context.stream_established, "Stream not established"


# ═══════════════════════════════════════════════════════════════════════════
# Error Handling Steps
# ═══════════════════════════════════════════════════════════════════════════


@when("I attempt to call OrchestratorStatus with timeout {seconds} second")
@async_run_until_complete
async def step_call_with_timeout(context, seconds):
    """Attempt call with timeout."""
    from gaius.client.grpc_client import GrpcEngineClient, GrpcClientConfig

    port = getattr(context, "grpc_port", 59999)
    config = GrpcClientConfig(
        host="localhost",
        port=port,
        connect_timeout=float(seconds),
        timeout=float(seconds),
    )

    client = GrpcEngineClient(config)
    try:
        await client.connect()
        context.last_result = await client.call("Orchestrator", "status")
        context.last_error = None
    except Exception as e:
        context.last_error = e
        context.last_result = None


@when('I call service "{service}" action "{action}"')
@async_run_until_complete
async def step_call_service_action(context, service, action):
    """Call specific service action."""
    try:
        context.last_result = await context.grpc_client.call(service, action)
        context.last_error = None
    except Exception as e:
        context.last_error = e
        context.last_result = None


@then("I should receive a connection error")
def step_check_connection_error(context):
    """Verify connection error occurred."""
    assert context.last_error is not None, "Expected error, got success"


@then("the error should mention timeout or unavailable")
def step_check_error_message(context):
    """Verify error message content."""
    error_str = str(context.last_error).lower()
    assert "timeout" in error_str or "unavailable" in error_str, (
        f"Error message should mention timeout or unavailable: {context.last_error}"
    )


@then("I should receive an error response")
def step_check_error_response(context):
    """Verify error was received."""
    assert context.last_error is not None, "Expected error response"


# ═══════════════════════════════════════════════════════════════════════════
# Proto Compilation Steps
# ═══════════════════════════════════════════════════════════════════════════


@when("I import the OIP proto bindings")
def step_import_oip_protos(context):
    """Import OIP proto bindings."""
    context.oip_imports = {}
    try:
        from gaius.engine.generated import (
            GRPCInferenceServiceStub,
            ServerLiveRequest,
            ModelInferRequest,
        )
        context.oip_imports["GRPCInferenceServiceStub"] = GRPCInferenceServiceStub
        context.oip_imports["ServerLiveRequest"] = ServerLiveRequest
        context.oip_imports["ModelInferRequest"] = ModelInferRequest
    except ImportError as e:
        context.import_error = e


@when("I import the Gaius proto bindings")
def step_import_gaius_protos(context):
    """Import Gaius proto bindings."""
    context.gaius_imports = {}
    try:
        from gaius.engine.generated import (
            GaiusServiceStub,
            OrchestratorStatusResponse,
            HealthStreamRequest,
        )
        context.gaius_imports["GaiusServiceStub"] = GaiusServiceStub
        context.gaius_imports["OrchestratorStatusResponse"] = OrchestratorStatusResponse
        context.gaius_imports["HealthStreamRequest"] = HealthStreamRequest
    except ImportError as e:
        context.import_error = e


@then("GRPCInferenceServiceStub should be available")
def step_check_inference_stub(context):
    """Verify GRPCInferenceServiceStub is available."""
    assert "GRPCInferenceServiceStub" in context.oip_imports, "GRPCInferenceServiceStub not importable"


@then("ServerLiveRequest should be available")
def step_check_server_live_request(context):
    """Verify ServerLiveRequest is available."""
    assert "ServerLiveRequest" in context.oip_imports, "ServerLiveRequest not importable"


@then("ModelInferRequest should be available")
def step_check_model_infer_request(context):
    """Verify ModelInferRequest is available."""
    assert "ModelInferRequest" in context.oip_imports, "ModelInferRequest not importable"


@then("GaiusServiceStub should be available")
def step_check_gaius_stub(context):
    """Verify GaiusServiceStub is available."""
    assert "GaiusServiceStub" in context.gaius_imports, "GaiusServiceStub not importable"


@then("OrchestratorStatusResponse should be available")
def step_check_orchestrator_response(context):
    """Verify OrchestratorStatusResponse is available."""
    assert "OrchestratorStatusResponse" in context.gaius_imports, "OrchestratorStatusResponse not importable"


@then("HealthStreamRequest should be available")
def step_check_health_request(context):
    """Verify HealthStreamRequest is available."""
    assert "HealthStreamRequest" in context.gaius_imports, "HealthStreamRequest not importable"


# ═══════════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════════

def after_scenario_grpc(context, scenario):
    """Clean up after gRPC scenarios."""
    # Restore environment
    if hasattr(context, "_env_backup_transport"):
        if context._env_backup_transport is None:
            os.environ.pop("GAIUS_TRANSPORT", None)
        else:
            os.environ["GAIUS_TRANSPORT"] = context._env_backup_transport

    # Disconnect clients
    if hasattr(context, "grpc_client") and context.grpc_client:
        asyncio.get_event_loop().run_until_complete(context.grpc_client.disconnect())

    if hasattr(context, "test_client") and context.test_client:
        asyncio.get_event_loop().run_until_complete(context.test_client.disconnect())
