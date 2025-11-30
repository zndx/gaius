Feature: Grid Navigation
  As a Gaius user
  I want to navigate the 19x19 grid using vim-style keys
  So I can explore data spatially

  Background:
    Given the Gaius TUI is running

  Scenario: Vim-style cursor movement right
    Given the cursor is at position (9, 9)
    When I press "l" 3 times
    Then the cursor should be at position (12, 9)

  Scenario: Vim-style cursor movement left
    Given the cursor is at position (9, 9)
    When I press "h" 2 times
    Then the cursor should be at position (7, 9)

  Scenario: Vim-style cursor movement down
    Given the cursor is at position (9, 9)
    When I press "j" 4 times
    Then the cursor should be at position (9, 13)

  Scenario: Vim-style cursor movement up
    Given the cursor is at position (9, 9)
    When I press "k" 5 times
    Then the cursor should be at position (9, 4)

  Scenario: Cursor stays within grid bounds
    Given the cursor is at position (0, 0)
    When I press "h" 1 times
    Then the cursor should be at position (0, 0)

  Scenario: Toggle left panel
    Given the left panel is visible
    When I press "["
    Then the left panel should be hidden

  Scenario: Toggle right panel
    Given the right panel is visible
    When I press "]"
    Then the right panel should be hidden

  Scenario: Toggle both panels
    Given the left panel is visible
    And the right panel is visible
    When I press "\\"
    Then the left panel should be hidden
    And the right panel should be hidden

  Scenario: Cycle view modes
    Given the view mode is "go"
    When I press "v"
    Then the view mode should be "pension"
    When I press "v"
    Then the view mode should be "swarm"
    When I press "v"
    Then the view mode should be "go"

  Scenario: Cycle overlay modes
    Given the overlay mode is "none"
    When I press "o"
    Then the overlay mode should be "risk"

  Scenario: Toggle graph panel
    Given the graph panel is hidden
    When I press "g"
    Then the graph panel should be visible

  Scenario: Enter command mode
    When I press "/"
    Then command input should be focused
