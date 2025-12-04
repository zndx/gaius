Feature: Grid Navigation
  As a Gaius user
  I want to navigate the 19x19 grid using vim-style keys
  So I can explore data spatially with precision

  Background:
    Given the Gaius TUI is running
    And the cursor starts at the center position (9, 9)

  # ─────────────────────────────────────────────────────────────────────
  # Vim-Style Movement (h/j/k/l)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Move cursor right with 'l'
    When I press "l" 3 times
    Then the cursor should be at position (12, 9)
    And the mini-grids should update to reflect the new position

  Scenario: Move cursor left with 'h'
    When I press "h" 2 times
    Then the cursor should be at position (7, 9)

  Scenario: Move cursor down with 'j'
    When I press "j" 4 times
    Then the cursor should be at position (9, 13)

  Scenario: Move cursor up with 'k'
    When I press "k" 5 times
    Then the cursor should be at position (9, 4)

  Scenario: Cursor respects left boundary
    Given the cursor is at position (0, 9)
    When I press "h"
    Then the cursor should remain at position (0, 9)

  Scenario: Cursor respects right boundary
    Given the cursor is at position (18, 9)
    When I press "l"
    Then the cursor should remain at position (18, 9)

  Scenario: Cursor respects top boundary
    Given the cursor is at position (9, 0)
    When I press "k"
    Then the cursor should remain at position (9, 0)

  Scenario: Cursor respects bottom boundary
    Given the cursor is at position (9, 18)
    When I press "j"
    Then the cursor should remain at position (9, 18)

  # ─────────────────────────────────────────────────────────────────────
  # Tenuki (Strategic Jump)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Jump to strategic point with 't' (Tenuki)
    Given the cursor is at position (9, 9)
    When I press "t"
    Then the cursor should move to a strategic point
    And the status bar should indicate "tenuki"

  # ─────────────────────────────────────────────────────────────────────
  # Position Information
  # ─────────────────────────────────────────────────────────────────────

  Scenario: View position information via command
    Given the cursor is at position (3, 3)
    When I enter command "/info"
    Then the content panel should show position coordinates
    And the content panel should show semantic context for (3, 3)

  # ─────────────────────────────────────────────────────────────────────
  # Mini-Grid Synchronization
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Mini-grids update on cursor movement
    Given the cursor is at position (9, 9)
    When I press "l"
    Then the "Topo" mini-grid should update its view
    And the "Embed" mini-grid should update its view
    And the "Iso" mini-grid should update its view

  Scenario: Mini-grids show orthographic projections
    Given the cursor is at position (9, 9)
    Then the "Topo" mini-grid should show the topology projection
    And the "Embed" mini-grid should show the embedding projection
    And the "Iso" mini-grid should show the isometric projection
