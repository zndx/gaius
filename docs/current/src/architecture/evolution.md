# Evolution

The evolution subsystem optimizes agent system prompts through RLVR (Reinforcement Learning with Verifiable Reward) during GPU idle periods. It generates candidate prompts, evaluates them against held-out tasks, and promotes winners — operating as a continuous self-improvement loop.

## Evolution Cycle

```
1. EvolutionDaemon monitors GPU utilization
2. When idle (<30% for 60s), select next agent (round-robin)
3. CurriculumAgent orders tasks by difficulty
4. AgentRunner generates responses via engine scheduler
5. DaemonOracle verifies responses against RASE constraints
6. compute_reward() produces scalar training signal
7. APO/GEPA optimizes prompt based on reward trajectory
8. If improved, promote new version; record lineage
```

The `DaemonOracle` uses the same RASE verification pipeline as production — `Constraint[S]` composition evaluated against API ground truth. This ensures the evolution reward signal is verifiable, not learned.

## Optimization Methods

| Method | Description | Reference |
|--------|-------------|-----------|
| APO | Automatic Prompt Optimization — gradient-free meta-prompt search | Zhou et al., 2023 |
| GEPA | Genetic Evolution of Prompt Architectures — crossover/mutation | Guo et al., 2024 |

## Task Sources

Evolution draws training tasks from three sources:

| Source | Method | Coverage |
|--------|--------|----------|
| Nous Research | JSONL reasoning tasks (`load_reasoning_tasks()`) | General reasoning |
| RASE Objectives | KB objectives → tasks via `ObjectiveGenerator` | Domain-specific verification |
| Task Ideation | `TaskIdeationAgent` analyzes capability gaps | Targeted improvement |

The `CurriculumAgent` orders tasks by difficulty, ensuring agents encounter progressively harder challenges rather than random sampling.

## Held-Out Evaluation

The `DailyEvaluator` runs held-out evaluation against a reserved query pool — queries the evolution process has never seen:

1. Sample N queries from the held-out pool (default 50)
2. Run each through `AgentRunner` with the current prompt
3. Score responses via the xAI evaluator (independent critique)
4. Aggregate into a `DailyEvalSummary` with accuracy, per-capability breakdown, and trend

This provides an unbiased measurement of agent improvement over time, separate from the training reward signal.

## Calibration

The `CalibrationOracle` cross-validates local evaluation scores against frontier models (Cerebras, xAI). If local scores diverge significantly from frontier assessments, it flags calibration drift — preventing the system from optimizing toward a biased local metric.

## Model Merging

Agent versions can be combined in parameter space:

| Method | Description | Reference |
|--------|-------------|-----------|
| Linear | Weighted average: theta = alpha * theta_1 + (1-alpha) * theta_2 | — |
| TIES | Resolves sign conflicts between model deltas | Yadav et al., 2023 |
| DARE | Drop and rescale for sparse merging | Yu et al., 2024 |

The `MergeCoordinator` identifies merge candidates (versions with complementary strengths) and validates merged models before registration.

## Atropos Compatibility

`GaiusEvolutionEnv` implements the Atropos `BaseEnv` interface, exposing Gaius evolution as a standard RL environment for external frameworks:

```python
env = GaiusEvolutionEnv("leader")
item = await env.get_next_item()      # Training task
reward = await env.score_response(response)  # Verifiable reward
```

## Configuration

```hocon
evolution {
    enabled = true
    idle_threshold = 60    # seconds of GPU idle before triggering
    cycle_interval = 3600  # minimum seconds between cycles
}
```

The daemon runs in the engine process and activates only during GPU idle periods to avoid competing with interactive inference.
