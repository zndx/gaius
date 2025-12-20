@model-library @cli
Feature: Model Library KB Upkeep
  As a Gaius user
  I want to add models to the knowledge base with accurate feasibility assessment
  So that I can track which models can run locally and discover alternatives for those that cannot

  Background:
    Given fallbacks and workarounds are disabled
    And the gaius-engine is running with healthy endpoints
    And the KB root is configured with current/ and scratch/ directories
    And the Lambda Labs API is configured
    And the Cerebras API is configured

  # ==========================================================================
  # Hardware Detection and Baseline
  # ==========================================================================

  @tier-2 @hardware
  Scenario: Detect local GPU hardware configuration
    When I run "/model hardware" via CLI
    Then the response should include GPU information
      | field           | expected_pattern         |
      | gpu_count       | 6                        |
      | gpu_model       | NVIDIA GeForce RTX 4090  |
      | total_vram_gb   | 143.9                    |
      | per_gpu_vram_gb | 24.0                     |
    And the hardware info should be cached for subsequent operations

  # ==========================================================================
  # Feasible Model Addition (Can Run Locally)
  # ==========================================================================

  @tier-2 @model-add @feasible
  Scenario: Add a model that fits local hardware
    Given I have not previously added "mistralai/Mistral-7B-Instruct-v0.3"
    When I run "/model add mistralai/Mistral-7B-Instruct-v0.3" via CLI
    Then the model should be assessed as "feasible"
    And a KB entry should be created in "scratch/{date}/models/"
    And the KB entry should have frontmatter
      | field    | value                                |
      | type     | model-reference                      |
      | status   | feasible                             |
      | model_id | mistralai/Mistral-7B-Instruct-v0.3   |
    And the KB entry should include sections
      | section               | content_pattern                    |
      | Overview              | Parameters.*7B                     |
      | Hardware Requirements | VRAM Required.*~\d+GB              |
      | Feasibility           | ✅ Can run locally                 |
      | Local Hardware        | 6x NVIDIA GeForce RTX 4090         |

  @tier-2 @model-add @feasible @spec-generation
  Scenario: Generate ModelSpec for feasible model
    Given "mistralai/Mistral-7B-Instruct-v0.3" has been assessed as feasible
    When the orchestrator generates ModelSpec code
    Then the generated code should be syntactically valid Python
    And the code should define a ModelSpec class
    And the code should include serve_command with vLLM parameters
    And the code should be validated in an isolated environment
    And the code should pass XAI critique with score >= 7

  @tier-2 @model-add @feasible @tensor-parallel
  Scenario: Add larger model requiring tensor parallelism
    Given I have not previously added "Qwen/Qwen2.5-Coder-32B-Instruct"
    When I run "/model add Qwen/Qwen2.5-Coder-32B-Instruct" via CLI
    Then the model should be assessed as "feasible"
    And the KB entry should indicate tensor parallelism required
      | field              | value |
      | Min Tensor Parallel| 4     |
      | Min GPUs           | 4     |
    And the Feasibility section should show "✅ Can run locally"

  # ==========================================================================
  # Infeasible Model Addition - Fail Fast with Alternatives
  # ==========================================================================

  @tier-2 @model-add @infeasible @fail-fast
  Scenario: Add model too large for local hardware (fail fast)
    Given I have not previously added "meta-llama/Llama-3.1-70B-Instruct"
    When I run "/model add meta-llama/Llama-3.1-70B-Instruct" via CLI
    Then the model should be assessed as "infeasible"
    And the assessment should fail fast without generating ModelSpec
    And a KB entry should still be created with status "infeasible"
    And the KB entry should include
      | section     | content_pattern                              |
      | Feasibility | ❌ Cannot run locally                        |
      | Feasibility | Model requires TP=8 but only 6 GPUs available|
      | Feasibility | Model requires ~\d+GB VRAM but only \d+GB    |

  @tier-2 @model-add @infeasible @lambda-labs
  Scenario: Infeasible model includes Lambda Labs cloud options
    Given I have not previously added "meta-llama/Llama-3.1-70B-Instruct"
    When I run "/model add meta-llama/Llama-3.1-70B-Instruct" via CLI
    Then the KB entry should include a "Cloud Options (Lambda Labs)" section
    And the cloud options should list instance types meeting requirements
      | instance             | gpus          | vram   |
      | gpu_8x_a100_40gb_sxm | 8x A100 40GB  | 320GB  |
      | gpu_8x_a100_80gb_sxm | 8x A100 80GB  | 640GB  |
    And the KB entry should include a "Recommended Cloud Instance" section
    And the recommended instance should be the cheapest meeting requirements

  @tier-2 @model-add @infeasible @lambda-labs @availability
  Scenario: Infeasible model shows best available Lambda Labs instance
    Given I have not previously added "meta-llama/Llama-3.1-70B-Instruct"
    And Lambda Labs API returns current availability
    When I run "/model add meta-llama/Llama-3.1-70B-Instruct" via CLI
    Then the "Recommended Cloud Instance" section should show
      | field    | expected_pattern          |
      | GPUs     | 8x A100                   |
      | VRAM     | \d+GB total               |
      | Cost     | \$\d+\.\d{2}/hr           |
      | Regions  | .+, .+                    |
    And the recommendation should be based on real-time availability

  @tier-2 @model-add @infeasible @cerebras
  Scenario: Infeasible model includes Cerebras hosted inference option
    Given I have not previously added "meta-llama/Llama-3.1-70B-Instruct"
    When I run "/model add meta-llama/Llama-3.1-70B-Instruct" via CLI
    Then the KB entry should include a "Hosted Inference Option (Cerebras)" section
    And the Cerebras section should show
      | field    | expected_pattern           |
      | Model    | llama-3.3-70b              |
      | Speed    | ~\d+,\d+ tokens/sec        |
      | Pricing  | \$\d+\.\d{2}/M input       |
      | Context  | \d+,\d+ tokens             |

  @tier-2 @model-add @infeasible @cost-comparison
  Scenario: Infeasible model includes cost comparison analysis
    Given I have not previously added "meta-llama/Llama-3.1-70B-Instruct"
    When I run "/model add meta-llama/Llama-3.1-70B-Instruct" via CLI
    Then the KB entry should include a cost comparison section
    And the cost comparison should show for 100K tokens/hour workload
      | option         | cost_pattern    |
      | Cerebras API   | ~\$\d+\.\d{2}/hr|
      | GPU Rental     | \$\d+\.\d{2}/hr |
    And the comparison should include break-even analysis
    And the comparison should recommend the cost-effective option

  @tier-2 @model-add @infeasible @massive
  Scenario: Add extremely large model with limited cloud options
    Given I have not previously added "meta-llama/Llama-3.1-405B-Instruct"
    When I run "/model add meta-llama/Llama-3.1-405B-Instruct" via CLI
    Then the model should be assessed as "infeasible"
    And the KB entry should show VRAM requirement ~974GB
    And the cloud options should only show high-end instances
      | instance         | vram    |
      | gpu_8x_b200_sxm6 | 1440GB  |
    And no Cerebras option should be available
      # Cerebras doesn't host 405B models

  @tier-2 @model-add @infeasible @vision
  Scenario: Add multimodal vision model with hardware constraints
    Given I have not previously added "zai-org/GLM-4.6V"
    When I run "/model add zai-org/GLM-4.6V" via CLI
    Then the model should be assessed as "infeasible"
    And the KB entry should indicate
      | field              | value          |
      | Parameters         | ~107.7B        |
      | Min Tensor Parallel| 16             |
      | VRAM Required      | ~258.5GB       |
    And the Feasibility section should show multiple constraints
      | constraint                              |
      | Model requires TP=16 but only 6 GPUs    |
      | Model requires ~259GB VRAM but only 144GB|
    And the Cerebras section should show GLM-4.6 as available option
      | field   | value         |
      | Model   | glm-4.6       |
      | Speed   | ~1,000 tok/s  |

  # ==========================================================================
  # Model Listing and Registry
  # ==========================================================================

  @tier-1 @model-list
  Scenario: List models in registry
    Given models have been added to the registry
    When I run "/model list" via CLI
    Then the response should list all registered models
    And each model should show
      | field      | description                |
      | model_id   | HuggingFace model ID       |
      | status     | feasible or infeasible     |
      | parameters | Model size                 |

  @tier-1 @model-list @filter
  Scenario: List models filtered by capability
    Given models have been added to the registry
    When I run "/model list --capability reasoning" via CLI
    Then only models with "reasoning" capability should be listed
    And models should be sorted by capability score

  # ==========================================================================
  # Research Integration - Wiki Links to Model Library
  # ==========================================================================

  @tier-3 @research @wiki-links @engine-required
  Scenario: Research creates wiki links to model library entries
    Given a model KB entry exists for "zai-org/GLM-4.6V"
    When I run "/research GLM-4.1V-Thinking: Towards Versatile Multimodal Reasoning" via CLI
    Then the research note should be created in "scratch/{date}/"
    And the research note should include KB sources
    And the KB sources should include the GLM-4.6V model entry
    And the research note should contain a wiki link to the model entry
      | pattern                                          |
      | \[GLM-4\.6V\]\(scratch/.*/models/.*glm.*\.md:.*\)|
    And the wiki link should use extended citation format with regex anchor

  @tier-3 @research @wiki-links @semantic
  Scenario: Research finds related model entries via semantic search
    Given model KB entries exist for multiple models
      | model_id                              | status     |
      | mistralai/Mistral-7B-Instruct-v0.3    | feasible   |
      | meta-llama/Llama-3.1-70B-Instruct     | infeasible |
      | zai-org/GLM-4.6V                      | infeasible |
    When I run "/research comparing instruction-tuned language models" via CLI
    Then the research note should include relevant model entries
    And the model entries should be found via hybrid search
      | search_type | description                        |
      | bm25        | Keyword match on model names/tags  |
      | vector      | Semantic similarity on descriptions|

  @tier-3 @research @citations
  Scenario: Research verifies citations including model references
    Given a model KB entry exists with HuggingFace link
    When I run "/research! {topic}" via CLI
    Then the research note should be evaluated
    And citations to model entries should be verified
    And the evaluation should score citation accuracy

  # ==========================================================================
  # Search Integration
  # ==========================================================================

  @tier-2 @search @model-discovery
  Scenario: Search finds model entries by model ID
    Given model KB entries exist in the model library
    When I run "/search GLM-4.6V model" via CLI
    Then the search results should include the model KB entry
    And the result should show
      | field   | pattern                              |
      | path    | scratch/.*/models/.*glm.*\.md        |
      | title   | GLM-4.6V                             |
      | snippet | model_id: zai-org/GLM-4.6V           |

  @tier-2 @search @provider-discovery
  Scenario: Search finds provider documentation
    Given provider KB entries exist for Lambda Labs and Cerebras
    When I run "/search GPU rental cloud inference" via CLI
    Then the search results should include provider entries
    And results should include
      | provider    | path                          |
      | Lambda Labs | current/providers/lambdalabs.md|
      | Cerebras    | current/providers/cerebras.md  |

  # ==========================================================================
  # Error Handling
  # ==========================================================================

  @tier-1 @error-handling
  Scenario: Handle invalid model ID gracefully
    When I run "/model add not-a-valid/model-id-12345" via CLI
    Then the command should fail with informative error
    And the error should indicate model not found on HuggingFace
    And no KB entry should be created

  @tier-1 @error-handling @gated
  Scenario: Handle gated model requiring authentication
    When I run "/model add meta-llama/Llama-3.1-405B-Instruct" via CLI
    And the model requires HuggingFace authentication
    Then the command should provide guidance on HF_TOKEN
    And a KB entry should still be created with available public info

  @tier-2 @error-handling @api-failure
  Scenario: Handle Lambda Labs API unavailability
    Given Lambda Labs API is temporarily unavailable
    When I run "/model add meta-llama/Llama-3.1-70B-Instruct" via CLI
    Then the KB entry should be created without cloud recommendations
    And the entry should note "Cloud options unavailable - API error"
    And the entry should still include Cerebras options if available

  @tier-2 @error-handling @cerebras-failure
  Scenario: Handle Cerebras API unavailability
    Given Cerebras API is temporarily unavailable
    When I run "/model add meta-llama/Llama-3.1-70B-Instruct" via CLI
    Then the KB entry should be created without Cerebras section
    And the entry should still include Lambda Labs cloud options

  # ==========================================================================
  # Idempotency and Updates
  # ==========================================================================

  @tier-2 @idempotency
  Scenario: Re-adding existing model updates KB entry
    Given a model KB entry exists for "mistralai/Mistral-7B-Instruct-v0.3"
    When I run "/model add mistralai/Mistral-7B-Instruct-v0.3" via CLI
    Then the existing KB entry should be updated
    And cloud options should reflect current availability
    And the entry should show "updated" timestamp

  @tier-2 @refresh
  Scenario: Refresh model library with current cloud pricing
    Given model KB entries exist with cloud options
    When I run "/model refresh" via CLI
    Then all infeasible model entries should be updated
    And Lambda Labs availability should be refreshed
    And Cerebras pricing should be refreshed

  # ==========================================================================
  # Provider KB Documentation
  # ==========================================================================

  @tier-1 @provider-docs
  Scenario: Lambda Labs provider documentation exists
    When I read "current/providers/lambdalabs.md"
    Then the document should include
      | section          | content_pattern                    |
      | Overview         | GPU cloud                          |
      | API              | cloud.lambdalabs.com/api           |
      | Instance Types   | A100.*H100.*B200                   |
      | Pricing          | \$/hr                              |

  @tier-1 @provider-docs
  Scenario: Cerebras provider documentation exists
    When I read "current/providers/cerebras.md"
    Then the document should include
      | section          | content_pattern                    |
      | Overview         | ultra-fast hosted inference        |
      | API              | api.cerebras.ai                    |
      | Available Models | Llama.*Qwen                        |
      | Pricing          | \$/M.*tokens                       |
      | Cost Comparison  | Break-even                         |
