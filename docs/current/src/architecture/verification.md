# Verification

The Verifier Model (VM) implements RLVR -- Reinforcement Learning with Verifiable Reward. The oracle provides ground-truth verification using authoritative API sources, never UI observations. UI traces are the *training target*, not the oracle.

## VerdictKind

Every verification case produces one of four outcomes:

| Verdict | Meaning | Default Reward |
|---------|---------|----------------|
| `PASS` | All requirements satisfied | 1.0 |
| `FAIL` | One or more requirements not satisfied | 0.0 (or accuracy for partial credit) |
| `INCONCLUSIVE` | Could not determine (missing data) | 0.5 |
| `ERROR` | Verification itself failed (infrastructure) | 0.0 |

## Accuracy

Accuracy is always a float in `[0.0, 1.0]`, representing the proportion of constraints satisfied. It provides the foundation for graded reward strategies.

```python
# Computed inside verification cases:
passed_count = sum(1 for r in constraint_results if r.satisfied)
accuracy = passed_count / len(constraint_results)
```

## Verification Cases

Two types of verification cases exist:

- **APIVerificationCase** -- the RLVR oracle. Checks system state via the NiFi REST API. Evaluates Given (setup), Then (end-state), invariant, and transition constraints.
- **UIVerificationCase** -- verifies agent UI actions. The final state is still checked via API; the trace captures what the agent did to get there.

```python
case = APIVerificationCase(
    id=TraceableId.generate(scheme=IdScheme.RASE, prefix="verify"),
    name="Verify_CreateBasicFlow",
    objective=VerificationObjective(requirement_ids=[scenario.id]),
    scenario_requirement=scenario_req,
)
result = await case.execute(current_nifi_state)
```

## Reward Strategies

Reward strategies convert verification results into training signals:

| Strategy | Signal Type | Use Case |
|----------|-------------|----------|
| `BinaryReward` | Sparse (0 or 1) | Clear pass/fail tasks, early training |
| `GradedReward` | Dense (0.0--1.0 with partial credit) | Multi-step tasks, complex scenarios |
| `StepwiseReward` | Dense per step | Long sequences where intermediate progress matters |
| `TrajectoryShaping` | Dense with efficiency | Tasks where path quality matters |

```python
from gaius.rase import GradedReward, compute_reward

strategy = GradedReward(pass_bonus=0.1, fail_penalty=0.0)
reward = compute_reward(result, strategy=strategy)
```

## Oracle

The `NiFiOracle` provides authoritative verification:

1. Agent takes UI actions to modify NiFi
2. Oracle queries NiFi REST API to check resulting state
3. State is compared against scenario requirements (constraints)
4. Reward is computed from the `VerificationResult`

```python
oracle = NiFiOracle(reward_strategy=GradedReward())
result, reward = await oracle.verify_and_reward(scenario_req, trace=ui_trace)
```

Advanced oracles include `CurriculumOracle` (progressive difficulty) and `EnsembleOracle` (multi-source consensus).

## Source

Verification infrastructure lives in `src/gaius/rase/vm/` with verification cases in `verification.py`, requirements in `requirements.py`, and oracle/reward logic in `oracle.py`.
