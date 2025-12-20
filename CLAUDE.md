# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gaius is a CLI-first terminal interface for navigating complex, graph-oriented data domains. Named after Gaius Plinius Secundus (Pliny the Elder), it renders high-dimensional embeddings and topological structures onto a constrained 19×19 grid—transforming abstract complexity into spatial intuition.

## Development Commands

```bash
# Run the TUI application
uv run gaius

# Run the CLI (non-interactive, for testing)
uv run gaius-cli --cmd "/state" --format json

# Build documentation
mdbook build docs

# Build and open documentation
mdbook build docs --open
```

## Module Structure

```
src/gaius/
├── app.py              # Main TUI application (GaiusApp)
├── cli.py              # Non-interactive CLI
├── __main__.py         # Module entry point
├── core/
│   └── state.py        # AppState, ViewMode, OverlayMode
├── widgets/
│   ├── grid.py         # MainGrid (19×19)
│   ├── minigrid.py     # MiniGrid (9×9 orthographic views)
│   ├── filetree.py     # FileTree (KB navigation)
│   ├── content.py      # ContentPanel (right panel)
│   └── command.py      # CommandInput (bottom)
├── static/
│   └── test_data.py    # Static data for UI development
└── agents/             # Agent definitions (planned)
```

## Key Components

**MainGrid**: 19×19 Go board with view modes (Go, Pension, Swarm) and overlays (none, risk, h1, h2, agents, temporal).

**MiniGridPanel**: Three 9×9 orthographic projections that update based on cursor position - CAD-style views showing topology, embeddings, and temporal evolution.

**FileTree**: Plan 9-inspired navigation where agents are represented as files under `/agents/`.

**ContentPanel**: Displays file contents, agent output, and position context.

**CommandInput**: Claude Code-style slash commands with history.

### Key Bindings

- `hjkl`: Navigate cursor (vim-style)
- `v`: Cycle view modes
- `o`: Cycle overlay modes
- `c`: Toggle candidate markers
- `[`/`]`: Toggle left/right panels
- `\`: Toggle both panels
- `/`: Enter command mode
- `?`: Show help
- `t`: Tenuki (jump to strategic point)
- `q`: Quit

## Knowledge Base Structure

Development KB lives under `build/dev/` (gitignored):

```
build/dev/
├── current/            # Active work (manual)
│   ├── projects/
│   └── content/domains/
├── scratch/            # Zettelkasten (by date)
│   └── 2025-11-28/
└── archive/            # Quarterly archives
    └── 2025Q4/attachments/
```

## Dependencies

Core (always): `textual>=0.60.0`

Optional:
- TDA: `numpy`, `scikit-learn`, `giotto-tda` (requires Python 3.11)
- Swarm: `langchain`, `langchain-openai`

Install optional deps: `uv sync --extra tda` or `uv sync --extra swarm`

## Documentation

mdbook documentation in `docs/`. Save work summaries and notes to `docs/notes/$(date --iso-8601)/` with zero-padded numeric prefixes.

## Design Inspirations

- **Go board**: Spatial metaphor, 19×19 grid, tenuki concept
- **Bloomberg Terminal**: Information density, keyboard-first
- **Plan 9 / Acme**: Everything is a file, text as command
- **Claude Code**: Slash commands, conversational interface
- **CAD orthographic views**: Multiple projection views updating together

## Fail-Fast Policy (MANDATORY)

**Fail-fast is an iron-clad design principle in this codebase.** All code must surface errors immediately with actionable remediation paths. Never silently degrade, fall back to placeholders, or continue with partial functionality.

### Implementation Requirements

1. **No Optional Fallbacks**: Never use `fail_fast=True` as a parameter. Fail-fast is the ONLY behavior, not an option.

2. **No Silent Degradation**: If a required resource is unavailable (LLM endpoint, NiFi, database), raise an error immediately. Never substitute placeholder data or skip functionality.

3. **No Conditional Feature Flags for Core Functionality**: Don't use patterns like `if SELENIUM_AVAILABLE:` with an else clause that produces fake data. Either the feature works or it fails.

### Error Message Requirements

All error messages must be **actionable** and include:

1. **Guru Meditation Code**: Unique identifier for the failure mode (e.g., `#DS.00000001.SVCNOTINIT`)
2. **Health Fix Command**: Reference to `/health fix <service>` when applicable
3. **Manual Remediation**: Alternative manual steps

Example:
```python
error_msg = (
    "DatasetService not initialized.\n"
    "  Try: /health fix dataset\n"
    "  Or:  process-compose process restart gaius-engine"
)
```

### Guru Meditation Codes

Inspired by the Amiga's memorable error codes, each failure mode gets a unique identifier:

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

**Examples**:
- `#DS.00000001.SVCNOTINIT` - DatasetService not initialized
- `#NF.00000001.UNREACHABLE` - NiFi not reachable
- `#EP.00000001.GPUOOM` - GPU out of memory

**Codes are unique** - one code maps to exactly one failure mode, though a failure mode may have multiple diagnostic heuristics.

### Heuristics and Remediation

When implementing a new failure mode:

1. **Create KB Heuristic**: Add to `build/dev/current/heuristics/gaius/<category>/<name>.md`
   - Symptom: Brief description
   - Cause: Why this happens
   - Observation: How to detect (with code)
   - Solution: How to fix (with `/health fix` command)

2. **Implement Fix Strategy**: Add to `src/gaius/health/service_fixes.py`
   - Create a `<Name>FixStrategy` class
   - Multi-step remediation with verification
   - Register in `SERVICE_STRATEGIES` dict

3. **Update Error Messages**: Reference the `/health fix` command in all error paths

### Health Commands

```bash
# Run diagnostics
uv run gaius-cli --cmd "/health"
uv run gaius-cli --cmd "/health <category>"

# Apply automated fix
uv run gaius-cli --cmd "/health fix <service>"

# Available services: engine, dataset, nifi, postgres, qdrant, minio, endpoints, evolution
```

### Testing for Fail-Fast Compliance

Before committing, verify:
1. No `fail_fast` parameters exist in the code
2. No placeholder/fallback code paths for required functionality
3. All error messages include remediation hints
4. New failure modes have KB heuristics and fix strategies

```bash
# Check for fallback patterns (should return nothing)
grep -rn "fail_fast\|SELENIUM_AVAILABLE\)" src/gaius/
grep -rn "240, 240, 240" src/gaius/  # Placeholder image color
```

## Pre-Commit Checklist

- Do not rely on fallbacks nor workarounds when testing; all functional aspects of new features must be verified directly.
- We do _not_ fall back to static test data in this application.
- Before making a commit ensure that all new functionality is available on the CLI and use the CLI to verify that everything is working.


## Testing Methodology

After every code change, re-test via CLI before declaring success.

The CLI is the product. Previous test outputs are invalidated by code changes. Don't reason from stale context - run the command again.

# After editing orchestrated.py:
# BAD: "The fix should work based on my analysis"
# GOOD: Actually run it
uv run gaius-cli --cmd "/evolve status" --format json

This isn't redundant tool use - it's verifying the product works.
- you can use devenv processes down and devenv processes up to control the gaius platform components

## RASE Metamodel (Rapid Agentic Systems Engineering)

The `gaius.rase` package implements a Python-native MBSE metamodel for verifiable agent training. **This is safety-critical infrastructure** - the verifier is a first-class artifact that must be maintained with the same rigor as production code.

### Package Structure

```
src/gaius/rase/
├── traceability.py       # TraceableId, DigitalThread (the spine)
├── ssm/                  # System State Model (NiFi as typed graph)
├── osm/                  # Operational Scenario Model (BDD scenarios)
├── uom/                  # UI Observation Model (SoM/ToM marks)
└── vm/                   # Verifier Model (requirements, oracle, rewards)
```

### Four Coupled Models - Maintain Coherence

The four models (OSM, SSM, UOM, VM) are **tightly coupled by design**. Changes to one model often require updates to others:

| If you change... | Also update... |
|------------------|----------------|
| SSM (NiFi state) | VM constraints that reference state structure |
| OSM (scenarios) | VM requirements derived from scenarios |
| UOM (marks/traces) | VM verification cases that consume traces |
| VM (verification) | Ensure reward strategies align with constraint semantics |

### TraceableId - The Digital Thread

`TraceableId` is the **traceability spine** linking all artifacts. Every model element should have a traceable ID:

```python
# BDD scenario
TraceableId.from_bdd("basic_flows", scenario="CreateFlow")
# → bdd://features/basic_flows#Scenario:CreateFlow

# NiFi element
TraceableId.from_nifi("root", processor_id="abc123")
# → nifi://root/processors/abc123

# Generated artifacts
TraceableId.generate(scheme="rase", prefix="verify")
# → rase://verify_<uuid>
```

**Rule**: When adding new model elements, always include a `TraceableId`. When creating relationships, use `DigitalThread` to capture provenance.

### Constraint Design Principles

SSM constraints (`src/gaius/rase/ssm/constraints.py`) follow these rules:

1. **Declarative**: Describe *what* to check, not *how*
2. **Composable**: Support `AllOf`, `AnyOf`, `Not` composition
3. **Debuggable**: Return `ConstraintResult` with rich failure messages
4. **Immutable**: Use `frozen=True` for safe concurrent use

When adding new constraints:
```python
class NewConstraint(Constraint):
    # Fields with Pydantic types
    some_param: str

    @property
    def name(self) -> str:
        return f"NewConstraint({self.some_param})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        # Return ConstraintResult.success() or .failure()
```

### Verification and Reward Invariants

The VM module (`src/gaius/rase/vm/`) implements RLVR (Reinforcement Learning with Verifiable Reward):

1. **VerdictKind**: Only four outcomes - PASS, FAIL, INCONCLUSIVE, ERROR
2. **Accuracy**: Always 0.0-1.0, representing proportion of constraints satisfied
3. **Reward strategies**: Must produce values suitable for RL training
   - `BinaryReward`: Sparse signal (0 or 1)
   - `GradedReward`: Dense signal with partial credit

**Rule**: The Oracle uses API (ground truth), never UI observations, for verification. UI traces are the *training target*, not the oracle.

### Testing RASE Changes

Before committing changes to `gaius.rase`:

```bash
# Verify all imports work
uv run python -c "from gaius.rase import *"

# Run comprehensive smoke test
uv run python -c "
from gaius.rase import (
    TraceableId, NiFiInstance, ProcessorGroup, Processor,
    Scenario, StepType, ScreenshotWithSoM, Mark,
    ScenarioRequirement, VerdictKind, compute_reward,
)
# ... test object creation and constraint evaluation
"
```

### SysML v2 Semantic Alignment

The RASE metamodel mirrors SysML v2 semantics without requiring external tooling:

| SysML v2 Concept | RASE Implementation |
|------------------|---------------------|
| `requirement def` | `Requirement`, `ScenarioRequirement` |
| `verification def` | `VerificationCase`, `APIVerificationCase` |
| `constraint def` | `Constraint` subclasses |
| `action def` | `StepDef` with `@given`, `@when`, `@then` |
| `part def` | `Processor`, `ProcessorGroup`, `NiFiInstance` |
| Human ID `<'scheme:path'>` | `TraceableId.uri` |

When extending the metamodel, consult `docs/scratch/2025-12-19/150000_rase_mbse_framework.md` for the formal SysML v2 mappings.