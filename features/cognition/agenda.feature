Feature: Cognition manages the forward agenda
  As an operator of Gaius
  I want Cognition to write Briefs, Lists, and Sessions onto /agenda
  So I read a memo, tick shared suggestions, and catch up with the agent
  using headlines in the calendar description

  Background:
    Given Cognition synthesis writes agenda_entries with kinds brief, reminder, and session
    And each kind has a rolling-week target density
    And Aperture admitted windows are the only slices handed to Thinking by default

  @cognition @agenda @session
  Scenario: Sessions a few times a week with a Terminal paste block
    Given fewer than 3 open sessions in the next 7 days
    When Cognition curates the agenda from Aperture-admitted world events
    Then it schedules at most 3 sessions in that week
    And each session is a catch-up with a colleague
    And the calendar description lists discussion headlines
    And the description includes a BEGIN SESSION / END SESSION block to paste into the Terminal

  @cognition @agenda @reminder
  Scenario: Reminders are short follow-up lists
    Given open reminders under the density cap
    When Cognition emits a reminder
    Then the body is a short shared suggestion list of at most 5 checkbox items
    And items are helpful to operators and to other agents

  @cognition @agenda @brief
  Scenario: Regular executive briefs report cause without packing guru codes
    Given briefs under the weekly density cap
    When Cognition emits a briefing
    Then the body is a letter or memo in natural-register prose
    And the audience is a sophisticated expert-technical executive
    And operational facts are stated accurately without a commit log or wiki dump
    And guru meditation codes are not packed into the brief body
    And Thinking may SEARCH_GURU unique codes in the codebase to inform RCA
    And the brief is not a toy coding problem
