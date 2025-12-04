Feature: Explain Grid Position
  As an expert Gaius user
  I want a narrative explanation about the TDA and UMAP projection
  So I can communicate the quantitative details behind the visualization

  Background:
    Given the Gaius TUI is running
    And KB embeddings have been projected to the grid

  # ─────────────────────────────────────────────────────────────────────
  # Basic Explain Command
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Execute explain command at cursor position
    Given the cursor is at position (9, 9)
    When I enter command "/explain"
    Then an explanation should be generated using local LLM
    And the explanation should describe:
      | Aspect              | Content                            |
      | Semantic position   | What concepts cluster here         |
      | Topological context | H0/H1/H2 features nearby           |
      | Grid coordinates    | Position in UMAP projection        |

  Scenario: Explanation saved as zettelkasten note
    When I enter command "/explain"
    Then a zettelkasten note should be created
    And the note should be saved in today's scratch directory
    And the filename should follow the "HHMMss_explain_*.md" pattern
    And the full path should be "scratch/YYYY-MM-DD/HHMMss_explain_x9y9.md"

  Scenario: Explanation opens in content panel
    When I enter command "/explain"
    Then the generated note should open in the content panel
    And the content should be scrollable

  # ─────────────────────────────────────────────────────────────────────
  # Explain with Coordinates
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explain specific coordinates
    When I enter command "/explain 3 15"
    Then an explanation should be generated for position (3, 15)
    And the cursor should not move

  Scenario: Explain corner positions
    When I enter command "/explain 0 0"
    Then an explanation should describe the top-left semantic region
    And boundary effects should be noted

  Scenario: Explain center position
    When I enter command "/explain 9 9"
    Then an explanation should describe the semantic center
    And the explanation should note central clustering

  # ─────────────────────────────────────────────────────────────────────
  # Explanation Content
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation includes differential geometry concepts
    When I enter command "/explain"
    Then the explanation should reference:
      | Concept           | Description                        |
      | UMAP projection   | How high-dim embeddings map to 2D  |
      | Semantic density  | How concepts cluster at position   |
      | Curvature         | Boundary vs interior regions       |
      | Gradient          | Direction of semantic change       |

  Scenario: Explanation includes topological features
    When I enter command "/explain"
    Then the explanation should describe nearby TDA features:
      | Feature | Interpretation                       |
      | H0      | Connected semantic components        |
      | H1      | Conceptual loops or cycles           |
      | H2      | Semantic voids or gaps               |

  Scenario: Explanation is accessible to non-experts
    When I enter command "/explain"
    Then the explanation should use clear, non-technical language
    And technical terms should be defined when first used
    And the explanation should be suitable for sharing with colleagues

  # ─────────────────────────────────────────────────────────────────────
  # Explain with Save Option
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation defaults to saving note
    When I enter command "/explain"
    Then a note should be saved to KB automatically

  Scenario: Note includes metadata frontmatter
    When I enter command "/explain 5 10"
    Then the saved note should include YAML frontmatter with:
      | Field       | Value                              |
      | position    | [5, 10]                            |
      | generated   | timestamp                          |
      | type        | explanation                        |

  # ─────────────────────────────────────────────────────────────────────
  # Error Handling
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Invalid coordinates show error
    When I enter command "/explain 20 5"
    Then the content panel should show "Invalid position"
    And the error should explain valid range is 0-18

  Scenario: Explain works when inference unavailable
    Given no inference endpoints are available
    When I enter command "/explain"
    Then a fallback explanation should be generated
    And the fallback should use cached TDA metrics

  # ─────────────────────────────────────────────────────────────────────
  # Integration with Other Features
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explain after TDA recomputation
    Given TDA features have been recomputed
    When I enter command "/explain"
    Then the explanation should reflect current TDA state
    And H0/H1/H2 counts should match /tda output

  Scenario: Explain references nearby KB content
    Given KB notes are projected to positions near (9, 9)
    When I enter command "/explain 9 9"
    Then the explanation should reference nearby notes
    And semantic clustering should be described
