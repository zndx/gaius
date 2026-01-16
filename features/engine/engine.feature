@engine-integration
Feature: Engine Connectivity
  As a Gaius user
  I want reliable connectivity to gaius-engine
  So that agentic operations work consistently

  # Note: These tests require the gaius-engine daemon.
  # Tests will start the engine if not already running.
  # The engine uses gRPC on port 50051.
  # Skip in CI with: behave --tags="~@engine-integration"

  Background:
    Given the Gaius CLI is available

  # ─────────────────────────────────────────────────────────────────────
  # Engine Status
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Check engine status when running
    Given gaius-engine is running
    When I enter command "/engine status"
    Then the response should show engine is connected
    And the response should show transport type
    And the response should show engine health

  Scenario: Check engine status when not running
    Given gaius-engine is not running
    When I enter command "/engine status"
    Then the response should show engine is not connected
    And the response should suggest "devenv up"

  # ─────────────────────────────────────────────────────────────────────
  # Engine Test
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Test engine round-trip
    Given gaius-engine is running
    When I enter command "/engine test"
    Then the response should show test passed
    And the response should show latency in milliseconds
    And the response should include health status

  Scenario: Test engine when disconnected
    Given gaius-engine is not running
    When I enter command "/engine test"
    Then the response should show test failed
    And the response should show connection error

  # ─────────────────────────────────────────────────────────────────────
  # Engine Reconnect
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Reconnect to engine
    Given gaius-engine is running
    When I enter command "/engine reconnect"
    Then the response should show reconnected is true
    And the transport type should be shown

  Scenario: Reconnect fails when engine not running
    Given gaius-engine is not running
    When I enter command "/engine reconnect"
    Then the response should show reconnected is false

  # ─────────────────────────────────────────────────────────────────────
  # Integration with /ask
  # ─────────────────────────────────────────────────────────────────────

  Scenario: /ask uses engine when available
    Given gaius-engine is running
    When I enter command "/ask --platform check engine status"
    Then diagnostics should include engine health
    And engine telemetry should be included

  Scenario: /ask platform mode gathers engine diagnostics
    Given gaius-engine is running
    When I enter command "/ask --platform why is inference slow?"
    Then diagnostics should check gaius-engine component
    And service status should be reported

  # ─────────────────────────────────────────────────────────────────────
  # Service Health via Engine
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Query orchestrator status via engine
    Given gaius-engine is running
    When I request Orchestrator status via engine
    Then the response should include GPU count

  Scenario: Query scheduler status via engine
    Given gaius-engine is running
    When I request Scheduler status via engine
    Then the response should be successful

  Scenario: Query evolution status via engine
    Given gaius-engine is running
    When I request Evolution status via engine
    Then the response should include evolution mode
