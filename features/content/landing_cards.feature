Feature: Public landing card pages
  As a visitor of gaius.zndx.org
  I want a card click to open a summary page with a LuxCore image and local reasoning
  So the public surface proves Gaius is producing intelligent, visualized content
  without exposing internal knowledge-base paths

  Background:
    Given Gaius is publishing the featured collection to Cloudflare KV
    And card images are served from viz.gaius.zndx.org

  @landing @luxcore
  Scenario: Card click shows LuxCore visualization and local open-weights
    Given a published featured card with a public https source URL
    When a visitor opens the card page on gaius.zndx.org
    Then the page must display the LuxCore-rendered card image
    And the page must include an Open-Weights Reasoning summary panel
    And the source URL must not be an internal KB path

  @landing @summaries
  Scenario: Brave and Cerebras panels vary with API availability
    Given the local open-weights panel is present
    When Brave Summarizer is available within budget
    Then a Brave API summary panel is shown
    When the Cerebras API is available within budget
    Then a Cerebras Thinking summary panel is shown
    When Brave or Cerebras is unavailable or over budget
    Then that panel is omitted
    And the LuxCore image and Open-Weights panel remain

  @landing @gate
  Scenario: Unpublished cards missing required enrichment
    Given a pending featured card
    When it lacks a LuxCore image or a local open-weights summary
    Then publish_cards must not promote it to the landing page
    And the failure is #COL.00000016.NOENRICH
