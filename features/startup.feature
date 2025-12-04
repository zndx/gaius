Feature: Application Startup
  As a Gaius user
  I want a polished startup experience
  So I can immediately begin productive work

  Background:
    Given Gaius is installed and configured

  # ─────────────────────────────────────────────────────────────────────
  # Initial Launch
  # ─────────────────────────────────────────────────────────────────────

  Scenario: TUI launches with correct layout
    When I run "uv run gaius"
    Then the TUI should display within 2 seconds
    And the layout should show:
      | Element          | Position      | Visible |
      | FileTree         | Left panel    | Yes     |
      | Main Grid        | Center        | Yes     |
      | Mini-grids       | Center-right  | Yes     |
      | Content Panel    | Right panel   | Yes     |
      | Command Input    | Bottom        | Yes     |
      | Status Bar       | Top           | Yes     |

  Scenario: Grid starts at center position
    When the TUI loads
    Then the cursor should be at position (9, 9)
    And the cursor should be visually highlighted

  Scenario: Center panels start hidden
    When the TUI loads
    Then the Graph panel should be hidden
    And the Think panel should be hidden
    And the Evolution panel should be hidden
    And only the main grid and mini-grids should be visible in center

  # ─────────────────────────────────────────────────────────────────────
  # Status Bar
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Status bar shows essential information
    When the TUI loads
    Then the status bar should display:
      | Field        | Example Content    |
      | Coordinates  | (9, 9)             |
      | View Mode    | PENSION            |
      | Domain       | (current domain)   |
      | Panel Mode   | NONE               |

  Scenario: Status bar shows keyboard hints
    Then the status bar should show key hints like:
      | Key | Action  |
      | v   | view    |
      | o   | overlay |
      | g   | panel   |
      | /   | cmd     |
      | ?   | help    |

  # ─────────────────────────────────────────────────────────────────────
  # Default View State
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Default view mode is pension
    When the TUI loads
    Then the view mode should be "pension"

  Scenario: Default overlay is none
    When the TUI loads
    Then the overlay mode should be "none"

  Scenario: Candidates hidden by default
    When the TUI loads
    Then candidate markers should not be visible

  # ─────────────────────────────────────────────────────────────────────
  # Configuration Loading
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Load configuration from HOCON
    When the TUI loads
    Then configuration should be read from config/base.conf
    And profile-specific config should be merged

  Scenario: Environment variables override config
    Given GAIUS_PROFILE is set to "cloudera"
    When the TUI loads
    Then the profile should be "cloudera"

  # ─────────────────────────────────────────────────────────────────────
  # Responsive UI
  # ─────────────────────────────────────────────────────────────────────

  Scenario: UI responsive during background loading
    When the TUI loads
    And background KB indexing is in progress
    Then keyboard navigation should remain responsive
    And commands should be executable

  Scenario: Large KB doesn't block startup
    Given a KB with 1000+ documents exists
    When the TUI loads
    Then the UI should appear within 3 seconds
    And indexing should continue in background

  # ─────────────────────────────────────────────────────────────────────
  # CLI Mode
  # ─────────────────────────────────────────────────────────────────────

  Scenario: CLI non-interactive mode
    When I run "uv run gaius-cli --cmd '/state' --format json"
    Then the command should execute without TUI
    And output should be valid JSON
    And the process should exit cleanly

  Scenario: CLI command execution
    When I run "uv run gaius-cli --cmd '/help'"
    Then help text should be displayed
    And the process should exit with code 0

  # ─────────────────────────────────────────────────────────────────────
  # Error Handling on Startup
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Missing database connection handled gracefully
    Given the database is unavailable
    When the TUI loads
    Then an error message should be displayed
    And offline functionality should still work

  Scenario: Missing KB directory handled gracefully
    Given the KB root directory doesn't exist
    When the TUI loads
    Then a warning should be shown
    And the user should be prompted to run /init

  # ─────────────────────────────────────────────────────────────────────
  # Exit Behavior
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Clean exit with 'q'
    When I press "q"
    Then the TUI should exit gracefully
    And no error messages should appear

  Scenario: Exit with Ctrl+C
    When I press Ctrl+C
    Then the TUI should exit gracefully
    And terminal state should be restored
