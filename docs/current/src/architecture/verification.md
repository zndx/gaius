# Verification

The Verifier Model (VM) implements RLVR — Reinforcement Learning with Verifiable Reward (as distinct from RLHF, which depends on learned reward models). The oracle provides ground-truth verification using authoritative API sources, never UI observations. UI traces are the *training target*, not the oracle.

## VerdictKind

Every verification case produces one of four outcomes:

| Verdict | Meaning | Default Reward |
|---------|---------|----------------|
| `PASS` | All constraints satisfied | 1.0 |
| `FAIL` | One or more constraints not satisfied | 0.0 (or accuracy for partial credit) |
| `INCONCLUSIVE` | Could not determine (missing data) | 0.5 |
| `ERROR` | Verification itself failed (infrastructure) | 0.0 |

## Accuracy

Accuracy is always a float in `[0.0, 1.0]`, computed as the proportion of constraints satisfied with uniform weighting:

```
accuracy = |{c ∈ C : pass(c)}| / |C|
```

This provides the foundation for graded reward strategies. A scenario with 8 of 10 constraints passing yields accuracy 0.8, which `GradedReward` can convert to a dense training signal with partial credit.

## Verification Cases

Two types serve different purposes in the training pipeline:

**APIVerificationCase** — the RLVR oracle. Checks system state via the NiFi REST API. Evaluates Given (setup preconditions), Then (end-state assertions), invariant (must hold throughout), and transition constraints (state change patterns). This is the ground truth.

**UIVerificationCase** — verifies agent UI actions. The agent's browser trace (SoM/ToM marks, click coordinates, navigation steps) is recorded. The *final state* is still checked via API; the trace captures the path the agent took to get there. Good traces on passing verification cases become training data.

## Constraint Composition

Constraints are generic over `SystemState` and support algebraic composition:

```python
constraint: Constraint[NiFiInstance] = AllOf([
    ProcessorExists(name="Generate Data"),
    ProcessorHasType(name="Generate Data", type_pattern="GenerateFlowFile"),
    Not(ProcessorExists(name="Obsolete Processor")),
])
result: ConstraintResult = constraint.evaluate(state)
```

`AllOf`, `AnyOf`, and `Not` compose arbitrarily. Each `ConstraintResult` carries a boolean `satisfied`, a human-readable `message`, and the constraint's `name` — enabling precise identification of which constraint in a composition failed and why.

## Reward Strategies

Reward strategies convert verification results into RL training signals:

| Strategy | Signal Type | Use Case |
|----------|-------------|----------|
| `BinaryReward` | Sparse (0 or 1) | Clear pass/fail tasks, early training |
| `GradedReward` | Dense (0.0–1.0 with partial credit) | Multi-step tasks, complex scenarios |
| `StepwiseReward` | Dense per step | Long sequences where intermediate progress matters |
| `TrajectoryShaping` | Dense with efficiency bonus | Tasks where path quality matters |

`GradedReward` uses the accuracy score directly: `reward = accuracy * pass_reward + (1 - accuracy) * fail_penalty`. The `pass_bonus` parameter adds a bonus only when accuracy is exactly 1.0, creating an incentive to satisfy *all* constraints rather than settling for partial credit.

## Oracle Hierarchy

The `NiFiOracle` provides base verification. Specialized oracles build on it:

| Oracle | Purpose |
|--------|---------|
| `NiFiOracle` | Base: API state → constraint evaluation → reward |
| `CurriculumOracle` | Progressive difficulty — easier scenarios first, harder as agent improves |
| `EnsembleOracle` | Multi-source consensus — cross-validates against multiple oracles |
| `DaemonOracle` | Used by evolution daemon — same RASE pipeline as production |

The `DaemonOracle` is critical: it ensures evolution's reward signal is *verifiable*, not learned. The same `Constraint[S]` composition that verifies production agents verifies evolution candidates.

## Source

Verification infrastructure lives in `src/gaius/rase/vm/` with verification cases in `verification.py`, requirements in `requirements.py`, and oracle/reward logic in `oracle.py`.
