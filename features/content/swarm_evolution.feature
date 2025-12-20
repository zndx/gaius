Feature: Swarm Analysis and Evolution
  As a Gaius power user
  I want to run multi-agent analysis and evolve agent prompts
  So I can get high-quality insights and continuously improve the system

  Background:
    Given the Gaius TUI is running
    And the inference stack is available

  # ─────────────────────────────────────────────────────────────────────
  # Swarm Analysis
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Run swarm analysis with '/swarm'
    Given the domain is set to "pension risk"
    When I enter command "/swarm"
    Then a swarm analysis should start
    And the content panel should show analysis progress
    And multiple agents should contribute perspectives

  Scenario: Swarm respects configured agent roster
    Given the swarm configuration includes agents:
      | Role      |
      | Leader    |
      | Risk      |
      | Optimizer |
      | Critic    |
    When I run a swarm analysis
    Then each configured agent should provide a response
    And responses should be synthesized by the Leader

  Scenario: Swarm results include token metrics
    When a swarm analysis completes
    Then results should include total tokens used
    And results should include latency metrics
    And results should include per-agent contributions

  Scenario: Swarm auto-triggers on domain change
    Given swarm auto-trigger is enabled
    When I enter command "/domain new-topic"
    Then a swarm analysis should start automatically

  # ─────────────────────────────────────────────────────────────────────
  # Agent Positions
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Agents have positions after swarm
    When a swarm analysis completes
    Then agents should have assigned grid positions
    And positions should reflect semantic alignment

  Scenario: Agent overlay shows positions
    Given a swarm analysis has completed
    When I set overlay mode to "agents"
    Then agent positions should be visible on the grid
    And each agent should have a distinct marker

  Scenario: View agent status with '/agents'
    When I enter command "/agents"
    Then the content panel should list all agents
    And each agent should show position and last activity

  # ─────────────────────────────────────────────────────────────────────
  # Evolution Daemon
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Start evolution daemon with '/evolve start'
    When I enter command "/evolve start fast"
    Then orphaned vLLM processes should be cleaned up
    And the fast endpoint should start on GPU 3
    And the evolution daemon should begin monitoring

  Scenario: Evolution daemon monitors GPU idle state
    Given the evolution daemon is running
    When GPU utilization drops below 20%
    Then an evolution cycle should be triggered
    And the next agent in rotation should be optimized

  Scenario: Evolution respects rate limits
    Given the evolution daemon is running
    And an evolution cycle just completed
    When I check the daemon status
    Then it should respect max_cycles_per_hour setting

  Scenario: Stop evolution daemon with '/evolve stop'
    Given the evolution daemon is running
    When I enter command "/evolve stop"
    Then the evolution daemon should stop
    And GPU endpoints should remain available

  # ─────────────────────────────────────────────────────────────────────
  # Evolution Cycles
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Evolution cycle optimizes agent prompt
    Given the evolution daemon is running
    And sufficient training examples exist
    When an evolution cycle runs for "leader"
    Then the system should:
      | Step                          |
      | Collect training examples     |
      | Generate prompt candidates    |
      | Evaluate candidates           |
      | Save improved version if better |

  Scenario: Manual evolution trigger with '/evolve trigger'
    Given the evolution daemon is running
    When I enter command "/evolve trigger risk"
    Then an evolution cycle should start for "risk" immediately
    And the cycle should bypass idle check

  Scenario: Evolution cycle uses GEPA strategy
    Given the evolution strategy is "gepa"
    When an evolution cycle runs
    Then Pareto-optimal candidates should be identified
    And multiple objectives should be balanced

  Scenario: Evolution cycle records to database
    When an evolution cycle completes
    Then the cycle should be logged to evolution_cycles table
    And metrics should include improvement percentage
    And metrics should include examples used

  # ─────────────────────────────────────────────────────────────────────
  # Evolution Panel
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Evolution panel shows daemon status
    Given the center panel mode is "evolution"
    Then the Evolution panel should show:
      | Field               | Description                |
      | Status              | RUNNING or STOPPED         |
      | Cycles              | Total completed cycles     |
      | Improvement         | Cumulative improvement %   |
      | Next Agent          | Next in rotation           |

  Scenario: Evolution panel shows recent cycles
    Given the center panel mode is "evolution"
    And evolution cycles have occurred
    Then the Evolution panel should list recent cycles
    And each cycle should show:
      | Field      | Example        |
      | Timestamp  | 14:32          |
      | Agent      | leader         |
      | Status     | ✓ or ✗         |
      | Improvement| +2.3%          |
      | Duration   | 1.2s           |

  Scenario: Evolution panel shows agent scores
    Given the center panel mode is "evolution"
    Then the Evolution panel should show per-agent scores
    And scores should include training vs held-out
    And trends should be indicated (↗ ↘ →)

  # ─────────────────────────────────────────────────────────────────────
  # Held-Out Evaluation
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Held-out queries used for objective evaluation
    When daily evaluation runs
    Then held-out queries should be used
    And held-out results should not influence training

  Scenario: Overfitting detection via score comparison
    Given training and held-out scores are tracked
    When held-out score drops significantly below training score
    Then the system should flag potential overfitting

  # ─────────────────────────────────────────────────────────────────────
  # XAI Budget Management
  # ─────────────────────────────────────────────────────────────────────

  Scenario: View XAI budget with '/evolve budget'
    When I enter command "/evolve budget"
    Then the content panel should show:
      | Field           | Description              |
      | Daily Used      | XAI calls today          |
      | Daily Limit     | Maximum daily calls (50) |
      | Weekly Used     | XAI calls this week      |
      | Weekly Limit    | Maximum weekly calls     |

  Scenario: Tiered evaluation respects budget
    Given XAI daily budget is exhausted
    When evaluation is needed
    Then local model should be used instead
    And evaluation should still complete

  # ─────────────────────────────────────────────────────────────────────
  # Training Data Collection
  # ─────────────────────────────────────────────────────────────────────

  Scenario: Training examples collected from swarm runs
    When a swarm analysis completes with good results
    Then high-quality outputs should be collected as training examples
    And examples should be stored in the database

  Scenario: Bootstrap examples from held-out queries
    Given no organic training data exists
    When evolution attempts to run
    Then held-out queries should be used as bootstrap examples
    And evolution should still proceed

  Scenario: Minimum examples required for evolution
    Given fewer than 5 training examples exist
    When evolution cycle attempts to run
    Then the cycle should skip with "insufficient examples"
    And the next agent in rotation should be tried
