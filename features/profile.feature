Feature: Profile Configuration
  As a user with multiple research domains
  I want to switch between profiles
  So sources and settings match my current focus

  Background:
    Given the Gaius TUI is running

  Scenario: Load default profile on startup
    Then the active profile should be "default"

  Scenario: Switch profile via command
    When I enter command "/profile weathership"
    Then the active profile should be "weathership"

  Scenario: Profile affects available agents
    Given the active profile is "weathership"
    Then the enabled agents should include "Risk"
    And the enabled agents should include "Optimizer"

  Scenario: Profile loaded from HOCON config
    Given a profile config exists at "config/profiles/test.conf"
    When I enter command "/profile test"
    Then the profile should have settings from the HOCON file

  Scenario: Database profile overrides HOCON defaults
    Given a profile "custom" exists in the database
    And the database profile has custom feed_config
    When I enter command "/profile custom"
    Then the active profile should use database settings
