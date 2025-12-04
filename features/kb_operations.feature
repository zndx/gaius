Feature: Knowledge Base Operations
  As a researcher using Gaius
  I want to create and navigate notes in the knowledge base
  So I can build and explore my knowledge graph

  Background:
    Given the Gaius TUI is running
    And the KB root is configured

  # ─────────────────────────────────────────────────────────────────────
  # FileTree Structure
  # ─────────────────────────────────────────────────────────────────────

  Scenario: FileTree shows KB structure on startup
    Then the FileTree should show "Agents/" as a top-level node
    And the FileTree should show "KB/" as a top-level node
    And the FileTree should not show "/" as a visible root

  Scenario: Agents directory lists available agents
    When I expand the "Agents/" node in FileTree
    Then I should see agent entries like "leader", "risk", "critic"
    And each agent should show as a navigable item

  Scenario: KB directory shows current and scratch
    When I expand the "KB/" node in FileTree
    Then I should see "current/" subdirectory
    And I should see "scratch/" subdirectory

  Scenario: Scratch directory shows date-based organization
    When I expand the "KB/scratch/" node in FileTree
    Then I should see date-based directories (YYYY-MM-DD format)

  # ─────────────────────────────────────────────────────────────────────
  # FileTree Navigation
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Select file in FileTree shows content
    Given a KB note exists at "current/topics/example.md"
    When I select "example.md" in the FileTree
    Then the content panel should show the file content
    And the file path should appear in the panel header

  Scenario: Navigate FileTree with keyboard
    Given focus is on the FileTree
    When I press "j" or down arrow
    Then the next item should be highlighted
    When I press "Enter"
    Then the item should be selected/expanded

  # ─────────────────────────────────────────────────────────────────────
  # Note Creation (Ctrl+N)
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Create new scratch note with Ctrl+N
    When I press "ctrl+n"
    Then a new markdown file should be created in today's scratch directory
    And the note editor should appear
    And the editor should be in insert mode
    And the filename should follow the pattern "HHMMss_*.md" (time-prefixed)

  Scenario: Note editor supports markdown editing
    Given the note editor is open
    When I type markdown content
    Then the content should be saved
    And wiki-links should be recognized

  # ─────────────────────────────────────────────────────────────────────
  # Wiki-Links and Graph
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Wiki-links appear in graph panel
    Given a KB note exists with content "See [[related-concept]] for more"
    When I select this note in FileTree
    And the graph panel is visible
    Then "related-concept" should appear as a forward link node
    And an edge should connect the current note to "related-concept"

  Scenario: Backlinks appear in graph
    Given note A links to note B via [[B]]
    When I select note B in FileTree
    And the graph panel is visible
    Then note A should appear as a backlink node

  Scenario: Graph navigation updates content preview
    Given the graph panel is visible with multiple nodes
    When I navigate to a linked node in the graph
    Then the content panel should preview that node's content

  Scenario: Graph refreshes when panel is shown
    Given the graph panel is hidden
    And KB content has changed
    When I press "g" to show the graph panel
    Then the graph should refresh with current data

  # ─────────────────────────────────────────────────────────────────────
  # KB Search
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Search KB with '/search'
    Given KB notes exist containing "distributed consensus"
    When I enter command "/search distributed consensus"
    Then the content panel should show search results
    And results should include notes mentioning "distributed consensus"
    And results should show relevance scores

  Scenario: Semantic search finds related content
    Given KB notes exist about "Raft consensus algorithm"
    When I enter command "/search distributed agreement"
    Then results should include Raft-related notes
    And semantic similarity should influence ranking

  Scenario: Empty search shows recent files
    When I enter command "/search"
    Then the content panel should show recently modified KB files

  # ─────────────────────────────────────────────────────────────────────
  # KB Directories
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Current directory for active topics
    Then the "KB/current/" directory should contain:
      | Subdirectory | Purpose                    |
      | topics/      | Subject-matter notes       |
      | projects/    | Active project notes       |
      | content/     | Domain-specific content    |

  Scenario: Scratch directory for daily notes
    Then the "KB/scratch/" directory should contain:
      | Pattern      | Purpose                    |
      | YYYY-MM-DD/  | Date-organized scratchpad  |

  Scenario: Archive for quarterly organization
    Then the "KB/archive/" directory structure should support:
      | Pattern      | Purpose                    |
      | YYYYQN/      | Quarterly archives         |

  # ─────────────────────────────────────────────────────────────────────
  # Zettelkasten Features
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Notes support frontmatter
    Given I create a new note
    Then the note should support YAML frontmatter
    And frontmatter can include tags, date, and links

  Scenario: Note filenames follow time-prefix convention
    When I create a note in scratch directory
    Then the filename should be time-prefixed: "HHMMss_topic.md"
    And the format should be "YYYY-MM-DD/HHMMss_description.md"
    And filenames should sort chronologically within each day
