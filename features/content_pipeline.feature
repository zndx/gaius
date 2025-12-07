@content-pipeline @db-required
Feature: Content Pipeline with QwQ Reasoning Integration
  As a Gaius system operator
  I want the full content pipeline to process feeds through QwQ reasoning
  So that I get high-quality, summarized KB entries with agent evolution

  Background:
    Given a clean pipeline test environment
    And the database is initialized with test schema
    And the KB root is configured for isolation

  # ==========================================================================
  # Stage 1: Content Fetching (@tier-1)
  # Requirements: DB only (real external sources)
  # Tests: Feed source management, fetch job scheduling
  # ==========================================================================

  @tier-1 @content-fetch
  Scenario: Configure and verify feed sources
    Given feed sources are configured in the database
      | name       | source_type | url                                |
      | arxiv-ai   | arxiv       | https://arxiv.org/list/cs.AI/new   |
      | arxiv-lg   | arxiv       | https://arxiv.org/list/cs.LG/new   |
    Then the feed sources should be queryable from the database
    And each source should have "enabled" status

  @tier-1 @job-scheduling
  Scenario: Schedule fetch jobs for configured sources
    Given feed sources are configured in the database
      | name       | source_type | url                                |
      | arxiv-ai   | arxiv       | https://arxiv.org/list/cs.AI/new   |
    When I schedule fetch jobs for enabled sources
    Then fetch jobs should be created with "pending" status
    And fetch job should be linked to source via source_id

  # ==========================================================================
  # Stage 3: Content Triage - Heuristic (@tier-2)
  # Requirements: DB + KB
  # ==========================================================================

  @tier-2 @content-triage @heuristic
  Scenario: Heuristic pre-filtering of content
    Given unprocessed content items exist in Iceberg
    When I run heuristic triage
    Then items should be scored on
      | criterion         | weight |
      | content_length    | 0.3    |
      | title_quality     | 0.2    |
      | metadata_complete | 0.3    |
      | source_reputation | 0.2    |
    And low-scoring items should be flagged for exclusion
    And lineage should record heuristic_score origin

  # ==========================================================================
  # Stage 3: Content Triage - LLM (@tier-3)
  # Requirements: DB + KB + Inference
  # ==========================================================================

  @tier-3 @content-triage @inference-required
  Scenario: LLM quality assessment with lineage
    Given heuristic-scored content items exist
    When I run LLM triage using fast model
    Then each item should receive llm_quality_score
    And lineage should link content_item to triage_assessment
    And combined score should weight heuristic plus LLM
    And duplicates should be marked summary_excluded

  # ==========================================================================
  # Stage 4: KB Creation (@tier-2)
  # Requirements: DB + KB
  # ==========================================================================

  @tier-2 @kb-creation @isolated-kb
  Scenario: Process content to KB markdown
    Given triaged content items with quality_score >= 50
    When I run the content processor
    Then markdown files should be created in KB
    And files should have YAML frontmatter with
      | field       |
      | title       |
      | source      |
      | fetched_at  |
      | quality     |
    And files should have content sections

  # ==========================================================================
  # Stage 5: QwQ Reasoning - GPU Allocation (@tier-4)
  # Requirements: Full pipeline
  # Note: QwQ-32B requires 4 GPUs (tensor-parallel=4) to avoid OOM
  # ==========================================================================

  @tier-4 @llm-reflection @qwq @gpu-allocation
  Scenario: GPU allocation for QwQ-32B reasoning model
    Given a clean pipeline test environment
    And the database is initialized with test schema
    And the KB root is configured for isolation
    When I request QwQ reasoning model via orchestrator
    Then orchestrator should allocate 4 GPUs for reasoning endpoint
    And vLLM should start with tensor-parallel=4
    And endpoint should become healthy within 180 seconds

  @tier-4 @llm-reflection @qwq
  Scenario: Deep reflection on KB content using QwQ
    Given a clean pipeline test environment
    And the database is initialized with test schema
    And the KB root is configured for isolation
    Given the reasoning endpoint is healthy
    And KB content exists from pipeline stages
    When I trigger cognition with depth "deep"
    Then QwQ should analyze accumulated KB content
    And thoughts should be generated with types
      | thought_type     |
      | PATTERN          |
      | CONNECTION       |
      | SYNTHESIS        |
      | SELF_OBSERVATION |
      | OBSERVATION      |
    And a thoughts note should be created in scratch/
    And lineage should link kb_entries to cognition to thoughts

  # ==========================================================================
  # Stage 6: Swarm Evolution (@tier-5)
  # Requirements: Full pipeline + Evolution
  # ==========================================================================

  @tier-5 @swarm-evolution
  Scenario: Collect training examples and evolve agents
    Given KB content and reflection thoughts exist
    When I trigger evolution for "leader" with strategy "gepa"
    Then training examples should be collected from KB
    And agent version should be created
    And performance metrics should be recorded

  @tier-5 @swarm-evolution @restore
  Scenario: Restore normal operations after evolution
    Given evolution has completed for an agent
    When I restore normal GPU operations
    Then optillm workers should scale back to 4
    And reserved GPUs should be released
    And fast model endpoint should be healthy

  # ==========================================================================
  # Full E2E Pipeline (@tier-4)
  # ==========================================================================

  @tier-4 @pipeline-e2e @qwq
  Scenario: Complete content pipeline from fetch to reflection
    Given the orchestrator performs a clean start
    And feed sources are configured in the database
      | name       | source_type | url                                |
      | arxiv-ai   | arxiv       | https://arxiv.org/list/cs.AI/new   |
    When I execute the full pipeline sequence
      | stage              |
      | fetch              |
      | heuristic_triage   |
      | llm_triage         |
      | kb_creation        |
      | qwq_reflection     |
    Then all stages should complete successfully
    And metrics should show
      | metric            | condition |
      | content_fetched   | > 0       |
      | content_triaged   | > 0       |
      | kb_entries        | > 0       |
      | thoughts_created  | > 0       |

  @tier-5 @pipeline-e2e @full
  Scenario: Complete content pipeline including evolution
    Given the orchestrator performs a clean start
    And feed sources are configured in the database
      | name       | source_type | url                                |
      | arxiv-ai   | arxiv       | https://arxiv.org/list/cs.AI/new   |
    When I execute the full pipeline sequence
      | stage              |
      | fetch              |
      | heuristic_triage   |
      | llm_triage         |
      | kb_creation        |
      | qwq_reflection     |
      | evolution          |
    Then all stages should complete successfully
    And metrics should show
      | metric            | condition |
      | content_fetched   | > 0       |
      | content_triaged   | > 0       |
      | kb_entries        | > 0       |
      | thoughts_created  | > 0       |
      | agents_evolved    | > 0       |
    And lineage should be complete from source to agent_version
