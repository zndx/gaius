@grpc-transport
Feature: gRPC Transport
  As a Gaius user
  I want reliable gRPC connectivity to gaius-engine
  So that I can use OIP-compliant inference with streaming support

  Background:
    Given the Gaius CLI is available

  # ═══════════════════════════════════════════════════════════════════════════
  # TIER 1: OIP Health Checks
  # These are the standard KServe Open Inference Protocol health endpoints
  # ═══════════════════════════════════════════════════════════════════════════

  @oip @health @grpc-integration
  Scenario: ServerLive check via gRPC
    Given gaius-engine is running with gRPC enabled
    When I call GRPCInferenceService.ServerLive
    Then the response should indicate live is true

  @oip @health @grpc-integration
  Scenario: ServerReady check via gRPC
    Given gaius-engine is running with gRPC enabled
    When I call GRPCInferenceService.ServerReady
    Then the response should indicate ready status

  @oip @health @grpc-integration
  Scenario: ServerMetadata via gRPC
    Given gaius-engine is running with gRPC enabled
    When I call GRPCInferenceService.ServerMetadata
    Then the response should include server name "gaius-engine"
    And the response should include server version

  @oip @health @grpc-integration
  Scenario: ModelReady check via gRPC
    Given gaius-engine is running with gRPC enabled
    When I call GRPCInferenceService.ModelReady for model "fast"
    Then the response should indicate model ready status

  # ═══════════════════════════════════════════════════════════════════════════
  # TIER 2: GaiusService Operations
  # Custom Gaius extensions beyond OIP
  # ═══════════════════════════════════════════════════════════════════════════

  @gaius @orchestrator @grpc-integration
  Scenario: Orchestrator status via gRPC
    Given gaius-engine is running with gRPC enabled
    When I call GaiusService.OrchestratorStatus
    Then the response should include total_gpus
    And the response should include available_gpus

  @gaius @scheduler @grpc-integration
  Scenario: Scheduler status via gRPC
    Given gaius-engine is running with gRPC enabled
    When I call GaiusService.SchedulerStatus
    Then the response should include queue_depth

  @gaius @evolution @grpc-integration
  Scenario: Evolution status via gRPC
    Given gaius-engine is running with gRPC enabled
    When I call GaiusService.EvolutionStatus
    Then the response should include running state
    And the response should include mode

  # ═══════════════════════════════════════════════════════════════════════════
  # TIER 3: Client Selection
  # Transport auto-selection and fallback behavior
  # ═══════════════════════════════════════════════════════════════════════════

  @transport @client
  Scenario: gRPC client connects successfully
    Given gRPC server is running on localhost:50051
    When I create a GrpcEngineClient
    And I call connect
    Then the client should report is_connected as true

  @transport @client
  Scenario: gRPC client handles connection failure gracefully
    Given gRPC server is not running
    When I create a GrpcEngineClient with timeout 1 second
    And I call connect
    Then the client should report is_connected as false

  @transport @fallback
  Scenario: Transport selection prefers gRPC by default
    Given GAIUS_TRANSPORT is not set
    When I check the default transport
    Then the transport should be "grpc"

  @transport @fallback
  Scenario: Transport selection respects GAIUS_TRANSPORT environment
    Given GAIUS_TRANSPORT is set to "socket"
    When I check the configured transport
    Then the transport should be "socket"

  # ═══════════════════════════════════════════════════════════════════════════
  # TIER 4: Streaming
  # Server-side streaming for health metrics and events
  # ═══════════════════════════════════════════════════════════════════════════

  @streaming @health @grpc-integration
  Scenario: Health metrics streaming
    Given gaius-engine is running with gRPC enabled
    When I subscribe to GaiusService.HealthStream with interval 500ms
    And I wait for 1 second
    Then I should receive at least 1 HealthMetrics message
    And each message should include timestamp_ms

  @streaming @events @grpc-integration
  Scenario: Event streaming setup
    Given gaius-engine is running with gRPC enabled
    When I subscribe to GaiusService.EventStream
    Then the stream should be established successfully

  # ═══════════════════════════════════════════════════════════════════════════
  # TIER 5: Error Handling
  # Graceful error handling and status codes
  # ═══════════════════════════════════════════════════════════════════════════

  @errors @grpc-integration
  Scenario: Connection timeout returns appropriate error
    Given gRPC server is not running
    When I attempt to call OrchestratorStatus with timeout 1 second
    Then I should receive a connection error
    And the error should mention timeout or unavailable

  @errors @grpc-integration
  Scenario: Unknown service action returns appropriate error
    Given gaius-engine is running with gRPC enabled
    When I call service "Orchestrator" action "nonexistent_action"
    Then I should receive an error response

  # ═══════════════════════════════════════════════════════════════════════════
  # TIER 6: Proto Compilation
  # Ensure protos are correctly compiled and importable
  # ═══════════════════════════════════════════════════════════════════════════

  @proto @compile
  Scenario: OIP proto bindings are importable
    When I import the OIP proto bindings
    Then GRPCInferenceServiceStub should be available
    And ServerLiveRequest should be available
    And ModelInferRequest should be available

  @proto @compile
  Scenario: Gaius proto bindings are importable
    When I import the Gaius proto bindings
    Then GaiusServiceStub should be available
    And OrchestratorStatusResponse should be available
    And HealthStreamRequest should be available
