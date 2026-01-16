@tier-5 @engine-integration
Feature: Self-Healing System
  As a Gaius operator
  I want the system to automatically recover from failures
  So that I don't need to manually intervene for common issues

  Background:
    Given the Gaius TUI is running

  # ─────────────────────────────────────────────────────────────────────
  # Heal Status Command
  # ─────────────────────────────────────────────────────────────────────

  Scenario: View healing system status
    When I enter command "/heal status"
    Then the content panel should show "tiers"
    And the heal status should show tier "PROCEDURAL"
    And the heal status should show tier "LOCAL_AGENT"
    And the heal status should show tier "REMOTE_ESCALATION"

  Scenario: View tier details
    When I enter command "/heal tiers"
    Then the content panel should show "tiers"
    And the heal tiers should include "max_attempts"
    And the heal tiers should include "allowed_actions"
    And the heal tiers should include "remediation_codes"

  Scenario: View healing history
    When I enter command "/heal history"
    Then the content panel should show "history"
    And the response should be valid JSON

  # ─────────────────────────────────────────────────────────────────────
  # Tier 0: Procedural Restart
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Tier 0 attempts soft reset first
    When I enter command "/heal trigger test-endpoint"
    Then the heal result should show action "SOFT_RESET"
    And the heal result should show tier "PROCEDURAL"

  Scenario: Tier 0 respects cooldown period
    Given an endpoint has a recent failed healing attempt
    When I enter command "/heal trigger test-endpoint"
    Then the heal result should indicate cooldown active

  # ─────────────────────────────────────────────────────────────────────
  # Tier 1: Local Agent Intervention
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Tier 1 requires healthy endpoints
    Given no healthy endpoints are available
    When Tier 1 healing is attempted
    Then it should escalate to Tier 2
    And the reason should include "No healthy endpoints"

  Scenario: Tier 1 only allows approved actions
    Given a healthy endpoint exists
    When the local agent suggests "clear_cuda_cache"
    Then the action should be allowed
    When the local agent suggests "arbitrary_code_execution"
    Then the action should be rejected

  # ─────────────────────────────────────────────────────────────────────
  # Tier 2: Remote Escalation
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Tier 2 only executes known remediations
    When Tier 2 receives remediation code "COLD_RESTART"
    Then the remediation should be executed

    When Tier 2 receives unknown code "ARBITRARY_CODE"
    Then the remediation should be rejected
    And the error should mention "unknown remediation"

  Scenario: Tier 2 respects budget limits
    Given the daily API budget is exhausted
    When Tier 2 escalation is attempted
    Then it should fail with budget exceeded error

  # ─────────────────────────────────────────────────────────────────────
  # Escalation Flow
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Escalation follows tier order
    Given an endpoint is unhealthy
    When healing is triggered
    Then Tier 0 should be attempted first
    And if Tier 0 fails 3 times, escalate to Tier 1
    And if Tier 1 fails, escalate to Tier 2

  Scenario: All tiers exhausted requires manual intervention
    Given all healing tiers have failed
    When healing completes
    Then the result should indicate "manual_intervention_required"

  # ─────────────────────────────────────────────────────────────────────
  # CLI Verification
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Heal commands available via CLI
    When I run "/heal" via CLI
    Then the output should show usage information
    And available subcommands should include "status"
    And available subcommands should include "trigger"
    And available subcommands should include "history"
    And available subcommands should include "tiers"

  Scenario: Heal trigger requires endpoint argument
    When I run "/heal trigger" via CLI without arguments
    Then the output should show missing endpoint error
