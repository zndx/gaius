Feature: Research Workflow
  As a Gaius power user
  I want to conduct end-to-end research workflows
  So I can efficiently produce well-structured project documentation

  Background:
    Given Gaius is installed and configured
    And the KB root is configured with current/ and scratch/ directories

  # ═══════════════════════════════════════════════════════════════════════
  # ENGINE: Background Evolution Daemon
  # ═══════════════════════════════════════════════════════════════════════

  @engine @tui
  Scenario: TUI auto-attaches to running background engine
    Given a gaius-engine instance is running in the background
    When I run "uv run gaius" with no arguments
    Then the TUI should detect the running engine
    And the EvolutionPanel should show engine-connected status
    And the status bar should indicate engine attachment

  @engine @tui
  Scenario: Engine status reflected in EvolutionPanel
    Given the TUI is auto-attached to a running engine
    Then the EvolutionPanel should update with live data:
      | Field              | Source              |
      | Status             | Engine daemon state |
      | Cycles             | Engine cycle count  |
      | Current Agent      | Engine current task |
      | GPU Utilization    | Engine metrics      |

  @engine @tui
  Scenario: Graceful handling when no engine is running
    Given no gaius-engine instance is running
    When I run "uv run gaius"
    Then the TUI should start normally
    And the EvolutionPanel should show "STOPPED" or "No engine"
    And in-process evolution should be available as fallback

  # ═══════════════════════════════════════════════════════════════════════
  # PROFILE AND DOMAIN SETUP
  # (Implemented: CLI + partial TUI)
  # ═══════════════════════════════════════════════════════════════════════

  @tui
  Scenario: Set work profile with '/profile' in TUI
    When I enter command "/profile cloudera"
    Then the active profile should be "cloudera"
    And profile-specific KB paths should be configured
    And profile-specific agents should be enabled
    And the status bar should show "cloudera" profile

  @tui
  Scenario: Set domain focus with '/domain' in TUI
    Given the profile is set to "cloudera"
    When I enter command "/domain csa"
    Then the active domain should be "csa"
    And "csa" should refer to "Cloudera Streaming Analytics"
    And domain context should be passed to agent queries
    And the status bar should show domain "csa"

  @mcp
  Scenario: Domain change is logged via MCP
    When I enter command "/domain csa"
    Then a domain_change event should be logged to activity
    And activity should record timestamp and previous domain

  # ═══════════════════════════════════════════════════════════════════════
  # PROJECT NOTES WITH BIDIRECTIONAL LINKING
  # (Implemented: CLI)
  # ═══════════════════════════════════════════════════════════════════════

  @tui
  Scenario: Create initial project charter note in TUI
    Given no previous charter notes exist
    When I enter command "/project charter"
    Then a new Zettelkasten note should be created in today's scratch directory
    And the filename should follow pattern "HHMMss_charter.md"
    And the note content should start with:
      """
      [[current/projects/charter/agenda]]
      prev:
      next:
      """
    And the note should open in the center content panel

  @tui
  Scenario: Create subsequent project charter note with prev link
    Given a charter note exists at "scratch/2025-02-01/153419_charter.md"
    When I enter command "/project charter"
    Then a new Zettelkasten note should be created
    And the note content should start with:
      """
      [[current/projects/charter/agenda]]
      prev: [[scratch/2025-02-01/153419_charter.md]]
      next:
      """
    And the new note should open in the center content panel

  @tui
  Scenario: Previous charter note updated with next link
    Given a charter note exists at "scratch/2025-02-01/153419_charter.md"
    And its "next:" line is empty
    When I enter command "/project charter"
    And the new note is created at "scratch/2025-02-06/140532_charter.md"
    Then the previous note "scratch/2025-02-01/153419_charter.md" should be updated
    And its "next:" line should become:
      """
      next: [[scratch/2025-02-06/140532_charter.md]]
      """

  @tui
  Scenario: Project charter maintains linked chain
    Given multiple charter notes exist in chronological order:
      | Date       | Time   | prev                                    | next                                    |
      | 2025-01-15 | 091234 |                                         | [[scratch/2025-01-20/102345_charter.md]]|
      | 2025-01-20 | 102345 | [[scratch/2025-01-15/091234_charter.md]]| [[scratch/2025-02-01/153419_charter.md]]|
      | 2025-02-01 | 153419 | [[scratch/2025-01-20/102345_charter.md]]|                                         |
    When I enter command "/project charter"
    Then the chain should extend with proper bidirectional links

  @tui
  Scenario: Project command supports different project types
    When I enter command "/project standup"
    Then a standup note should be created with:
      """
      [[current/projects/standup/template]]
      prev: [[scratch/...previous_standup...]]
      next:
      """

  # ═══════════════════════════════════════════════════════════════════════
  # CONTENT REFRESH AND COGNITION
  # (Implemented: CLI via /thoughts)
  # ═══════════════════════════════════════════════════════════════════════

  @mcp @tui
  Scenario: Trigger cognition creates thoughts note
    When I enter command "/thoughts"
    Then a cognition cycle should run
    And a new Zettelkasten "thoughts" note should be created
    And the thoughts note should contain:
      | Section              | Description                         |
      | Active patterns      | Detected patterns from recent work  |
      | Connections          | Cross-domain connections found      |
      | Questions            | Curiosity-driven questions          |
      | Summary              | Synthesis of current thinking       |
    And the thoughts note should open in the center content panel

  @mcp
  Scenario: Thoughts note links to relevant KB entries
    When a thoughts note is generated
    Then it should include wiki-links to related KB entries
    And links should be based on semantic similarity

  # ═══════════════════════════════════════════════════════════════════════
  # FULL-HEIGHT CONTENT PANEL MODE (Ctrl+Z)
  # GAP: Not implemented - need new binding and layout toggle
  # ═══════════════════════════════════════════════════════════════════════

  @tui @gap
  Scenario: Expand content panel to full height with Ctrl+Z
    Given a document is open in the center content panel
    When I press "ctrl+z"
    Then the center content panel should expand to full height
    And the grid views (MainGrid, MiniGrids) should be hidden
    And the Graph/Think/Evolution panels should be hidden
    And the document should be displayed in expanded view

  @tui @gap
  Scenario: Return from full-height mode with Ctrl+Z
    Given the content panel is in full-height mode
    When I press "ctrl+z"
    Then the normal layout should be restored
    And grid views should be visible again
    And the previously active center panel mode should be restored

  @tui @gap
  Scenario: Full-height mode preserves document state
    Given I am viewing a document at line 50
    When I press "ctrl+z" to enter full-height mode
    Then the document scroll position should be preserved
    And I should still be viewing line 50

  # ═══════════════════════════════════════════════════════════════════════
  # DOCUMENT SCROLLING AND NAVIGATION
  # GAP: j/k currently bound to grid navigation, not document scroll
  # Partial: Arrow keys may work in ContentPanel
  # ═══════════════════════════════════════════════════════════════════════

  @tui @gap
  Scenario: Scroll document with arrow keys
    Given a multi-page document is open in the content panel
    When I press the down arrow key
    Then the document should scroll down one line
    When I press the up arrow key
    Then the document should scroll up one line

  @tui @gap
  Scenario: Scroll document with vim-style keys when focused
    Given a multi-page document is open in the content panel
    And the content panel has focus
    When I press "j"
    Then the document should scroll down one line
    When I press "k"
    Then the document should scroll up one line

  @tui @gap
  Scenario: Page navigation with Ctrl+D and Ctrl+U
    Given a multi-page document is open
    When I press "ctrl+d"
    Then the document should scroll down half a page
    When I press "ctrl+u"
    Then the document should scroll up half a page

  # ═══════════════════════════════════════════════════════════════════════
  # VIM-STYLE EDITING MODE
  # GAP: No vim-style editing in ContentPanel
  # NoteEditor widget exists but vim bindings not implemented
  # ═══════════════════════════════════════════════════════════════════════

  @tui @gap
  Scenario: Jump to end and enter edit mode with Shift+G, Shift+A
    Given a document is open in the content panel
    When I press "shift+g" (capital G)
    Then the cursor should jump to the end of the document
    When I press "shift+a" (capital A)
    Then I should enter edit/insert mode
    And the cursor should be at the end of the last line
    And I should be able to append text

  @tui @gap
  Scenario: Enter insert mode with 'i'
    Given a document is open in the content panel
    And I am in normal/view mode
    When I press "i"
    Then I should enter edit/insert mode
    And the cursor should be at the current position
    And I should be able to type text

  @tui @gap
  Scenario: Exit edit mode with Escape (auto-save)
    Given I am in edit/insert mode
    And I have made changes to the document
    When I press "Escape"
    Then I should exit edit mode and return to normal mode
    And the changes should be automatically saved
    And the save should be non-blocking

  @tui @gap
  Scenario: Edit mode indicated in status
    Given I am in edit/insert mode
    Then the status bar should show "INSERT" or similar indicator
    When I press "Escape"
    Then the status bar should show "NORMAL" or remove the indicator

  # ═══════════════════════════════════════════════════════════════════════
  # DOCUMENT EXIT WITH :q
  # GAP: No vim-style command-line mode (:) in ContentPanel
  # ═══════════════════════════════════════════════════════════════════════

  @tui @gap
  Scenario: Exit document with ':q'
    Given a document is open in the content panel
    And I am in normal mode
    When I type ":q"
    Then the document should close
    And the previous document (charter note) should be shown
    And if no previous document, the content panel should show default state

  @tui @gap
  Scenario: ':q' in full-height mode returns to normal layout
    Given the content panel is in full-height mode
    When I type ":q"
    Then full-height mode should exit
    And the normal layout should be restored
    And the previous document should be shown in the content panel

  @tui @gap
  Scenario: Command-line mode with ':'
    Given I am in normal mode viewing a document
    When I type ":"
    Then a command-line input should appear at the bottom
    And I should be able to type vim-style commands
    When I press "Escape"
    Then the command-line should close without executing

  # ═══════════════════════════════════════════════════════════════════════
  # PANEL CONTROL DURING DOCUMENT EDITING
  # IMPLEMENTED: [ ] \ bindings exist but need testing
  # ═══════════════════════════════════════════════════════════════════════

  @tui
  Scenario: Close left panel with '[' while editing
    Given a document is open in the content panel (full-height mode)
    And the left-nav panel is visible
    When I press "["
    Then the left-nav panel should close
    And the content panel should expand horizontally
    And the document should remain in focus

  @tui
  Scenario: Panel toggles work in full-height mode
    Given the content panel is in full-height mode
    When I press "["
    Then the left panel should toggle
    When I press "]"
    Then the right panel should toggle
    When I press "\"
    Then both panels should toggle

  # ═══════════════════════════════════════════════════════════════════════
  # IN-DOCUMENT SEARCH WITH APPEND
  # GAP: /search --append not implemented
  # /search exists but doesn't append to document
  # ═══════════════════════════════════════════════════════════════════════

  @tui @gap
  Scenario: Search with append from edit mode
    Given I am in edit/insert mode in a document
    When I type "/search --append attach to kafka topic from flink"
    Then a search should be performed for "attach to kafka topic from flink"
    And the search results should be appended to the current document
    And the results should be formatted as markdown
    And the cursor should be positioned after the appended content
    And the original document content should be preserved

  @mcp @gap
  Scenario: Search append includes source citations
    When I use "/search --append" with a query
    Then appended results should include:
      | Element         | Format                          |
      | Result summaries| Bullet points or paragraphs     |
      | Source links    | Wiki-links to KB entries        |
      | Web sources     | URL citations if applicable     |

  @tui @gap
  Scenario: Search append respects current position
    Given the cursor is at line 50 of the document
    When I use "/search --append" with a query
    Then results should be appended at line 50 (current position)
    And existing content below should be pushed down

  # ═══════════════════════════════════════════════════════════════════════
  # SWARM REFINEMENT OF ACTIVE DOCUMENT
  # Partial: /swarm exists but doesn't append to document
  # ═══════════════════════════════════════════════════════════════════════

  @mcp @tui @gap
  Scenario: Run swarm on active document with '/swarm'
    Given a document is open in the content panel
    And the document contains research notes
    When I enter command "/swarm"
    Then the agent swarm should be activated
    And the swarm should use the active document as context
    And the content panel should show swarm progress

  @mcp @gap
  Scenario: Swarm agents append observations to document
    Given a swarm analysis is running on the active document
    Then each agent should append their observations:
      | Agent       | Section Header                    |
      | Leader      | ## Synthesis                      |
      | Risk        | ## Risk Analysis                  |
      | Opportunity | ## Opportunities                  |
      | Critic      | ## Critical Review                |
      | Domain      | ## Domain-Specific Insights       |
    And observations should be appended in agent order

  @mcp @gap
  Scenario: Swarm concludes with cross-agent summary
    When a swarm analysis completes
    Then a final section should be appended:
      """
      ## Cross-Agent Summary

      [Synthesis of all agent perspectives...]
      [Key agreements and disagreements...]
      [Recommended next steps...]
      """
    And the summary should reconcile different agent viewpoints

  @tui @gap
  Scenario: Document updated in real-time during swarm
    Given a swarm analysis is running
    Then the content panel should update as each agent completes
    And the user should see progressive refinement
    And scroll position should be maintained or follow new content

  @mcp @gap
  Scenario: Swarm respects document structure
    Given the active document has existing sections
    When swarm agents append their observations
    Then new sections should be added after existing content
    And document structure should remain coherent
    And wiki-links in the original content should be preserved

  # ═══════════════════════════════════════════════════════════════════════
  # END-TO-END WORKFLOW SCENARIO
  # ═══════════════════════════════════════════════════════════════════════

  @workflow @tui @engine @mcp
  Scenario: Complete research session workflow
    # Startup
    Given a gaius-engine is running in the background
    When I start Gaius with "uv run gaius"
    Then the TUI should auto-attach to the engine
    And the EvolutionPanel should show engine status

    # Profile and domain setup
    When I enter command "/profile cloudera"
    Then the profile should be set to "cloudera"
    When I enter command "/domain csa"
    Then the domain should be set to "csa"

    # Create project charter
    When I enter command "/project charter"
    Then a charter note should be created with proper links
    And the note should open in the content panel

    # Content refresh
    When I trigger a content refresh
    Then a thoughts note should be created
    And it should open in the content panel

    # Full-height editing
    When I press "ctrl+z"
    Then the content panel should be full-height
    When I scroll down with arrow keys
    Then the document should scroll
    When I press "shift+g" then "shift+a"
    Then I should be editing at the end
    When I press "Escape"
    Then changes should be saved
    When I type ":q"
    Then I should return to the charter note

    # Panel adjustment
    When I press "["
    Then the left panel should close
    When I press "i"
    Then I should enter edit mode

    # Search and append
    When I type "/search --append attach to kafka topic from flink"
    Then search results should be appended to the document

    # Swarm refinement
    When I enter command "/swarm"
    Then agents should analyze and append their observations
    And a cross-agent summary should be generated
    And the document should be a comprehensive research artifact

  # ═══════════════════════════════════════════════════════════════════════
  # ERROR HANDLING
  # ═══════════════════════════════════════════════════════════════════════

  @tui
  Scenario: Project command with invalid project type
    When I enter command "/project nonexistent"
    Then an error should be shown
    And available project types should be listed

  @mcp @gap
  Scenario: Search append with no results
    When I use "/search --append" with an obscure query
    And no results are found
    Then a message should be appended indicating no results
    And the document should not be corrupted

  @mcp @engine
  Scenario: Swarm fails gracefully if agents unavailable
    Given the inference stack is not available
    When I enter command "/swarm"
    Then an appropriate error should be shown
    And the document should remain unchanged
    And a suggestion to start the engine should be provided

  @tui @gap
  Scenario: Auto-save handles write errors gracefully
    Given I am in edit mode
    And the filesystem becomes read-only
    When I press "Escape" to exit edit mode
    Then an error notification should be shown
    And the unsaved content should be preserved in memory
    And the user should be prompted to save elsewhere

  # ═══════════════════════════════════════════════════════════════════════
  # CLI-TESTABLE SCENARIOS
  # These scenarios can be tested via `behave --tags=@cli` without TUI
  # ═══════════════════════════════════════════════════════════════════════

  @cli
  Scenario: Set work profile via CLI
    Given the Gaius CLI is available
    When I run CLI command "/profile cloudera"
    Then the command should succeed
    And the active profile should be "cloudera"

  @cli
  Scenario: Get current profile via CLI
    Given the Gaius CLI is available
    When I run CLI command "/profile"
    Then the command should succeed

  @cli
  Scenario: Set domain focus via CLI
    Given the Gaius CLI is available
    When I run CLI command "/domain csa"
    Then the command should succeed
    And the active domain should be "csa"

  @cli
  Scenario: Get current domain via CLI
    Given the Gaius CLI is available
    When I run CLI command "/domain"
    Then the command should succeed

  @cli
  Scenario: Create initial project charter note via CLI
    Given the Gaius CLI is available
    And the KB root is configured with current/ and scratch/ directories
    And no previous charter notes exist
    When I create a charter project note
    Then the command should succeed
    And a new Zettelkasten note should be created in today's scratch directory
    And the filename should follow pattern "HHMMss_charter.md"

  @cli
  Scenario: Create subsequent project charter note with prev link via CLI
    Given the Gaius CLI is available
    And the KB root is configured with current/ and scratch/ directories
    And no previous charter notes exist
    And a charter note exists at "scratch/2025-02-01/153419_charter.md"
    When I create a charter project note
    Then the command should succeed
    And the prev: link should point to "scratch/2025-02-01/153419_charter.md"
    And the previous note should have its next: field updated

  @cli
  Scenario: Trigger thoughts/cognition via CLI
    Given the Gaius CLI is available
    When I run CLI command "/thoughts"
    Then the command should succeed

  @cli
  Scenario: View recent thoughts via CLI
    Given the Gaius CLI is available
    When I run CLI command "/thoughts recent"
    Then the command should succeed

  @cli
  Scenario: Search knowledge base via CLI
    Given the Gaius CLI is available
    When I search for "kafka flink"
    Then the command should succeed

  @cli
  Scenario: Check evolution status via CLI
    Given the Gaius CLI is available
    When I check evolution status
    Then the command should succeed
    And evolution status should show "running"

  @cli
  Scenario: Project command without type shows error
    Given the Gaius CLI is available
    When I run CLI command "/project"
    Then the command should fail
    And the error should mention "requires type"

  @cli @workflow
  Scenario: Complete CLI workflow test
    Given the Gaius CLI is available
    And the KB root is configured with current/ and scratch/ directories
    And no previous charter notes exist

    # Set profile and domain
    When I run CLI command "/profile cloudera"
    Then the command should succeed
    When I run CLI command "/domain csa"
    Then the command should succeed

    # Create project note
    When I create a charter project note
    Then the command should succeed
    And a new Zettelkasten note should be created in today's scratch directory

    # Trigger cognition
    When I run CLI command "/thoughts"
    Then the command should succeed

    # Check evolution
    When I check evolution status
    Then the command should succeed
