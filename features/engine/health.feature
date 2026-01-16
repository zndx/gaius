@tier-5 @engine-integration
Feature: Health Check Command
  As a Gaius operator
  I want to run system health diagnostics
  So I can identify issues with the running system

  Background:
    Given the Gaius TUI is running

  # ─────────────────────────────────────────────────────────────────────
  # Full Health Check
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Run full health check
    When I enter command "/health"
    And I wait for health check to complete
    Then the content panel should show "Health Check"
    And the health report should include "gRPC Connection"
    And the health report should include "Engine Endpoints"
    And the health report should include "Database Connection"
    And the health report should include "Cognition Daemon"
    And the health report should include "Recent Thoughts"
    And the health report should include "GPU Memory"
    And the health report should include "Disk Space"

  Scenario: Health check shows status summary
    When I enter command "/health"
    And I wait for health check to complete
    Then the health report should include "Health:"
    And the health report should include "passed"

  Scenario: Health check shows status indicators
    When I enter command "/health"
    And I wait for health check to complete
    Then the health report should contain status emoji
    And the health report should include "Check Results"

  # ─────────────────────────────────────────────────────────────────────
  # Quick Health Check (Critical Checks Only)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Run quick health check
    When I enter command "/health quick"
    And I wait for health check to complete
    Then the content panel should show "Quick Health Check"
    And the health report should include "gRPC Connection"
    And the health report should include "Database Connection"
    And the health report should NOT include "GPU Memory"
    And the health report should NOT include "Disk Space"

  # ─────────────────────────────────────────────────────────────────────
  # Category-Specific Checks
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Check engine health only
    When I enter command "/health engine"
    And I wait for health check to complete
    Then the content panel should show "Engine Health"
    And the health report should include "gRPC Connection"
    And the health report should include "Engine Endpoints"
    And the health report should NOT include "Database Connection"
    And the health report should NOT include "Cognition Daemon"

  Scenario: Check data health only
    When I enter command "/health data"
    And I wait for health check to complete
    Then the content panel should show "Data Health"
    And the health report should include "Database Connection"
    And the health report should include "Disk Space"
    And the health report should NOT include "gRPC Connection"

  Scenario: Check cognition health only
    When I enter command "/health cognition"
    And I wait for health check to complete
    Then the content panel should show "Cognition Health"
    And the health report should include "Cognition Daemon"
    And the health report should include "Recent Thoughts"
    And the health report should NOT include "Database Connection"

  Scenario: Check inference health only
    When I enter command "/health inference"
    And I wait for health check to complete
    Then the content panel should show "Inference Health"
    And the health report should include "GPU Memory"
    And the health report should NOT include "Database Connection"

  # ─────────────────────────────────────────────────────────────────────
  # Intervention Suggestions
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Health check shows suggested interventions when issues exist
    When I enter command "/health"
    And I wait for health check to complete
    Then the health report should include "Suggested Interventions"

  Scenario: Health check shows command hints
    When I enter command "/health"
    And I wait for health check to complete
    Then the health report should include "/health quick"
    And the health report should include "Categories:"

  # ─────────────────────────────────────────────────────────────────────
  # Real-World Verification (based on overnight system snapshot)
  # These capture expected behavior from actual running system
  # ─────────────────────────────────────────────────────────────────────

  @snapshot
  Scenario: Verify health check completes within reasonable time
    When I enter command "/health"
    And I wait for health check to complete
    Then the health check should complete within 5 seconds
    And the health report should show completion time

  @snapshot
  Scenario: Verify endpoint count matches expected infrastructure
    When I enter command "/health engine"
    And I wait for health check to complete
    Then the health report should show endpoint count
    And the endpoint total should be at least 1

  # ─────────────────────────────────────────────────────────────────────
  # Panel Cycling with 'g' Key
  # Tests cycling through GRAPH → THINK → EVOLUTION → NONE views
  # Default starts at GRAPH (visible), so cycle is:
  #   1 press: THINK, 2 presses: EVOLUTION, 3 presses: NONE, 4 presses: GRAPH
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Cycle from Graph to ThinkPanel
    When I press "g"
    Then the center panel mode should be "think"
    And the think panel should be visible

  Scenario: Cycle to EvolutionPanel
    When I press "g" 2 times
    Then the center panel mode should be "evolution"
    And the evolution panel should be visible

  Scenario: Cycle to hidden (none) mode
    When I press "g" 3 times
    Then the center panel mode should be "none"
    And no center panel should be visible

  Scenario: Full panel cycle returns to Graph
    When I press "g" 4 times
    Then the center panel mode should be "graph"

  # ─────────────────────────────────────────────────────────────────────
  # ThinkPanel Cross-Validation
  # Verify TUI displays match CLI/engine data sources
  # ─────────────────────────────────────────────────────────────────────

  @cross-validation
  Scenario: ThinkPanel cognition status matches CLI
    Given I capture CLI cognition status
    When I press "g"
    And I wait for panel to update
    Then the think panel cognition status should match CLI
    And the think panel should show engine activity section

  @cross-validation
  Scenario: ThinkPanel shows recent thoughts from engine
    Given I capture CLI thoughts data
    When I press "g"
    And I wait for panel to update
    Then the think panel should show thoughts section
    And the thought count should be consistent with CLI

  # ─────────────────────────────────────────────────────────────────────
  # EvolutionPanel Cross-Validation
  # Verify TUI displays match CLI/engine data sources
  # ─────────────────────────────────────────────────────────────────────

  @cross-validation
  Scenario: EvolutionPanel daemon status matches CLI
    Given I capture CLI evolution status
    When I press "g" 2 times
    And I wait for panel to update
    Then the evolution panel daemon status should match CLI
    And the evolution panel should show cycles completed

  @cross-validation
  Scenario: EvolutionPanel shows next agent from CLI
    Given I capture CLI evolution status
    When I press "g" 2 times
    And I wait for panel to update
    Then the evolution panel next agent should match CLI

  # ─────────────────────────────────────────────────────────────────────
  # Engine Health Cross-Validation
  # Verify engine connectivity reported consistently
  # ─────────────────────────────────────────────────────────────────────

  @cross-validation
  Scenario: Engine health matches across TUI panels and CLI
    Given I capture CLI engine status
    And I capture CLI health check results
    When I press "g"
    And I wait for panel to update
    Then the engine healthy indicator should be consistent
    And the endpoint count should match health check

  @cross-validation
  Scenario: GPU endpoint count consistent across views
    Given I capture CLI health check results
    When I press "g"
    And I wait for panel to update
    Then the think panel endpoint count should match health check
    When I press "g"
    And I wait for panel to update
    Then the evolution panel GPU status should be consistent
