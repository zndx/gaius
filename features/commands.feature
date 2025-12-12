Feature: Command System
  As a Gaius user
  I want to use slash commands for advanced operations
  So I can access all features without memorizing key bindings

  Background:
    Given the Gaius TUI is running

  # ─────────────────────────────────────────────────────────────────────
  # Command Mode Entry
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Enter command mode with '/'
    When I press "/"
    Then the command input should be focused
    And the command input should show "/"
    And I should be able to type a command

  Scenario: Exit command mode with Escape
    Given I am in command mode
    When I press "Escape"
    Then the command input should lose focus
    And the main grid should regain focus

  Scenario: Execute command with Enter
    Given I am in command mode
    And I have typed "help"
    When I press "Enter"
    Then the help screen should be displayed
    And command mode should exit

  # ─────────────────────────────────────────────────────────────────────
  # Help and Information Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Display help with '/help'
    When I enter command "/help"
    Then a help overlay should appear
    And the help should list all key bindings
    And the help should list all commands

  Scenario: Display help with '?' key
    When I press "?"
    Then a help overlay should appear

  Scenario: View position info with '/info'
    Given the cursor is at position (5, 5)
    When I enter command "/info"
    Then the content panel should show position (5, 5)
    And the content panel should show semantic context

  # ─────────────────────────────────────────────────────────────────────
  # Domain Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Set domain with '/domain'
    When I enter command "/domain pension risk"
    Then the active domain should be "pension risk"
    And the status bar should show "pension risk"
    And domain change should be logged to activity

  Scenario: Domain change triggers swarm analysis when enabled
    Given swarm auto-trigger is enabled
    When I enter command "/domain kudu architecture"
    Then a swarm analysis should start automatically
    And the content panel should show "Auto-triggering swarm analysis"

  # ─────────────────────────────────────────────────────────────────────
  # View and Overlay Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Set view mode with '/view'
    When I enter command "/view swarm"
    Then the view mode should be "swarm"
    And the grid should refresh with swarm visualization

  Scenario: Cycle view mode with '/view' (no argument)
    Given the view mode is "go"
    When I enter command "/view"
    Then the view mode should be "theta"

  Scenario: Set overlay mode with '/overlay'
    When I enter command "/overlay topology"
    Then the overlay mode should be "topology"
    And the grid should show H0/H1/H2 features

  Scenario: Invalid view mode shows error
    When I enter command "/view invalid"
    Then the content panel should show "Unknown view: invalid"

  # ─────────────────────────────────────────────────────────────────────
  # Ask Command - Primary Agentic Interface
  # /ask away! - General-purpose query routing with auto-detection
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Ask simple question auto-routes to reasoning
    When I enter command "/ask what is 2+2?"
    Then the query should be processed in "reasoning" mode
    And the response should include chain-of-thought analysis
    And the content panel should show the answer

  Scenario: Ask with --reason flag forces reasoning mode
    When I enter command "/ask --reason explain the CAP theorem"
    Then the query should be processed in "reasoning" mode
    And the response should use cot_reflection technique

  Scenario: Ask research question auto-routes to search
    When I enter command "/ask what is distributed consensus?"
    Then the query should be processed in "search" mode
    And hybrid search should be performed (KB + web)
    And the response should cite sources

  Scenario: Ask with --search flag forces search mode
    When I enter command "/ask --search byzantine fault tolerance"
    Then the query should be processed in "search" mode
    And results should include KB and web sources

  Scenario: Ask with --search --save creates Zettelkasten note
    When I enter command "/ask --search --save raft consensus algorithm"
    Then the query should be processed in "research" mode
    And a Zettelkasten note should be created
    And wiki-links should be generated
    And citations should be verified

  Scenario: Ask domain question auto-routes to swarm
    When I enter command "/ask analyze pension fund risk exposure"
    Then the query should be processed in "swarm" mode
    And multiple specialist agents should be invoked
    And the response should synthesize agent perspectives

  Scenario: Ask with --swarm flag forces swarm mode
    Given the domain is set to "kudu"
    When I enter command "/ask --swarm evaluate consistency guarantees"
    Then the query should be processed in "swarm" mode
    And domain context should be included

  Scenario: Ask platform error auto-routes to platform mode
    When I enter command "/ask no documents found when running /reindex"
    Then the query should be processed in "platform" mode
    And platform diagnostics should be gathered
    And remediation steps should be provided

  Scenario: Ask with --platform flag diagnoses issues
    When I enter command "/ask --platform connection refused to Qdrant"
    Then the query should be processed in "platform" mode
    And diagnostics should check Qdrant connectivity
    And suggestions should include how to start Qdrant

  Scenario: Ask platform with --save captures heuristic
    When I enter command "/ask --platform --save bm25s module not found"
    Then diagnostics should be gathered
    And remediation should be generated
    And a platform heuristic should be saved to KB

  Scenario: Ask without query shows error
    When I enter command "/ask"
    Then an error should be shown: "ask requires a question"
    And the tagline "/ask away!" should be displayed

  # ─────────────────────────────────────────────────────────────────────
  # Watch Command - OTel Telemetry Observability
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Watch status shows OTel configuration
    When I enter command "/watch status"
    Then the content panel should show OTel status
    And status should include endpoint configuration
    And status should include tracer provider info
    And status should include engine telemetry status

  Scenario: Watch traces shows recent operations
    Given inference operations have been performed
    When I enter command "/watch traces"
    Then the content panel should show recent traces
    And traces should include operation type
    And traces should include timestamps and duration

  Scenario: Watch traces with filter
    Given inference operations have been performed
    When I enter command "/watch traces operation:search"
    Then only traces matching "search" operation should be shown

  Scenario: Watch spans shows span details
    When I enter command "/watch spans"
    Then the content panel should show span information
    And spans should include service and operation names

  Scenario: Watch metrics shows platform metrics
    When I enter command "/watch metrics"
    Then the content panel should show metrics
    And metrics should include GPU utilization
    And metrics should include evolution cycle count

  Scenario: Watch metrics with filter
    When I enter command "/watch metrics gpu"
    Then only metrics containing "gpu" should be shown

  Scenario: Watch logs shows recent log entries
    When I enter command "/watch logs"
    Then the content panel should show log entries
    And logs should include level and message

  Scenario: Watch logs with level filter
    When I enter command "/watch logs level:error"
    Then only error-level logs should be shown

  Scenario: Watch service filters by service name
    When I enter command "/watch service gaius-engine"
    Then traces should be filtered to gaius-engine service

  Scenario: Watch operation filters by operation name
    When I enter command "/watch operation ask"
    Then spans should be filtered to "ask" operation

  Scenario: Watch clear clears buffers
    Given reasoning traces exist
    When I enter command "/watch clear"
    Then watch buffers should be cleared
    And subsequent "/watch traces" should show empty

  Scenario: Watch default shows traces
    When I enter command "/watch"
    Then the default behavior should show traces

  # ─────────────────────────────────────────────────────────────────────
  # Search and Research Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Search knowledge base with '/search'
    Given KB notes exist containing "distributed consensus"
    When I enter command "/search distributed consensus"
    Then the content panel should show search results
    And results should be ranked by relevance

  Scenario: Research topic with '/research'
    When I enter command "/research byzantine fault tolerance"
    Then a research operation should start
    And the Think panel should show research progress
    And results should be saved to the KB

  # ─────────────────────────────────────────────────────────────────────
  # Swarm Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Run swarm analysis with '/swarm'
    Given the domain is set to "pension risk"
    When I enter command "/swarm"
    Then a swarm analysis should start
    And the content panel should show "Running swarm analysis"
    And multiple agents should be invoked

  Scenario: Run swarm with custom query
    When I enter command "/swarm analyze regulatory compliance"
    Then a swarm analysis should start with query "analyze regulatory compliance"

  Scenario: View agent status with '/agents'
    When I enter command "/agents"
    Then the content panel should show agent roster
    And each agent should show position and status

  # ─────────────────────────────────────────────────────────────────────
  # TDA and Initialization Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: View TDA metrics with '/tda'
    When I enter command "/tda"
    Then the content panel should show TDA metrics
    And metrics should include H0, H1, H2 counts
    And metrics should include entropy value

  Scenario: Initialize platform with '/init'
    When I enter command "/init"
    Then a background initialization should start
    And the content panel should show initialization steps
    And the UI should remain responsive

  Scenario: Reindex KB with '/reindex'
    When I enter command "/reindex"
    Then a reindex operation should start in background
    And the content panel should show reindex progress

  # ─────────────────────────────────────────────────────────────────────
  # Activity and Summary Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: View daily summary with '/summary'
    When I enter command "/summary"
    Then the content panel should show daily summary
    And summary should include activity counts
    And summary should include key highlights

  Scenario: View activity log with '/activity'
    When I enter command "/activity"
    Then the content panel should show recent activity
    And activity should include timestamps
    And activity should include event types

  # ─────────────────────────────────────────────────────────────────────
  # Explain Command
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explain grid position with '/explain'
    Given the cursor is at position (9, 9)
    When I enter command "/explain"
    Then a zettelkasten note should be generated
    And the note should explain the TDA/UMAP projection
    And the note should be opened in the content panel

  Scenario: Explain with coordinates
    When I enter command "/explain 3 15"
    Then an explanation for position (3, 15) should be generated

  # ─────────────────────────────────────────────────────────────────────
  # Evolution Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Start evolution daemon with '/evolve start'
    When I enter command "/evolve start fast"
    Then the orchestrator should clean start
    And the fast endpoint should start
    And the evolution daemon should start

  Scenario: Stop evolution daemon with '/evolve stop'
    Given the evolution daemon is running
    When I enter command "/evolve stop"
    Then the evolution daemon should stop

  Scenario: View evolution status with '/evolve status'
    When I enter command "/evolve status"
    Then the content panel should show daemon status
    And status should include cycles completed
    And status should include improvement percentage

  Scenario: Manually trigger evolution with '/evolve trigger'
    Given the evolution daemon is running
    When I enter command "/evolve trigger leader"
    Then an evolution cycle should start for "leader"

  Scenario: View XAI budget with '/evolve budget'
    When I enter command "/evolve budget"
    Then the content panel should show XAI usage
    And usage should include daily and weekly limits

  # ─────────────────────────────────────────────────────────────────────
  # Inference Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: View inference status with '/inference'
    When I enter command "/inference"
    Then the content panel should show inference stack status
    And status should include endpoint health

  # ─────────────────────────────────────────────────────────────────────
  # Exit Commands
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Exit with '/quit'
    When I enter command "/quit"
    Then the TUI should exit gracefully

  Scenario: Exit with '/exit'
    When I enter command "/exit"
    Then the TUI should exit gracefully

  Scenario: Exit with '/q'
    When I enter command "/q"
    Then the TUI should exit gracefully

  # ─────────────────────────────────────────────────────────────────────
  # Unknown Command Handling
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Unknown command shows error
    When I enter command "/foobar"
    Then the content panel should show "Unknown command: foobar"
    And the content panel should suggest "/help"
