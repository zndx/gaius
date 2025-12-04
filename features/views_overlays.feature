Feature: View Modes and Overlays
  As a Gaius user
  I want to switch between different visualization modes
  So I can analyze data from multiple perspectives

  Background:
    Given the Gaius TUI is running

  # ─────────────────────────────────────────────────────────────────────
  # View Mode Cycling (v)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Cycle view modes with 'v'
    Given the view mode is "go"
    When I press "v"
    Then the view mode should be "pension"
    And the status bar should show "PENSION"

  Scenario: View mode cycle order
    Given the view mode is "go"
    When I press "v" 3 times
    Then the view mode should cycle through "pension" → "swarm" → "go"

  # ─────────────────────────────────────────────────────────────────────
  # Go View Mode
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Go view shows board-style visualization
    Given the view mode is "go"
    Then the main grid should display a Go board aesthetic
    And stones should be shown at populated positions
    And the grid should use 19x19 intersections

  # ─────────────────────────────────────────────────────────────────────
  # Pension View Mode
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Pension view shows allocation data
    Given the view mode is "pension"
    And pension allocation data is loaded
    Then the grid should show allocation heatmap
    And positions should reflect asset distribution

  # ─────────────────────────────────────────────────────────────────────
  # Swarm View Mode
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Swarm view shows agent positions
    Given the view mode is "swarm"
    And a swarm analysis has been run
    Then the grid should show agent positions
    And each agent should have a distinct marker

  # ─────────────────────────────────────────────────────────────────────
  # Overlay Mode Cycling (o)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Cycle overlay modes with 'o'
    Given the overlay mode is "none"
    When I press "o"
    Then the overlay mode should be "topology"
    And the status bar should show overlay indicator

  Scenario: Overlay mode cycle order
    Given the overlay mode is "none"
    When I press "o" 4 times
    Then the overlay mode should cycle through "topology" → "geometry" → "dynamics" → "agents"

  Scenario: Return to no overlay
    Given the overlay mode is "agents"
    When I press "o"
    Then the overlay mode should be "none"

  # ─────────────────────────────────────────────────────────────────────
  # Topology Overlay (H0/H1/H2)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Topology overlay shows persistent homology features
    Given the overlay mode is "topology"
    Then H0 (connected components) should be visualized
    And H1 (loops/cycles) should be highlighted
    And H2 (voids) should be indicated

  Scenario: Topology overlay updates with TDA computation
    Given the overlay mode is "topology"
    When TDA features are recomputed
    Then the topology overlay should refresh

  # ─────────────────────────────────────────────────────────────────────
  # Geometry Overlay (Curvature)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Geometry overlay shows curvature heatmap
    Given the overlay mode is "geometry"
    Then high-curvature regions should be highlighted
    And semantic boundaries should be visible
    And flat regions should have minimal highlighting

  # ─────────────────────────────────────────────────────────────────────
  # Dynamics Overlay (Gradient Field)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Dynamics overlay shows gradient vectors
    Given the overlay mode is "dynamics"
    Then gradient direction should be indicated
    And semantic change direction should be visible

  # ─────────────────────────────────────────────────────────────────────
  # Agents Overlay
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Agents overlay shows swarm agent positions
    Given the overlay mode is "agents"
    And a swarm analysis has been run
    Then agent positions should be shown as markers
    And each agent should have a role indicator

  # ─────────────────────────────────────────────────────────────────────
  # Candidate Markers (c)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Toggle candidate markers with 'c'
    Given candidate positions have been calculated
    When I press "c"
    Then candidate markers should be visible on the grid

  Scenario: Hide candidate markers with 'c'
    Given candidate markers are visible
    When I press "c"
    Then candidate markers should be hidden

  # ─────────────────────────────────────────────────────────────────────
  # View/Overlay Independence
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Overlays work with any view mode
    Given the view mode is "pension"
    When I press "o" to activate "topology" overlay
    Then the topology overlay should display over the pension view

  Scenario: View change preserves overlay
    Given the overlay mode is "geometry"
    When I press "v" to change view mode
    Then the overlay mode should still be "geometry"

  # ─────────────────────────────────────────────────────────────────────
  # Status Bar Display
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Status bar shows current view mode
    Given the view mode is "swarm"
    Then the status bar should display "SWARM"

  Scenario: Status bar shows overlay when active
    Given the overlay mode is "topology"
    Then the status bar should indicate active overlay
