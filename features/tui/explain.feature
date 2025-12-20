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
    And the Think panel should show a trace with:
      | Field     | Value              |
      | Operation | explanation        |
      | Query     | grid interpretation|
      | Model     | local LLM          |

  Scenario: Explanation uses Go notation for position
    Given the cursor is at position (9, 9)
    When I enter command "/explain"
    Then the explanation header should show "K10"
    And the explanation should include coordinates "(9, 9)"

  # ─────────────────────────────────────────────────────────────────────
  # Explain with Position Arguments
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explain specific position via Go notation
    When I enter command "/explain K10"
    Then an explanation should be generated for position (9, 9)
    And the cursor position should not change

  Scenario: Explain corner position
    When I enter command "/explain A19"
    Then an explanation should be generated for position (0, 0)
    And boundary effects should be noted in geometric interpretation

  Scenario: Explain lower-right corner
    When I enter command "/explain T1"
    Then an explanation should be generated for position (18, 18)

  Scenario: Invalid position notation falls back to cursor
    Given the cursor is at position (5, 5)
    When I enter command "/explain ZZ99"
    Then an explanation should be generated for the cursor position
    And no error should be displayed

  # ─────────────────────────────────────────────────────────────────────
  # Explanation Content - Position Context
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation includes document at position
    Given a KB document exists at cursor position
    When I enter command "/explain"
    Then the explanation should include:
      | Field    | Description                    |
      | Position | Go notation and coordinates    |
      | Document | Title of document at cell      |
      | View     | Current view mode              |
      | Overlay  | Current overlay mode           |

  Scenario: Explanation handles empty cell
    Given no document exists at cursor position
    When I enter command "/explain"
    Then the document field should show "Empty cell"

  # ─────────────────────────────────────────────────────────────────────
  # Explanation Content - Differential Geometry
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation includes Ricci curvature
    Given curvature data is available
    When I enter command "/explain"
    Then the explanation should include "Ricci curvature κ" value
    And curvature interpretation should indicate:
      | Value Range | Interpretation   |
      | κ < -0.3    | STRONG BOUNDARY  |
      | -0.3 ≤ κ < 0| boundary         |
      | κ = 0       | flat             |
      | 0 < κ ≤ 0.3 | interior         |
      | κ > 0.3     | STRONG INTERIOR  |

  Scenario: Explanation includes gradient magnitude
    Given gradient field is available
    When I enter command "/explain"
    Then the explanation should include gradient magnitude
    And the gradient should indicate semantic flow direction

  Scenario: Explanation includes divergence
    Given divergence map is available
    When I enter command "/explain"
    Then the explanation should include divergence value

  # ─────────────────────────────────────────────────────────────────────
  # Explanation Content - Topological Features
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation includes TDA features
    Given TDA features have been computed
    When I enter command "/explain"
    Then the saved note should include topological context:
      | Feature | Description                  |
      | H0      | Connected semantic components|
      | H1      | Knowledge cycles             |
      | H2      | Missing knowledge (voids)    |
      | Entropy | Complexity measure           |

  Scenario: Explanation includes risk score
    Given a document exists at cursor position
    And TDA features include risk scores
    When I enter command "/explain"
    Then the explanation should include risk score with interpretation:
      | Value Range | Interpretation |
      | > 0.7       | critical       |
      | 0.4 - 0.7   | bridge point   |
      | < 0.4       | stable         |

  # ─────────────────────────────────────────────────────────────────────
  # Explanation Content - Nearby Documents
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation includes nearby documents
    Given documents exist in 3x3 neighborhood around cursor
    When I enter command "/explain"
    Then the saved note should list up to 8 nearby documents
    And the list should exclude the center document

  # ─────────────────────────────────────────────────────────────────────
  # Explanation Content - Mini-Grid Visuals
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation includes embed view visualization
    When I enter command "/explain"
    Then the saved note should include "Embed View (Similarity)"
    And the embed grid should be rendered as Unicode blocks
    And the description should mention "Cosine similarity"

  Scenario: Explanation includes iso view visualization
    When I enter command "/explain"
    Then the saved note should include "Iso View (Curvature)"
    And the iso grid should be rendered as Unicode blocks
    And the description should mention "Ricci curvature elevation"

  Scenario: Mini-grid uses Unicode block characters
    When I enter command "/explain"
    Then mini-grids should use intensity characters:
      | Value Range | Character |
      | > 0.8       | █         |
      | 0.6 - 0.8   | ▓         |
      | 0.4 - 0.6   | ▒         |
      | 0.2 - 0.4   | ░         |
      | 0.05 - 0.2  | ·         |
      | < 0.05      | (space)   |

  # ─────────────────────────────────────────────────────────────────────
  # KB Persistence
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation saves to KB by default
    When I enter command "/explain"
    Then a zettelkasten note should be created
    And the note should be saved in today's scratch directory
    And the filename should follow "HHMMSS_explain_<position>.md" pattern
    And the full path should be "scratch/YYYY-MM-DD/HHMMSS_explain_K10.md"

  Scenario: Explanation includes YAML frontmatter
    When I enter command "/explain"
    Then the saved note should have YAML frontmatter with:
      | Field         | Example Value     |
      | created       | ISO timestamp     |
      | type          | explain           |
      | position      | K10               |
      | coordinates   | [9, 9]            |
      | curvature     | numeric value     |
      | gradient      | [x, y] pair       |
      | h0_count      | integer           |
      | h1_count      | integer           |
      | h2_count      | integer           |
      | tda_entropy   | float             |
      | grid_coverage | percentage        |
      | total_documents| integer          |
      | view_mode     | current mode      |
      | overlay_mode  | current overlay   |
      | model         | local LLM         |
      | elapsed_ms    | generation time   |

  Scenario: Disable KB save with --no-save flag
    When I enter command "/explain --no-save"
    Then an explanation should be generated
    And no zettelkasten note should be created
    And the explanation should only appear in content panel

  Scenario: Explanation shows save path confirmation
    When I enter command "/explain"
    Then the content panel should show "Saved to:" with file path
    And the path should be relative to scratch directory

  # ─────────────────────────────────────────────────────────────────────
  # Note Editor Integration
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explanation opens in note editor
    When I enter command "/explain"
    Then the note editor should become visible
    And the note editor should open the saved explanation file
    And the note editor should start in normal mode
    And the file tree should refresh to show the new note

  Scenario: Note editor allows editing explanation
    Given an explanation has been generated
    When the note editor is visible
    Then I can press "i" to enter insert mode
    And I can edit the explanation content
    And changes are auto-saved

  Scenario: Close note editor returns focus to grid
    Given an explanation is open in the note editor
    When I enter ":q" in the note editor
    Then the note editor should close
    And focus should return to the main grid

  # ─────────────────────────────────────────────────────────────────────
  # Content Panel Display
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Content panel shows explanation summary
    When I enter command "/explain"
    Then the content panel should show:
      | Section              | Content                     |
      | Header               | Grid Explanation: <position>|
      | Position             | Go notation and coordinates |
      | Document             | Title or "Empty cell"       |
      | View/Overlay         | Current modes               |
      | Differential Geometry| Curvature, gradient values  |
      | LLM Interpretation   | Generated explanation       |
      | Save confirmation    | Path to saved file          |

  # ─────────────────────────────────────────────────────────────────────
  # Think Panel Integration
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Explain operation appears in Think panel trace
    When I enter command "/explain"
    Then the Think panel should show an active trace during generation
    And on completion the trace should show:
      | Field      | Value                        |
      | Operation  | explanation                  |
      | Query      | grid interpretation          |
      | Duration   | generation time in ms        |
      | Summary    | "Generated explanation in Xms"|

  # ─────────────────────────────────────────────────────────────────────
  # Error Handling
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Error when grid data unavailable
    Given grid projection has failed
    When I enter command "/explain"
    Then the content panel should show "Failed to get grid data"

  Scenario: Error when inference endpoint unavailable
    Given no inference endpoints are running
    When I enter command "/explain"
    Then the content panel should show "Explanation failed"
    And the error should suggest "Make sure optillm/vLLM is running"
    And the Think panel trace should be cleared

  Scenario: LLM thinking tags are stripped
    Given the LLM response contains <think>...</think> tags
    When I enter command "/explain"
    Then the displayed explanation should not include thinking tags
    And only the final explanation text should be shown

  # ─────────────────────────────────────────────────────────────────────
  # Coordinate System
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Go notation conversion is correct
    Then Go notation should map correctly:
      | Go Notation | Grid X | Grid Y |
      | A19         | 0      | 0      |
      | A1          | 0      | 18     |
      | T19         | 18     | 0      |
      | T1          | 18     | 18     |
      | K10         | 9      | 9      |
      | J10         | 8      | 9      |

  Scenario: Column I is skipped in Go notation
    Then column "I" should not exist in Go notation
    And column "J" should map to grid X=8
    And column "H" should map to grid X=7
