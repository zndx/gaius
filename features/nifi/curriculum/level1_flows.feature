@nifi @curriculum @level1
Feature: NiFi Flow Construction (Level 1)
  As a MetaAgent progressing in training
  I need to build complete data flows
  So I can orchestrate data movement pipelines

  Background:
    Given a NiFi instance is running at "http://localhost:8080/nifi"
    And I have authenticated with NiFi
    And the root process group is empty

  @simple_flow
  Scenario: Create a simple file transfer flow
    When I create a flow with:
      | Source        | Destination   | Relationship |
      | GetFile       | PutFile       | success      |
    And I configure "GetFile" with:
      | Property          | Value           |
      | Input Directory   | /input          |
    And I configure "PutFile" with:
      | Property            | Value         |
      | Directory           | /output       |
    Then the flow should be valid
    And all processors should show no validation errors

  @process_group
  Scenario: Create and use a process group
    When I create a process group named "Data Ingestion"
    And I add to "Data Ingestion":
      | Processor         |
      | GenerateFlowFile  |
      | UpdateAttribute   |
    And I connect them sequentially
    Then the process group "Data Ingestion" should contain 2 processors

  @funnel_merge
  Scenario: Merge multiple sources with funnel
    Given I have processors:
      | Name         | Type              |
      | Source1      | GenerateFlowFile  |
      | Source2      | GenerateFlowFile  |
      | LogOutput    | LogMessage        |
    When I create a funnel
    And I connect "Source1" to the funnel
    And I connect "Source2" to the funnel
    And I connect the funnel to "LogOutput"
    Then data from both sources should flow to "LogOutput"
