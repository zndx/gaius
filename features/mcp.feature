Feature: MCP Server Integration
  As a Claude Code user
  I want MCP tools to work correctly
  So I can use Gaius capabilities from any MCP client

  Background:
    Given the MCP server is initialized with test KB root
    And the KB root is configured with current/ and scratch/ directories

  # ═══════════════════════════════════════════════════════════════════════
  # TIER 1: Critical User-Facing Tools
  # These are the most frequently used MCP tools
  # ═══════════════════════════════════════════════════════════════════════

  # ─────────────────────────────────────────────────────────────────────
  # KB Operations
  # ─────────────────────────────────────────────────────────────────────

  @mcp @tier1 @kb
  Scenario: Create KB entry
    When I call MCP tool "create_kb" with
      | parameter | value                      |
      | path      | scratch/mcp_test.md        |
      | content   | # MCP Test\n\nTest content |
    Then the MCP result should be successful
    And the MCP result should contain "created"
    And the file "scratch/mcp_test.md" should exist

  @mcp @tier1 @kb
  Scenario: Read KB entry
    Given a test KB note at "scratch/read_test.md" contains "Test read content"
    When I call MCP tool "read_kb" with
      | parameter | value                |
      | path      | scratch/read_test.md |
    Then the MCP result should be successful
    And the MCP result should contain "content"

  @mcp @tier1 @kb
  Scenario: Search KB entries
    Given a test KB note at "scratch/2025-01-01/search_target.md" contains "Apache Kudu columnar storage"
    When I call MCP tool "search_kb" with
      | parameter   | value |
      | query       | Kudu  |
      | max_results | 5     |
    Then the MCP result should be successful

  @mcp @tier1 @kb
  Scenario: List KB entries
    Given a test KB note at "scratch/list_test.md" contains "List test"
    When I call MCP tool "list_kb" with
      | parameter | value   |
      | directory | scratch |
    Then the MCP result should be successful

  @mcp @tier1 @kb
  Scenario: Update KB entry
    Given a test KB note at "scratch/update_test.md" contains "Original content"
    When I call MCP tool "update_kb" with
      | parameter | value                 |
      | path      | scratch/update_test.md |
      | content   | # Updated\n\nNew content |
    Then the MCP result should be successful
    And the file "scratch/update_test.md" should contain "Updated"

  @mcp @tier1 @kb
  Scenario: Delete KB entry
    Given a test KB note at "scratch/delete_test.md" contains "To be deleted"
    When I call MCP tool "delete_kb" with
      | parameter | value                 |
      | path      | scratch/delete_test.md |
    Then the MCP result should be successful
    And the file "scratch/delete_test.md" should not exist

  @mcp @tier1 @kb @security
  Scenario: KB path validation prevents directory traversal
    When I call MCP tool "create_kb" with
      | parameter | value               |
      | path      | ../../../etc/passwd |
      | content   | malicious           |
    Then the MCP result should have error

  @mcp @tier1 @kb @security
  Scenario: KB path validation rejects paths outside allowed directories
    When I call MCP tool "create_kb" with
      | parameter | value             |
      | path      | forbidden/test.md |
      | content   | should fail       |
    Then the MCP result should have error

  # ─────────────────────────────────────────────────────────────────────
  # Model Registry
  # ─────────────────────────────────────────────────────────────────────

  @mcp @tier1 @models
  Scenario: List available models
    When I call MCP tool "list_models" without arguments
    Then the MCP result should be successful
    And the MCP result should contain "models"

  @mcp @tier1 @models
  Scenario: List models filtered by capability
    When I call MCP tool "list_models" with
      | parameter  | value     |
      | capability | reasoning |
    Then the MCP result should be successful
    And the MCP result should contain "models"

  @mcp @tier1 @models
  Scenario: Get model for task
    When I call MCP tool "get_model" with
      | parameter | value     |
      | task      | reasoning |
    Then the MCP result should be successful

  # ─────────────────────────────────────────────────────────────────────
  # Status Queries (Infrastructure)
  # ─────────────────────────────────────────────────────────────────────

  @mcp @tier1 @status
  Scenario: Get evolution status
    When I call MCP tool "evolution_status" without arguments
    Then the MCP result should be successful

  @mcp @tier1 @status
  Scenario: Get orchestrator status
    When I call MCP tool "orchestrator_status" without arguments
    Then the MCP result should be successful

  @mcp @tier1 @status
  Scenario: Get scheduler status
    When I call MCP tool "scheduler_status" without arguments
    Then the MCP result should be successful

  @mcp @tier1 @status
  Scenario: Get GPU health
    When I call MCP tool "gpu_health" without arguments
    Then the MCP result should be successful

  # ═══════════════════════════════════════════════════════════════════════
  # TIER 2: Secondary User Tools
  # Agent versioning, session management, activity logging
  # ═══════════════════════════════════════════════════════════════════════

  # ─────────────────────────────────────────────────────────────────────
  # Agent Versioning (requires PostgreSQL database)
  # ─────────────────────────────────────────────────────────────────────

  @mcp @tier2 @versioning @db-required
  Scenario: Save agent version
    When I call MCP tool "save_agent_version" with
      | parameter     | value                        |
      | agent_id      | test_agent                   |
      | system_prompt | You are a helpful assistant. |
      | temperature   | 0.7                          |
      | change_notes  | Initial version              |
    Then the MCP result should be successful
    And the MCP result should contain "version_id"

  @mcp @tier2 @versioning @db-required
  Scenario: List agent versions
    Given an agent "test_agent" has an active version
    When I call MCP tool "list_agent_versions" with
      | parameter | value      |
      | agent_id  | test_agent |
    Then the MCP result should be successful
    And the MCP result should contain "versions"

  @mcp @tier2 @versioning @db-required
  Scenario: Get active agent config
    Given an agent "test_agent" has an active version
    When I call MCP tool "get_active_config" with
      | parameter | value      |
      | agent_id  | test_agent |
    Then the MCP result should be successful

  # ─────────────────────────────────────────────────────────────────────
  # Session Management (requires PostgreSQL database)
  # ─────────────────────────────────────────────────────────────────────

  @mcp @tier2 @session @db-required
  Scenario: Start session
    When I call MCP tool "start_session" with
      | parameter | value   |
      | domain    | testing |
    Then the MCP result should be successful
    And the MCP result should contain "session_id"

  @mcp @tier2 @session @db-required
  Scenario: Get session handoff
    When I call MCP tool "get_session_handoff" without arguments
    Then the MCP result should be successful

  @mcp @tier2 @session @db-required
  Scenario: List open threads
    When I call MCP tool "list_open_threads" without arguments
    Then the MCP result should be successful

  @mcp @tier2 @session @db-required
  Scenario: Create research thread
    When I call MCP tool "create_research_thread" with
      | parameter     | value                     |
      | topic         | Test research topic       |
      | domain        | testing                   |
      | initial_query | What is the test about?   |
      | goal          | Understand testing        |
    Then the MCP result should be successful
    And the MCP result should contain "thread_id"

  # ─────────────────────────────────────────────────────────────────────
  # Activity Logging (requires PostgreSQL database)
  # ─────────────────────────────────────────────────────────────────────

  @mcp @tier2 @activity @db-required
  Scenario: Log activity event
    When I call MCP tool "log_activity" with
      | parameter  | value                    |
      | event_type | command                  |
      | domain     | testing                  |
      | details    | {"action": "test_event"} |
    Then the MCP result should be successful

  @mcp @tier2 @activity @db-required
  Scenario: Get activity stats
    When I call MCP tool "get_activity_stats" with
      | parameter | value |
      | days      | 7     |
    Then the MCP result should be successful

  @mcp @tier2 @activity @db-required
  Scenario: Get daily summary
    When I call MCP tool "get_daily_summary" without arguments
    Then the MCP result should be successful

  # ─────────────────────────────────────────────────────────────────────
  # Cognition
  # ─────────────────────────────────────────────────────────────────────

  @mcp @tier2 @cognition
  Scenario: Get recent thoughts
    When I call MCP tool "get_recent_thoughts" without arguments
    Then the MCP result should be successful

  @mcp @tier2 @cognition
  Scenario: What are you thinking
    When I call MCP tool "what_are_you_thinking" without arguments
    Then the MCP result should be successful

  # ─────────────────────────────────────────────────────────────────────
  # Reflection
  # ─────────────────────────────────────────────────────────────────────

  @mcp @tier2 @reflection
  Scenario: Quick thought on topic
    When I call MCP tool "quick_thought" with
      | parameter | value           |
      | topic     | software testing |
    Then the MCP result should be successful

  # ═══════════════════════════════════════════════════════════════════════
  # TIER 3: Inference-Dependent Tools
  # Require optillm/vLLM stack to be running
  # ═══════════════════════════════════════════════════════════════════════

  @mcp @tier3 @inference @requires_inference
  Scenario: Local inference query
    When I call MCP tool "ask_local" with
      | parameter   | value                                     |
      | question    | What is 2+2? Answer with just the number. |
      | max_tokens  | 50                                        |
    Then the MCP result should be successful
    And the MCP result should contain "response"

  @mcp @tier3 @inference @requires_inference
  Scenario: Reasoning query
    When I call MCP tool "ask_reasoning" with
      | parameter  | value                                            |
      | question   | If A implies B, and A is true, what can we say? |
      | max_tokens | 200                                              |
    Then the MCP result should be successful
    And the MCP result should contain "response"

  @mcp @tier3 @cognition @requires_inference
  Scenario: Trigger cognition cycle
    When I call MCP tool "trigger_cognition" with
      | parameter      | value  |
      | max_thoughts   | 3      |
      | trigger_reason | manual |
    Then the MCP result should be successful

  @mcp @tier3 @swarm @requires_inference
  Scenario: Run swarm analysis
    When I call MCP tool "run_swarm" with
      | parameter  | value                              |
      | query      | What are the benefits of testing?  |
      | domain     | software                           |
      | num_agents | 3                                  |
    Then the MCP result should be successful
    And the MCP result should contain "synthesis"

  @mcp @tier3 @reflection @requires_inference
  Scenario: Deep reflection
    When I call MCP tool "reflect" with
      | parameter | value    |
      | depth     | moderate |
    Then the MCP result should be successful

  # ═══════════════════════════════════════════════════════════════════════
  # TIER 4: Engine Proxy Tools
  # These tools proxy to gaius-engine when GAIUS_ENABLE_FALLBACKS=true
  # ═══════════════════════════════════════════════════════════════════════

  @mcp @tier4 @engine_proxy
  Scenario: Orchestrator status with fallbacks enabled
    Given GAIUS_ENABLE_FALLBACKS is set to "true"
    When I call MCP tool "orchestrator_status" without arguments
    Then the MCP result should be successful

  @mcp @tier4 @engine_proxy
  Scenario: Scheduler status with fallbacks enabled
    Given GAIUS_ENABLE_FALLBACKS is set to "true"
    When I call MCP tool "scheduler_status" without arguments
    Then the MCP result should be successful

  @mcp @tier4 @engine_proxy
  Scenario: Evolution status with fallbacks enabled
    Given GAIUS_ENABLE_FALLBACKS is set to "true"
    When I call MCP tool "evolution_status" without arguments
    Then the MCP result should be successful

  @mcp @tier4 @engine_proxy @engine-integration
  Scenario: GPU health with fallbacks enabled
    Given GAIUS_ENABLE_FALLBACKS is set to "true"
    When I call MCP tool "gpu_health" without arguments
    Then the MCP result should be successful

  # ═══════════════════════════════════════════════════════════════════════
  # ERROR HANDLING
  # ═══════════════════════════════════════════════════════════════════════

  @mcp @errors
  Scenario: Read non-existent KB entry
    When I call MCP tool "read_kb" with
      | parameter | value                    |
      | path      | scratch/does_not_exist.md |
    Then the MCP result should have error

  @mcp @errors @db-required
  Scenario: Get versions for non-existent agent
    When I call MCP tool "list_agent_versions" with
      | parameter | value                    |
      | agent_id  | nonexistent_agent_xyz123 |
    Then the MCP result should be successful
    # Should return empty list, not error
