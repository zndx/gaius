Feature: Panel System
  As a Gaius user
  I want to control panel visibility and modes
  So I can optimize my workspace for different tasks

  Background:
    Given the Gaius TUI is running

  # ─────────────────────────────────────────────────────────────────────
  # Side Panel Toggle ([ ] \)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Toggle left panel with '['
    Given the left panel is visible
    When I press "["
    Then the left panel should be hidden
    And the main grid should expand to fill the space

  Scenario: Show left panel with '[' when hidden
    Given the left panel is hidden
    When I press "["
    Then the left panel should be visible
    And the FileTree should be displayed

  Scenario: Toggle right panel with ']'
    Given the right panel is visible
    When I press "]"
    Then the right panel should be hidden
    And the main grid should expand to fill the space

  Scenario: Show right panel with ']' when hidden
    Given the right panel is hidden
    When I press "]"
    Then the right panel should be visible
    And the content panel should be displayed

  Scenario: Toggle both panels with '\'
    Given the left panel is visible
    And the right panel is visible
    When I press "\"
    Then the left panel should be hidden
    And the right panel should be hidden
    And the main grid should be maximized

  Scenario: Restore both panels with '\' when hidden
    Given the left panel is hidden
    And the right panel is hidden
    When I press "\"
    Then the left panel should be visible
    And the right panel should be visible

  # ─────────────────────────────────────────────────────────────────────
  # Center Panel Cycling (g)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Cycle center panel with 'g' - Graph to Think
    Given the center panel mode is "graph"
    When I press "g"
    Then the center panel mode should be "think"
    And the Graph panel should be hidden
    And the Think panel should be visible
    And the status bar should show "THINK"

  Scenario: Cycle center panel with 'g' - Think to Evolution
    Given the center panel mode is "think"
    When I press "g"
    Then the center panel mode should be "evolution"
    And the Think panel should be hidden
    And the Evolution panel should be visible
    And the status bar should show "EVOLUTION"

  Scenario: Cycle center panel with 'g' - Evolution to None
    Given the center panel mode is "evolution"
    When I press "g"
    Then the center panel mode should be "none"
    And the Evolution panel should be hidden
    And no center panel should be visible
    And the status bar should show "NONE"

  Scenario: Cycle center panel with 'g' - None to Graph
    Given the center panel mode is "none"
    When I press "g"
    Then the center panel mode should be "graph"
    And the Graph panel should be visible
    And the status bar should show "GRAPH"

  # ─────────────────────────────────────────────────────────────────────
  # Direct Evolution Panel Access (e)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Jump directly to Evolution panel with 'e'
    Given the center panel mode is "graph"
    When I press "e"
    Then the center panel mode should be "evolution"
    And the Evolution panel should be visible
    And the Graph panel should be hidden

  Scenario: Evolution panel shows daemon status
    Given the center panel mode is "evolution"
    Then the Evolution panel should show daemon running status
    And the Evolution panel should show cycle count
    And the Evolution panel should show improvement percentage

  # ─────────────────────────────────────────────────────────────────────
  # Panel Initial State
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Panels start in correct initial state
    When the TUI first loads
    Then the left panel should be visible
    And the right panel should be visible
    And all center panels (Graph, Think, Evolution) should be hidden
    And the center panel mode should be "none" or first visible mode

  # ─────────────────────────────────────────────────────────────────────
  # Panel Content Updates
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Graph panel refreshes when shown
    Given the center panel mode is "think"
    When I press "g" to cycle to "none"
    And I press "g" again to cycle to "graph"
    Then the Graph panel should refresh its wiki-link data

  Scenario: Think panel shows reasoning traces
    Given the center panel mode is "think"
    Then the Think panel should show recent reasoning traces
    And traces should include operation type and summary

  Scenario: Evolution panel shows recent cycles
    Given the center panel mode is "evolution"
    Then the Evolution panel should show recent evolution cycles
    And each cycle should show agent, success/failure, and improvement
