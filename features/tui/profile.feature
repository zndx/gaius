Feature: Profile Configuration
  As a user with multiple research domains
  I want to switch between profiles
  So sources and settings match my current focus

  Background:
    Given the Gaius TUI is running

  # ─────────────────────────────────────────────────────────────────────
  # Default Profile
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Load default profile on startup
    When the TUI first loads
    Then the active profile should be "default"
    And default profile settings should be applied

  Scenario: Default profile from environment
    Given GAIUS_PROFILE is set to "cloudera"
    When the TUI loads
    Then the active profile should be "cloudera"

  # ─────────────────────────────────────────────────────────────────────
  # Profile Switching
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Switch profile via command
    When I enter command "/profile weathership"
    Then the active profile should be "weathership"
    And the status bar should reflect the new profile

  Scenario: Profile affects configuration
    Given the active profile is "cloudera"
    Then profile-specific KB paths should be used
    And profile-specific agents should be enabled

  # ─────────────────────────────────────────────────────────────────────
  # Profile Configuration Sources
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Profile loaded from HOCON config file
    Given a profile config exists at "config/profiles/test.conf"
    When I enter command "/profile test"
    Then settings should be loaded from the HOCON file
    And nested configuration should be supported

  Scenario: Profile configuration hierarchy
    Given a profile "custom" exists
    Then configuration should be merged in order:
      | Priority | Source                    |
      | 1 (high) | Environment variables     |
      | 2        | Profile-specific config   |
      | 3 (low)  | Base config (base.conf)   |

  # ─────────────────────────────────────────────────────────────────────
  # Profile-Specific Settings
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Profile affects available agents
    Given the active profile is "weathership"
    Then the enabled agents should include configured agents
    And agent configuration should reflect profile settings

  Scenario: Profile affects KB root
    Given the active profile is "cloudera"
    Then the KB root should match profile.kb.root setting

  Scenario: Profile affects inference settings
    Given the active profile has custom inference config
    Then inference backend should match profile.inference.backend
    And model selection should match profile settings

  # ─────────────────────────────────────────────────────────────────────
  # Available Profiles
  # ─────────────────────────────────────────────────────────────────────

  Scenario: List available profiles
    Then the following profiles should be available:
      | Profile      | Description                    |
      | default      | General-purpose configuration  |
      | cloudera     | Cloudera/Kudu focused          |
      | weathership  | Financial/pension analysis     |

  Scenario: Unknown profile shows error
    When I enter command "/profile nonexistent"
    Then an error should be displayed
    And the active profile should remain unchanged

  # ─────────────────────────────────────────────────────────────────────
  # Profile Persistence
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Profile change persists during session
    When I enter command "/profile cloudera"
    And I perform various operations
    Then the active profile should remain "cloudera"

  Scenario: Profile does not persist across sessions by default
    Given the active profile was "cloudera" in the previous session
    When I start a new TUI session
    Then the active profile should be the default
