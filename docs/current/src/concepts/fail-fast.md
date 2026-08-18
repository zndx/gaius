# Fail-Fast & Self-Healing

Fail-fast is an iron-clad design principle in Gaius. All code surfaces errors immediately with actionable remediation paths. The system never silently degrades, falls back to placeholders, or continues with partial functionality.

## The Principle

When something goes wrong, the correct response is not to hide it — it's to surface it immediately with enough information to fix it. Every error message in Gaius includes:

1. **Guru Meditation Code**: A unique identifier for the failure mode
2. **Health Fix Command**: A reference to `/health fix <service>` when applicable
3. **Manual Remediation**: Alternative manual steps if self-healing can't resolve it

```python
error_msg = (
    "DatasetService not initialized.\n"
    "  Guru: #DS.00000001.SVCNOTINIT\n"
    "  Try: /health fix dataset\n"
    "  Or:  just restart-clean"
)
```

## Guru Meditation Codes

Inspired by the Amiga's memorable error screens, every failure mode gets a unique identifier.

**Format**: `#<COMPONENT>.<SEQUENCE>.<MNEMONIC>`

| Component | Description |
|-----------|-------------|
| DS | DatasetService |
| NF | NiFi |
| EN | Engine |
| EP | Endpoints/Inference |
| EV | Evolution |
| DB | Database |
| QD | Qdrant |
| GR | gRPC |
| ACP | Agent Client Protocol |
| ACF | Article Curation Flow |

Each code maps to exactly one failure mode. A failure mode may have multiple diagnostic heuristics, but the code is the canonical identifier.

See [Guru Meditation Codes](../reference/guru-codes.md) for the complete catalog.

## What Fail-Fast Prohibits

### No Optional Fallbacks

Never use `fail_fast=True` as a parameter. Fail-fast is the ONLY behavior, not an option.

### No Silent Degradation

If a required resource is unavailable (LLM endpoint, NiFi, database), raise an error immediately. Never substitute placeholder data or skip functionality.

### No Conditional Feature Flags for Core Functionality

Don't use patterns like `if SELENIUM_AVAILABLE:` with an else clause that produces fake data. Either the feature works or it fails.

## Fail Open for Observability

The counterpart to fail-fast for observability code is **fail open**. When filtering or displaying health state:

1. **Filter OUT, not IN**: When showing active incidents, filter out known terminal states (`resolved`) rather than filtering in known active states. Unknown states are surfaced for investigation.

2. **Unknown States are Visible**: Any state not in the "terminal" list is displayed. This ensures new or unexpected states don't silently disappear.

```python
# BAD: Filtering IN known active states (brittle)
active = [i for i in incidents if i.status in ("active", "healing")]

# GOOD: Filtering OUT known terminal states (fail open)
active = [i for i in incidents if i.status != "resolved"]
```

## Self-Healing Hierarchy

When services are unhealthy, Gaius follows a remediation hierarchy:

1. **`/health fix <service>`** — Let Gaius attempt self-healing first
2. **Manual commands** (`just restart-clean`, etc.) — Only if self-healing fails
3. **ACP escalation** — For novel failures that need human or AI intervention

The Health Observer daemon continuously monitors all system components. When an incident exceeds the configured FMEA RPN (Risk Priority Number) threshold, it escalates through ACP to grok-build (local thinking by default) for meta-level intervention.

## Heuristics and KB

Each failure mode has a corresponding heuristic document in the knowledge base:

- **Symptom**: Brief description of what the user sees
- **Cause**: Why this happens
- **Observation**: How to detect it programmatically
- **Solution**: How to fix it, with `/health fix` command

This creates a closed loop: errors reference codes, codes map to heuristics, heuristics provide automated fixes.
