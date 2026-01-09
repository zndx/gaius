"""gRPC Critical Path Test Suite.

This suite tests critical paths at the protobuf boundary level:
- Each test starts with a protobuf request message
- Each test verifies the protobuf response structure
- Tests are derived from BDD feature scenarios but executed independently

Design Principles:
1. Tests operate at the gRPC message boundary (protobuf in → protobuf out)
2. BDD features define WHAT to test; this suite verifies HOW it works
3. Mock the servicer's dependencies, not the gRPC transport
4. Every CLI command that calls gRPC should have a corresponding test here

BDD Feature Alignment:
- features/engine/grpc.feature: OIP health, GaiusService operations
- features/engine/health.feature: Health monitoring
- features/engine/engine.feature: Orchestrator, Scheduler, Evolution

Usage:
    pytest tests/engine/test_grpc_critical_path.py -v
    pytest tests/engine/test_grpc_critical_path.py -k orchestrator
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from dataclasses import dataclass
from typing import Optional, cast, TYPE_CHECKING
from google.protobuf import empty_pb2

if TYPE_CHECKING:
    from gaius.engine.grpc.server import ServiceRegistry

# ─────────────────────────────────────────────────────────────────────────────
# Protobuf Imports - The Contract
# ─────────────────────────────────────────────────────────────────────────────

from gaius.engine.generated import (
    # Process Status Enum
    ProcessStatus,
    PROCESS_STATUS_UNSPECIFIED,
    PROCESS_STATUS_STOPPED,
    PROCESS_STATUS_STARTING,
    PROCESS_STATUS_HEALTHY,
    PROCESS_STATUS_UNHEALTHY,
    PROCESS_STATUS_FAILED,
    PROCESS_STATUS_PENDING,
    # Orchestrator Messages
    OrchestratorStatusResponse,
    GPUAllocation,
    EndpointInfo,
    StartEndpointRequest,
    StopEndpointRequest,
    RestartEndpointRequest,
    CleanStartRequest,
    CleanStartResponse,
    EndpointResponse,
    EnsureEndpointResponse,
    # Scheduler Messages
    CompleteRequest,
    CompleteResponse,
    SubmitJobRequest,
    SubmitJobResponse,
    GetJobResultRequest,
    GetJobResultResponse,
    SchedulerStatusResponse,
    XAIBudgetResponse,
    # Evolution Messages
    EvolutionStatusResponse,
    TriggerEvolutionRequest,
    EvolutionCycleResponse,
    # Health Observer Messages
    HealthObserverStatusRequest,
    HealthObserverStatusResponse,
    ForceHealthCheckResponse,
    ListIncidentsResponse,
)

from gaius.engine.grpc.servicers.gaius_servicer import GaiusServicer


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures - Mock Service Layer
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MockEndpointStatus:
    """Mock endpoint status from orchestrator."""
    status: str = "healthy"
    port: Optional[int] = 8000
    gpu_ids: Optional[list] = None
    startup_message: Optional[str] = None


@dataclass
class MockCompletionResult:
    """Mock completion result from backend."""
    content: str = "Response from LLM"
    output_tokens: int = 50
    model: str = "test-model"


class MockServiceRegistry:
    """Mock ServiceRegistry for testing protobuf contracts.

    This mocks the internal services, NOT the gRPC transport.
    Tests verify protobuf message structure, not service logic.
    """

    def __init__(
        self,
        has_orchestrator: bool = True,
        has_router: bool = True,
        has_config: bool = True,
        has_evolution: bool = True,
        has_health_observer: bool = True,
    ):
        # Orchestrator
        self.orchestrator_service = MagicMock() if has_orchestrator else None
        if self.orchestrator_service:
            self.orchestrator_service.get_status.return_value = {"endpoints": {}}
            self.orchestrator_service.start_endpoint = AsyncMock(
                return_value=MockEndpointStatus()
            )
            self.orchestrator_service.stop_endpoint = AsyncMock(return_value=True)
            self.orchestrator_service.restart_endpoint = AsyncMock(
                return_value=MockEndpointStatus()
            )
            self.orchestrator_service.clean_start = AsyncMock(
                return_value={"cleanup": {"processes_killed": 0}, "started": []}
            )
            self.orchestrator_service.ensure_endpoint = AsyncMock(
                return_value=MockEndpointStatus()
            )

        # Backend Router
        self.backend_router = MagicMock() if has_router else None
        if self.backend_router:
            self.backend_router.get_status.return_value = {
                "queue_depth": 0,
                "active_jobs": 0,
                "avg_latency_ms": 0.0,
            }
            self.backend_router.complete = AsyncMock(
                return_value=MockCompletionResult()
            )

        # Config
        if has_config:
            self.config = MagicMock()
            self.config.gpus.total = 4
            self.config.gpus.reserved = []
        else:
            self.config = None

        # Evolution - uses get_evolution_status method on services
        if has_evolution:
            async def mock_evolution_status():
                return {
                    "running": False,
                    "mode": "idle",
                    "cycles_completed": 0,
                    "current_agent": "",
                    "next_agent": "leader",
                }
            self.get_evolution_status = mock_evolution_status
        else:
            self.get_evolution_status = None

        # Health Observer
        self.health_observer_service = MagicMock() if has_health_observer else None
        if self.health_observer_service:
            self.health_observer_service.get_status.return_value = {
                "running": False,
                "incidents": [],
            }

        # Init Controller (optional)
        self.init_controller = None

    def as_registry(self) -> "ServiceRegistry":
        """Return self cast to ServiceRegistry for type-safe servicer init."""
        # MockServiceRegistry implements the ServiceRegistry protocol;
        # cast is safe because we provide all required attributes
        return cast("ServiceRegistry", self)


@pytest.fixture
def mock_services():
    """Create mock service registry."""
    return MockServiceRegistry()


@pytest.fixture
def servicer(mock_services):
    """Create GaiusServicer with mocked services."""
    return GaiusServicer(mock_services.as_registry())


@pytest.fixture
def grpc_context():
    """Create mock gRPC context."""
    ctx = MagicMock()
    ctx.set_code = MagicMock()
    ctx.set_details = MagicMock()
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: OrchestratorStatus
# BDD: features/engine/grpc.feature - "Orchestrator status via gRPC"
# CLI: /gpu status, /state
# ─────────────────────────────────────────────────────────────────────────────


class TestOrchestratorStatus:
    """Test GaiusService.OrchestratorStatus.

    BDD Scenario: Orchestrator status via gRPC
      When I call GaiusService.OrchestratorStatus
      Then the response should include total_gpus
      And the response should include available_gpus
    """

    @pytest.mark.asyncio
    async def test_response_includes_total_gpus(self, servicer, grpc_context):
        """Response includes total_gpus field."""
        response = await servicer.OrchestratorStatus(empty_pb2.Empty(), grpc_context)

        assert isinstance(response, OrchestratorStatusResponse)
        assert hasattr(response, "total_gpus")
        assert response.total_gpus == 4  # From mock config

    @pytest.mark.asyncio
    async def test_response_includes_available_gpus(self, servicer, grpc_context):
        """Response includes available_gpus field."""
        response = await servicer.OrchestratorStatus(empty_pb2.Empty(), grpc_context)

        assert hasattr(response, "available_gpus")
        assert response.available_gpus >= 0

    @pytest.mark.asyncio
    async def test_response_includes_endpoints_list(self, servicer, mock_services, grpc_context):
        """Response includes endpoints list with EndpointInfo messages."""
        mock_services.orchestrator_service.get_status.return_value = {
            "endpoints": {
                "reasoning": {"model": "qwen-32b", "status": "healthy", "port": 8000},
            }
        }

        response = await servicer.OrchestratorStatus(empty_pb2.Empty(), grpc_context)

        assert hasattr(response, "endpoints")
        assert len(response.endpoints) == 1
        assert isinstance(response.endpoints[0], EndpointInfo)
        assert response.endpoints[0].name == "reasoning"
        assert response.endpoints[0].status == PROCESS_STATUS_HEALTHY


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: Endpoint Management
# BDD: features/engine/grpc.feature - Endpoint start/stop/restart
# CLI: /gpu start, /gpu stop, /gpu restart
# ─────────────────────────────────────────────────────────────────────────────


class TestStartEndpoint:
    """Test GaiusService.StartEndpoint.

    CLI: gaius-cli --cmd "/gpu start reasoning"
    """

    @pytest.mark.asyncio
    async def test_request_message_structure(self, servicer, grpc_context):
        """StartEndpointRequest has endpoint_name field."""
        request = StartEndpointRequest(endpoint_name="reasoning")

        assert request.endpoint_name == "reasoning"

    @pytest.mark.asyncio
    async def test_success_response(self, servicer, grpc_context):
        """Successful start returns EndpointResponse with success=True."""
        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StartEndpoint(request, grpc_context)

        assert isinstance(response, EndpointResponse)
        assert response.success is True
        assert "started" in response.message.lower()

    @pytest.mark.asyncio
    async def test_failure_response(self, grpc_context):
        """Missing orchestrator returns EndpointResponse with success=False."""
        services = MockServiceRegistry(has_orchestrator=False)
        servicer = GaiusServicer(services.as_registry())

        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StartEndpoint(request, grpc_context)

        assert response.success is False
        assert "not initialized" in response.message.lower()


class TestStopEndpoint:
    """Test GaiusService.StopEndpoint.

    CLI: gaius-cli --cmd "/gpu stop reasoning"
    """

    @pytest.mark.asyncio
    async def test_request_has_force_field(self):
        """StopEndpointRequest has optional force field."""
        request = StopEndpointRequest(endpoint_name="reasoning", force=True)

        assert request.endpoint_name == "reasoning"
        assert request.force is True

    @pytest.mark.asyncio
    async def test_success_response(self, servicer, grpc_context):
        """Successful stop returns EndpointResponse with success=True."""
        request = StopEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StopEndpoint(request, grpc_context)

        assert isinstance(response, EndpointResponse)
        assert response.success is True


class TestRestartEndpoint:
    """Test GaiusService.RestartEndpoint edge cases.

    CLI: gaius-cli --cmd "/gpu restart reasoning"
    """

    @pytest.mark.asyncio
    async def test_restart_returns_endpoint_response(self, servicer, grpc_context):
        """Restart endpoint returns EndpointResponse."""
        request = RestartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.RestartEndpoint(request, grpc_context)

        assert isinstance(response, EndpointResponse)
        assert hasattr(response, "success")
        assert hasattr(response, "message")

    @pytest.mark.asyncio
    async def test_restart_success_message(self, servicer, grpc_context):
        """Successful restart includes endpoint name in message."""
        request = RestartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.RestartEndpoint(request, grpc_context)

        assert response.success is True
        assert "reasoning" in response.message.lower() or "restart" in response.message.lower()

    @pytest.mark.asyncio
    async def test_restart_no_orchestrator(self, grpc_context):
        """Missing orchestrator returns failure."""
        services = MockServiceRegistry(has_orchestrator=False)
        servicer = GaiusServicer(services.as_registry())

        request = RestartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.RestartEndpoint(request, grpc_context)

        assert response.success is False
        assert "not initialized" in response.message.lower()


class TestStartEndpointEdgeCases:
    """Test GaiusService.StartEndpoint edge cases.

    Tests error paths and boundary conditions for endpoint start.
    """

    @pytest.mark.asyncio
    async def test_start_with_empty_name(self, servicer, grpc_context):
        """Empty endpoint name is handled gracefully."""
        request = StartEndpointRequest(endpoint_name="")
        response = await servicer.StartEndpoint(request, grpc_context)

        # Should return a response (success or failure depending on impl)
        assert isinstance(response, EndpointResponse)

    @pytest.mark.asyncio
    async def test_start_returns_port_info(self, servicer, mock_services, grpc_context):
        """Successful start can include port information."""
        mock_services.orchestrator_service.start_endpoint = AsyncMock(
            return_value=MockEndpointStatus(status="healthy", port=8000)
        )

        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StartEndpoint(request, grpc_context)

        assert response.success is True

    @pytest.mark.asyncio
    async def test_start_failure_propagates_error(self, servicer, mock_services, grpc_context):
        """Orchestrator failure is reflected in response."""
        mock_services.orchestrator_service.start_endpoint = AsyncMock(
            side_effect=RuntimeError("GPU allocation failed")
        )

        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.StartEndpoint(request, grpc_context)

        assert response.success is False
        assert "failed" in response.message.lower() or "error" in response.message.lower()


class TestEnsureEndpoint:
    """Test GaiusService.EnsureEndpoint (agent-first architecture).

    This is the primary method for agents to request endpoints.
    CLI: Used internally by agents before inference calls.
    """

    @pytest.mark.asyncio
    async def test_response_structure(self, servicer, grpc_context):
        """EnsureEndpointResponse has all required fields."""
        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.EnsureEndpoint(request, grpc_context)

        assert isinstance(response, EnsureEndpointResponse)
        assert hasattr(response, "healthy")
        assert hasattr(response, "status")
        assert hasattr(response, "port")
        assert hasattr(response, "gpu_ids")
        assert hasattr(response, "message")

    @pytest.mark.asyncio
    async def test_healthy_endpoint(self, servicer, grpc_context):
        """Healthy endpoint returns healthy=True."""
        request = StartEndpointRequest(endpoint_name="reasoning")
        response = await servicer.EnsureEndpoint(request, grpc_context)

        assert response.healthy is True
        assert response.status in ("healthy", "optillm")


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: SchedulerStatus and Complete
# BDD: features/engine/grpc.feature - "Scheduler status via gRPC"
# CLI: /scheduler status, ask_local (MCP)
# ─────────────────────────────────────────────────────────────────────────────


class TestSchedulerStatus:
    """Test GaiusService.SchedulerStatus.

    BDD Scenario: Scheduler status via gRPC
      When I call GaiusService.SchedulerStatus
      Then the response should include queue_depth
    """

    @pytest.mark.asyncio
    async def test_response_includes_queue_depth(self, servicer, grpc_context):
        """Response includes queue_depth field."""
        response = await servicer.SchedulerStatus(empty_pb2.Empty(), grpc_context)

        assert isinstance(response, SchedulerStatusResponse)
        assert hasattr(response, "queue_depth")

    @pytest.mark.asyncio
    async def test_response_includes_active_jobs(self, servicer, grpc_context):
        """Response includes active_jobs field."""
        response = await servicer.SchedulerStatus(empty_pb2.Empty(), grpc_context)

        assert hasattr(response, "active_jobs")

    @pytest.mark.asyncio
    async def test_response_includes_avg_latency(self, servicer, grpc_context):
        """Response includes avg_latency_ms field."""
        response = await servicer.SchedulerStatus(empty_pb2.Empty(), grpc_context)

        assert hasattr(response, "avg_latency_ms")


class TestComplete:
    """Test GaiusService.Complete - Primary inference endpoint.

    This is the critical path for all LLM inference.
    CLI: Internal via client.call("Scheduler", "complete", {...})
    MCP: ask_local tool
    """

    @pytest.mark.asyncio
    async def test_request_message_structure(self):
        """CompleteRequest has all required fields."""
        request = CompleteRequest(
            agent_alias="reasoning",
            prompt="What is 2+2?",
            system_prompt="You are a math tutor.",
            max_tokens=100,
            temperature=0.7,
            priority="normal",
        )

        assert request.agent_alias == "reasoning"
        assert request.prompt == "What is 2+2?"
        assert request.max_tokens == 100

    @pytest.mark.asyncio
    async def test_response_message_structure(self, servicer, grpc_context):
        """CompleteResponse has all expected fields."""
        request = CompleteRequest(prompt="Hello", agent_alias="fast")
        response = await servicer.Complete(request, grpc_context)

        assert isinstance(response, CompleteResponse)
        assert hasattr(response, "text")
        assert hasattr(response, "tokens_used")
        assert hasattr(response, "latency_ms")
        assert hasattr(response, "model")

    @pytest.mark.asyncio
    async def test_successful_completion(self, servicer, grpc_context):
        """Successful completion returns text."""
        request = CompleteRequest(prompt="Hello", agent_alias="fast")
        response = await servicer.Complete(request, grpc_context)

        assert response.text == "Response from LLM"
        assert response.tokens_used == 50

    @pytest.mark.asyncio
    async def test_default_agent_is_fast(self, servicer, mock_services, grpc_context):
        """Empty agent_alias defaults to 'fast'."""
        request = CompleteRequest(prompt="Hello")
        await servicer.Complete(request, grpc_context)

        # Verify backend was called with 'fast'
        call_kwargs = mock_services.backend_router.complete.call_args.kwargs
        assert call_kwargs["agent_alias"] == "fast"


class TestCompleteEdgeCases:
    """Test GaiusService.Complete edge cases and error paths."""

    @pytest.mark.asyncio
    async def test_complete_with_empty_prompt(self, servicer, grpc_context):
        """Empty prompt is handled gracefully."""
        request = CompleteRequest(prompt="", agent_alias="fast")
        response = await servicer.Complete(request, grpc_context)

        # Should return a response (possibly with error or empty text)
        assert isinstance(response, CompleteResponse)
        assert hasattr(response, "text")

    @pytest.mark.asyncio
    async def test_complete_with_max_tokens(self, servicer, mock_services, grpc_context):
        """Max tokens parameter is passed to backend."""
        request = CompleteRequest(
            prompt="Hello",
            agent_alias="fast",
            max_tokens=10,
        )
        await servicer.Complete(request, grpc_context)

        # Verify max_tokens was passed to backend
        call_kwargs = mock_services.backend_router.complete.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 10

    @pytest.mark.asyncio
    async def test_complete_with_temperature(self, servicer, mock_services, grpc_context):
        """Temperature parameter is passed to backend."""
        request = CompleteRequest(
            prompt="Hello",
            agent_alias="fast",
            temperature=0.5,
        )
        await servicer.Complete(request, grpc_context)

        call_kwargs = mock_services.backend_router.complete.call_args.kwargs
        # Use approximate comparison due to protobuf float32 precision
        assert abs(call_kwargs.get("temperature", 0) - 0.5) < 0.01

    @pytest.mark.asyncio
    async def test_complete_with_system_prompt(self, servicer, mock_services, grpc_context):
        """System prompt is passed to backend."""
        request = CompleteRequest(
            prompt="Hello",
            agent_alias="fast",
            system_prompt="You are helpful.",
        )
        await servicer.Complete(request, grpc_context)

        call_kwargs = mock_services.backend_router.complete.call_args.kwargs
        assert call_kwargs.get("system_prompt") == "You are helpful."

    @pytest.mark.asyncio
    async def test_complete_no_backend_router(self, grpc_context):
        """Missing backend router returns error response."""
        services = MockServiceRegistry(has_router=False)
        servicer = GaiusServicer(services.as_registry())

        request = CompleteRequest(prompt="Hello", agent_alias="fast")
        response = await servicer.Complete(request, grpc_context)

        # Should return a response with error indication
        assert isinstance(response, CompleteResponse)
        # Either empty text or error in the response
        assert response.text == "" or "error" in response.text.lower()

    @pytest.mark.asyncio
    async def test_complete_backend_error(self, servicer, mock_services, grpc_context):
        """Backend error is handled gracefully."""
        mock_services.backend_router.complete = AsyncMock(
            side_effect=RuntimeError("Backend unavailable")
        )

        request = CompleteRequest(prompt="Hello", agent_alias="fast")
        response = await servicer.Complete(request, grpc_context)

        # Should return a response (graceful degradation)
        assert isinstance(response, CompleteResponse)

    @pytest.mark.asyncio
    async def test_complete_with_agent_alias(self, servicer, mock_services, grpc_context):
        """Agent alias parameter is passed to backend."""
        request = CompleteRequest(
            prompt="Hello",
            agent_alias="reasoning",
        )
        await servicer.Complete(request, grpc_context)

        call_kwargs = mock_services.backend_router.complete.call_args.kwargs
        assert call_kwargs.get("agent_alias") == "reasoning"


# ─────────────────────────────────────────────────────────────────────────────
# TIER 4: CleanStart
# BDD: features/engine/engine.feature - Clean restart functionality
# CLI: devenv tasks run restart:clean
# ─────────────────────────────────────────────────────────────────────────────


class TestCleanStart:
    """Test GaiusService.CleanStart.

    CLI: devenv tasks run restart:clean (calls CleanStart internally)
    """

    @pytest.mark.asyncio
    async def test_request_message_structure(self):
        """CleanStartRequest has endpoints field."""
        request = CleanStartRequest(endpoints=["reasoning", "fast"])

        assert list(request.endpoints) == ["reasoning", "fast"]

    @pytest.mark.asyncio
    async def test_response_message_structure(self, servicer, grpc_context):
        """CleanStartResponse has all expected fields."""
        request = CleanStartRequest()
        response = await servicer.CleanStart(request, grpc_context)

        assert isinstance(response, CleanStartResponse)
        assert hasattr(response, "success")
        assert hasattr(response, "message")
        assert hasattr(response, "processes_killed")
        assert hasattr(response, "endpoints_started")

    @pytest.mark.asyncio
    async def test_successful_clean_start(self, servicer, mock_services, grpc_context):
        """Successful clean start returns counts."""
        mock_services.orchestrator_service.clean_start = AsyncMock(
            return_value={
                "cleanup": {"processes_killed": 3},
                "started": ["reasoning"],
            }
        )

        request = CleanStartRequest(endpoints=["reasoning"])
        response = await servicer.CleanStart(request, grpc_context)

        assert response.success is True
        assert response.processes_killed == 3
        assert response.endpoints_started == 1


# ─────────────────────────────────────────────────────────────────────────────
# TIER 5: EvolutionStatus
# BDD: features/engine/grpc.feature - "Evolution status via gRPC"
# CLI: /evolve status
# ─────────────────────────────────────────────────────────────────────────────


class TestEvolutionStatus:
    """Test GaiusService.EvolutionStatus.

    BDD Scenario: Evolution status via gRPC
      When I call GaiusService.EvolutionStatus
      Then the response should include running state
      And the response should include mode
    """

    @pytest.mark.asyncio
    async def test_response_includes_running_state(self, servicer, grpc_context):
        """Response includes running field."""
        response = await servicer.EvolutionStatus(empty_pb2.Empty(), grpc_context)

        assert isinstance(response, EvolutionStatusResponse)
        assert hasattr(response, "running")

    @pytest.mark.asyncio
    async def test_response_includes_mode(self, servicer, grpc_context):
        """Response includes mode field."""
        response = await servicer.EvolutionStatus(empty_pb2.Empty(), grpc_context)

        assert hasattr(response, "mode")


# ─────────────────────────────────────────────────────────────────────────────
# TIER 6: XAI Budget
# CLI: /budget, evolution cost management
# ─────────────────────────────────────────────────────────────────────────────


class TestXAIBudget:
    """Test GaiusService.XAIBudget.

    CLI: /budget (shows daily/weekly limits)
    """

    @pytest.mark.asyncio
    async def test_response_message_structure(self, servicer, grpc_context):
        """XAIBudgetResponse has all expected fields."""
        response = await servicer.XAIBudget(empty_pb2.Empty(), grpc_context)

        assert isinstance(response, XAIBudgetResponse)
        assert hasattr(response, "daily_used")
        assert hasattr(response, "daily_limit")
        assert hasattr(response, "weekly_used")
        assert hasattr(response, "weekly_limit")
        assert hasattr(response, "reset_at")

    @pytest.mark.asyncio
    async def test_default_limits(self, servicer, grpc_context):
        """Default limits are reasonable."""
        response = await servicer.XAIBudget(empty_pb2.Empty(), grpc_context)

        assert response.daily_limit == 50
        assert response.weekly_limit == 200


# ─────────────────────────────────────────────────────────────────────────────
# TIER 7: Health Observer
# BDD: features/engine/health.feature - Health monitoring
# CLI: /health, /health fix
# ─────────────────────────────────────────────────────────────────────────────


class TestHealthObserverStatus:
    """Test GaiusService.HealthObserverStatus.

    CLI: gaius-cli --cmd "/health"
    """

    @pytest.mark.asyncio
    async def test_response_includes_running_state(self, servicer, grpc_context):
        """Response includes running field indicating daemon state."""
        response = await servicer.HealthObserverStatus(HealthObserverStatusRequest(), grpc_context)

        assert isinstance(response, HealthObserverStatusResponse)
        assert hasattr(response, "running")

    @pytest.mark.asyncio
    async def test_response_includes_active_incidents(self, servicer, grpc_context):
        """Response includes active_incidents count."""
        response = await servicer.HealthObserverStatus(HealthObserverStatusRequest(), grpc_context)

        assert hasattr(response, "active_incidents")
        assert response.active_incidents >= 0

    @pytest.mark.asyncio
    async def test_response_includes_config(self, servicer, grpc_context):
        """Response includes config with poll_interval."""
        response = await servicer.HealthObserverStatus(HealthObserverStatusRequest(), grpc_context)

        # Config is a nested message with poll_interval
        assert hasattr(response, "config")
        assert hasattr(response.config, "poll_interval")

    @pytest.mark.asyncio
    async def test_no_health_observer_service(self, grpc_context):
        """Missing health observer returns default response."""
        services = MockServiceRegistry(has_health_observer=False)
        servicer = GaiusServicer(services.as_registry())

        response = await servicer.HealthObserverStatus(HealthObserverStatusRequest(), grpc_context)

        # Should return a response (possibly with running=False)
        assert isinstance(response, HealthObserverStatusResponse)


# Note: ForceHealthCheck and ListIncidents methods are not yet implemented
# on the GaiusServicer. These would be added in a future iteration.
# The proto messages exist but the RPC methods are not wired up.


# ─────────────────────────────────────────────────────────────────────────────
# Test Suite Summary
# ─────────────────────────────────────────────────────────────────────────────
"""
Coverage by BDD Feature:

features/engine/grpc.feature:
  ✓ Orchestrator status via gRPC → TestOrchestratorStatus
  ✓ Scheduler status via gRPC → TestSchedulerStatus
  ✓ Evolution status via gRPC → TestEvolutionStatus

features/engine/engine.feature (implied):
  ✓ Start/Stop/Restart endpoints → TestStartEndpoint, TestStopEndpoint, TestRestartEndpoint
  ✓ Start edge cases → TestStartEndpointEdgeCases
  ✓ Clean start → TestCleanStart
  ✓ Inference completion → TestComplete, TestCompleteEdgeCases

features/engine/health.feature (implied):
  ✓ Health observer status → TestHealthObserverStatus
  - Force health check → Deferred (RPC not wired)
  - List incidents → Deferred (RPC not wired)

CLI Commands Covered:
  ✓ /gpu status → OrchestratorStatus
  ✓ /gpu start <name> → StartEndpoint, StartEndpointEdgeCases
  ✓ /gpu stop <name> → StopEndpoint
  ✓ /gpu restart <name> → RestartEndpoint
  ✓ /evolve status → EvolutionStatus
  ✓ /budget → XAIBudget
  ✓ /health → HealthObserverStatus
  - /cognition → Deferred (requires CognitionService mock)
"""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
