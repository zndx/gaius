# RASE Gap Analysis

**Date**: 2025-12-21
**Status**: Active development planning

---

## Executive Summary

RASE infrastructure is well-designed but not yet wired together for end-to-end execution. The metamodel exists, the BDD features exist, the evolution daemon exists - but the RASE loop (Observe → Generate → Execute → Verify → Learn) is not closed.

---

## What Exists

### 1. RASE Metamodel (`gaius.rase`)

**Complete and well-structured:**

| Package | Purpose | Status |
|---------|---------|--------|
| `core/` | Generic abstractions (SystemState, Constraint, Oracle, RewardStrategy) | ✅ Complete |
| `domains/nifi/` | NiFi-specific state, constraints, oracle | ✅ Complete |
| `osm/` | BDD scenario model (StepDef, Scenario, Feature) | ✅ Complete |
| `uom/` | UI observation model (SoM, ToM, traces) | ✅ Complete |
| `vm/` | Verifier model (Requirements, VerificationCase) | ✅ Complete |
| `traceability.py` | TraceableId, DigitalThread | ✅ Complete |

**Key insight**: The architecture mirrors SysML v2 with Python-native Pydantic models. The generic `Oracle[S]` and `Constraint[S]` patterns enable domain reuse.

### 2. BDD Features

**Curriculum exists:**
- `features/nifi/curriculum/level0_basic.feature` - Basic NiFi operations
- `features/nifi/curriculum/level1_flows.feature` - Flow operations

**Step definitions exist but are stubs:**
- `features/nifi/steps/nifi_steps.py` - Has decorators but `# TODO` implementations

### 3. NiFi Client

**Complete async HTTP client:**
- `src/gaius/agents/metaagent/nifi/client.py` - Full NiFi REST API coverage
- Authentication, processor CRUD, connections, process groups

### 4. Evolution Daemon

**Complete infrastructure:**
- `src/gaius/agents/evolution/daemon.py` - Background GPU-aware daemon
- `src/gaius/agents/evolution/evaluation.py` - HeldOutManager, DailyEvaluator
- APO/GEPA optimization strategies
- Task ideation and model merging hooks

### 5. Cognition

**Self-observation exists:**
- `trigger_cognition`, `trigger_self_observation` MCP tools
- Thought chains with predecessor tracking

---

## What's Missing (The Gaps)

### Gap 1: Oracle ↔ NiFi Client Integration

**Problem**: `NiFiOracle.get_current_state()` raises `NotImplementedError`

```python
# Current state in domains/nifi/oracle.py:79
raise NotImplementedError(
    "NiFi client integration pending. "
    "Use NiFiStateManager.capture_state() for actual state capture."
)
```

**Solution**: Wire NiFiClient into NiFiOracle:
1. Pass NiFiClient instance to oracle
2. Implement `get_current_state()` to fetch via API
3. Map API response to `NiFiInstance` model

**Complexity**: Low (plumbing work)

### Gap 2: BDD Steps ↔ RASE Constraints

**Problem**: Step definitions are stubs that don't use RASE constraints

```python
# Current state in nifi_steps.py:57
@then('the processor "{name}" should exist in the root group')
def step_processor_exists(context, name):
    # TODO: Use RASE ProcessorExists constraint
    pass
```

**Solution**: Implement steps using RASE verification:
1. Create/inject NiFiOracle into behave context
2. In `@then` steps, build constraints and call `oracle.verify_constraints()`
3. Assert on `VerificationResult.verdict`

**Complexity**: Medium (need to handle state capture timing)

### Gap 3: Training Data Pipeline

**Problem**: No path from "verified BDD scenario" to "training example"

The RASE loop requires:
1. Execute BDD scenario (agent takes actions)
2. Capture UI trace (ToM)
3. Verify via API oracle
4. If PASS → convert to training format
5. Feed to evolution daemon

**Missing pieces:**
- Trace recorder integration with BDD execution
- Training example serialization (Magma/LLaVA format already exists in dataset_service)
- Hook from oracle verification → training pool

**Complexity**: Medium-High (requires state machine for capture)

### Gap 4: Autonomous Task Generation

**Problem**: `trigger_task_ideation` exists but doesn't generate BDD scenarios

Current task ideation creates "task concepts" but these aren't:
1. Grounded in capability gaps (topology-based)
2. Structured as executable BDD scenarios
3. Fed back into the curriculum

**Solution**: Implement `BDDScenarioGenerator`:
1. Input: Capability gaps from held-out evaluation
2. Output: New `.feature` file scenarios
3. Ensure intrinsic verifiability (constraints exist for the scenario)

**Complexity**: High (requires gap → constraint → scenario mapping)

### Gap 5: Evolution Daemon ↔ RASE Integration

**Problem**: Evolution daemon optimizes prompts but not via RASE verification

Current flow:
- Daemon runs GEPA/APO optimization
- Uses XAI evaluation for scoring (external labeler)

RASE flow should be:
- Daemon runs agent on BDD scenario
- Oracle verifies result intrinsically
- Reward computed from `VerificationResult`
- No XAI in the training loop (only for calibration/audit)

**Complexity**: Medium (change evaluation path)

---

## Minimal Viable RASE Loop

To close the loop with minimum work:

### Phase A: Manual E2E (Validate Architecture)

1. **Wire NiFiOracle to NiFiClient**
   - `NiFiOracle(nifi_client=client)`
   - Implement `get_current_state()`

2. **Implement 2-3 BDD steps fully**
   - Pick `level0_basic.feature` Scenario: "Create a single processor"
   - Implement Given/When/Then with real NiFi calls
   - Verify via oracle at end

3. **Manual verification test**
   - Run scenario via pytest-bdd
   - Print `VerificationResult` and reward
   - Confirm oracle matches expected state

**Deliverable**: One scenario that executes and verifies intrinsically

### Phase B: Automated Training Capture

4. **Add trace recording to BDD execution**
   - Wrap NiFi client calls with `TraceRecorder`
   - Capture before/after states per step

5. **Convert verified runs to training examples**
   - On PASS: Serialize scenario + trace to training format
   - Store in PostgreSQL `training_examples` table

6. **Hook into evolution daemon**
   - Evolution uses training examples from RASE runs
   - Fallback to held-out pool if insufficient

**Deliverable**: Training examples generated from BDD execution

### Phase C: Autonomous Expansion

7. **Implement capability gap detection**
   - Analyze verification results by constraint type
   - Identify which constraints fail most

8. **Generate new BDD scenarios targeting gaps**
   - Use constraint catalog to build valid scenarios
   - Difficulty progression via curriculum oracle

9. **Full autonomous loop**
   - Daemon idle → generate new scenario → execute → verify → train
   - No human in the loop except for review

**Deliverable**: Self-expanding curriculum

---

## Recommended Starting Point

**Start with Gap 1 + Gap 2** - these are the foundation.

Without oracle ↔ client integration, nothing else works. Without step ↔ constraint integration, we can't verify.

Once one scenario executes and verifies end-to-end, the architecture is validated and we can parallelize:
- Gap 3 (training pipeline) - can develop independently
- Gap 4 (scenario generation) - needs Gap 3 first
- Gap 5 (daemon integration) - needs Gap 3 first

---

## Files to Modify

| Priority | File | Change |
|----------|------|--------|
| P0 | `src/gaius/rase/domains/nifi/oracle.py` | Implement `get_current_state()` |
| P0 | `features/nifi/steps/nifi_steps.py` | Implement steps with RASE constraints |
| P1 | `src/gaius/rase/osm/registry.py` | Add trace recording hooks |
| P1 | `src/gaius/agents/evolution/daemon.py` | Add RASE verification path |
| P2 | `src/gaius/rase/` (new file) | `scenario_generator.py` |

---

## Open Questions

1. **NiFi availability**: Is NiFi running for development? Need `DISABLE_NIFI=false`
2. **Parallel domain**: Should we implement a simpler domain first (e.g., KB operations) to validate the loop without NiFi complexity?
3. **UI traces**: Do we need actual UI traces (Selenium) or is API-only verification sufficient for Phase A?

---

*Next step: Review this analysis and confirm approach before implementation.*
