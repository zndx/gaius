Feature: Knowledge Base Operations
  As a researcher using Gaius
  I want to create and navigate notes in the knowledge base
  So I can build and explore my knowledge graph

  Background:
    Given the Gaius TUI is running

  Scenario: FileTree shows KB structure without root node
    Then the FileTree should show "Agents/" as a top-level node
    And the FileTree should show "KB/" as a top-level node
    And the FileTree should not show "/" as a visible node

  Scenario: Navigate to KB scratch directory
    When I expand the "KB/" node in FileTree
    And I expand the "scratch/" node in FileTree
    Then I should see date-based directories

  Scenario: Create new scratch note
    When I press "ctrl+n"
    Then a new markdown file should be created in scratch
    And the note editor should be visible
    And the note editor should be in insert mode

  Scenario: View file content from FileTree
    Given a KB note exists at "current/topics/test.md"
    When I select "test.md" in the FileTree
    Then the content panel should show the file content

  Scenario: Wiki-link appears in graph
    Given a KB note exists with content "See [[related-concept]] for more"
    When I view the graph for this note
    Then "related-concept" should appear as a forward link node

  Scenario: Graph selection updates content preview
    Given multiple KB notes exist with wiki-links
    When I navigate to a node in the graph view
    Then the content panel should preview that node's content

  Scenario: Search KB with slash command
    Given KB notes exist containing "distributed consensus"
    When I enter command "/search distributed consensus"
    Then the content panel should show search results
    And results should include notes mentioning "distributed consensus"
