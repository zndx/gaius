@nifi @curriculum @level0
Feature: NiFi Basic Operations (Level 0)
  As a MetaAgent in training
  I need to learn basic NiFi operations
  So I can perform more complex flow operations later

  Background:
    Given a NiFi instance is running at "http://localhost:8080/nifi"
    And I have authenticated with NiFi

  @create_processor
  Scenario: Create a single processor
    Given I am viewing the root process group
    When I add a "GenerateFlowFile" processor to the canvas
    Then the processor "GenerateFlowFile" should exist in the root group
    And the processor should be in STOPPED state

  @configure_processor
  Scenario: Configure processor properties
    Given I have a "GenerateFlowFile" processor named "Generate Test Data"
    When I configure the processor with:
      | Property       | Value        |
      | File Size      | 1 KB         |
      | Batch Size     | 10           |
    Then the processor "Generate Test Data" should have property "File Size" = "1 KB"

  @connect_processors
  Scenario: Connect two processors
    Given I have processors:
      | Name      | Type              |
      | GetFile   | GetFile           |
      | LogMessage| LogMessage        |
    When I connect "GetFile" to "LogMessage" with relationship "success"
    Then a connection should exist from "GetFile" to "LogMessage"

  @start_stop_processor
  Scenario: Start and stop a processor
    Given I have a running "GenerateFlowFile" processor
    When I stop the processor "GenerateFlowFile"
    Then the processor should be in STOPPED state
    When I start the processor "GenerateFlowFile"
    Then the processor should be in RUNNING state
