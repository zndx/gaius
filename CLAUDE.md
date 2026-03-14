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

# Engine management
just restart-clean               # Full clean restart (preferred)
just --list                      # Show all available tasks
devenv processes up              # Start all platform components
devenv processes down            # Stop all platform components

# Check endpoint status
uv run gaius-cli --cmd "/gpu status" --format json

# Build documentation
just docs-build
```

## Module Structure

```
src/gaius/
├── app.py              # Main TUI application (GaiusApp)
├── cli.py              # Non-interactive CLI
├── __main__.py         # Module entry point
├── core/
│   └── state.py        # AppState, ViewMode, OverlayMode
├── engine/             # gRPC Engine (central nervous system)
│   ├── server.py       # Main engine server
│   ├── proto/          # Protobuf definitions
│   ├── generated/      # Generated gRPC bindings
│   ├── grpc/           # gRPC servicers
│   ├── services/       # Core services (orchestrator, cognition, etc.)
│   └── backends/       # vLLM controller, inference backends
├── health/             # Self-healing infrastructure
│   ├── observe.py      # HealthObserver daemon
│   └── service_fixes.py # Automated remediation strategies
├── acp/                # Agent Client Protocol (Claude Code integration)
├── rase/               # RASE metamodel (agent training verification)
├── widgets/            # TUI widgets
│   ├── grid.py         # MainGrid (19×19)
│   ├── minigrid.py     # MiniGrid (9×9 orthographic views)
│   ├── filetree.py     # FileTree (KB navigation)
│   ├── content.py      # ContentPanel (right panel)
│   └── command.py      # CommandInput (bottom)
└── commands/           # Slash command implementations

scripts/
├── lib/
│   ├── process-helpers.sh  # Shared: banner, check_disabled, wait_for_postgres, wait_for_aeron
│   └── gpu-helpers.sh      # Shared: gpu_cleanup (used by engine + justfile)
├── processes/              # Process startup scripts (exec'd by devenv process-compose)
│   ├── aeron-driver.sh
│   ├── gaius-engine.sh
│   ├── gaius-worker.sh
│   ├── metabase.sh
│   ├── metaflow-bootstrap.sh
│   ├── metaflow-db-setup.sh
│   ├── metaflow-port-forwards.sh
│   ├── metaflow-ui.sh
│   └── nifi.sh
└── restart-clean.sh        # Full cleanup and fresh restart
```

## Process Script Architecture

`devenv.nix` is a **pure service declaration file** — it defines packages, env vars, service configs, and process dependency graphs. All process startup bash lives in `scripts/processes/*.sh`.

### devenv.nix → script pattern

Each process block in devenv.nix is a one-liner that execs the script:

```nix
processes.gaius-engine = {
  exec = ''
    exec ${config.devenv.root}/scripts/processes/gaius-engine.sh
  '';
  process-compose = {
    depends_on.aeron-driver.condition = "process_started";
  };
};
```

When a script needs Nix store paths (like `${pkgs.nifi}`), they're passed as env vars:

```nix
processes.nifi = {
  exec = ''
    export NIFI_PACKAGE="${pkgs.nifi}"
    export DEVENV_ROOT="${config.devenv.root}"
    exec ${config.devenv.root}/scripts/processes/nifi.sh
  '';
};
```

### KUBECONFIG in process scripts

`enterShell` only runs for interactive shells, not process-compose processes. Scripts that need kubectl must set KUBECONFIG unconditionally from `$HOME`:

```bash
export KUBECONFIG="$HOME/.config/kube/rke2.yaml"
```

Do NOT use fallback syntax (`${KUBECONFIG:-...}`) — the system KUBECONFIG may be set to a root-owned path that's unreadable.

### Adding a new process

1. Create `scripts/processes/<name>.sh` with `#!/usr/bin/env bash`, `set -euo pipefail`
2. Source helpers: `source "$SCRIPT_DIR/../lib/process-helpers.sh"`
3. Add process block to `devenv.nix` with one-liner exec
4. Pass any Nix-only values as env vars in the exec block

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

## Database

**IMPORTANT**: The PostgreSQL database name is `zndx_gaius`, NOT `gaius`.

```bash
# Correct database connection
PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius

# WRONG - will fail with "database does not exist"
# psql -d gaius  # <-- DO NOT USE
```

Connection parameters:
- Host: `localhost`
- Port: `5444`
- Database: `zndx_gaius`
- User: `gaius`
- Password: `gaius`

Full connection URL: `postgres://gaius:gaius@localhost:5444/zndx_gaius?sslmode=disable`

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
    "  Or:  restart-clean"
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

### Self-Healing First (IMPORTANT)

**Always prefer `/health fix` over manual remediation.** When encountering unhealthy services:

1. **Run `/health fix <service>`** - Let Gaius attempt self-healing first
2. **Only use manual commands** (`restart-clean`, etc.) if self-healing fails
3. **Document failures** - If `/health fix` can't remediate, that's a bug to fix

This principle ensures:
- The self-healing system gets exercised and improved
- Manual interventions are documented as capability gaps
- Gaius becomes more autonomous over time

### Fail Open for Observability

**Fail Open is the counterpart to Fail Fast for observability code.** When filtering or displaying health state:

1. **Filter OUT, not IN**: When showing active incidents, filter OUT known terminal states (`resolved`) rather than filtering IN known active states. Unknown states are surfaced for investigation.

2. **Unknown States are Visible**: Any state not in the "terminal" list is displayed. This ensures new or unexpected states don't silently disappear.

3. **Bridle Assumptions**: Matching against an exhaustive list of "good" values is fragile. Only match against the small set of terminal states.

**Example - Fail Open for Incidents**:
```python
# BAD: Filtering IN known active states (brittle)
active = [i for i in incidents if i.status in ("active", "healing", "recovering")]

# GOOD: Filtering OUT known terminal states (Fail Open)
active = [i for i in incidents if i.status != "resolved"]
```

This principle aligns with the OODA loop interaction pattern:
- Observe: Surface all relevant state
- Orient: Let the user interpret unusual states
- Decide: User determines if intervention needed
- Act: User takes action with full visibility

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

```bash
# After editing code:
# BAD: "The fix should work based on my analysis"
# GOOD: Actually run it
uv run gaius-cli --cmd "/evolve status" --format json
```

This isn't redundant tool use - it's verifying the product works.

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

## ACP Integration (Agent Client Protocol)

The `gaius.acp` package provides integration with Claude Code for autonomous health maintenance. **This is security-critical infrastructure** with mandatory multi-layer protections.

### Architecture Overview

```
HealthObserver → detects incident → exceeds FMEA threshold?
       ↓                                    ↓ Yes
  Log & self-heal ←── No ──┘     Escalate via ACP → Claude Code
                                            ↓
                              Claude Code analyzes via MCP tools
                                            ↓
                              Implements /health fix enhancement
                                            ↓
                              Commits to acp-claude/health-fix branch
```

**Key Insight**: ACP-Claude is a *meta-level maintainer*. It evolves the `/health fix` framework itself, teaching Gaius to heal autonomously.

### Security Model (MANDATORY - No Bypass)

Security verification is **mandatory and cannot be disabled**. This is by design to prevent generated code from bypassing security checks.

#### Multi-Layer Protection

| Layer | Check | Purpose |
|-------|-------|---------|
| 0 | Format validation | Reject malformed repo names |
| 1 | HOCON allowlist | Explicit repo patterns only |
| 2 | Visibility verification | Must be private (via `gh api`) |
| 3 | Content sanitization | Redact secrets, strip injection |

#### Configuration

Security is configured via HOCON at `~/.config/gaius/acp.conf`:

```hocon
acp {
  github {
    # Explicit allowlist - only these repos can be used
    allowed_repos = ["zndx/gaius-acp"]

    # MANDATORY: repos must be private
    require_private = true

    # Re-verify visibility on each operation
    verify_on_each_operation = true

    # Cache visibility for 5 minutes
    cache_visibility_seconds = 300
  }
}
```

### Attack Vectors Mitigated

| Attack | Mitigation |
|--------|------------|
| Info leak via public repo | Layer 2: visibility verification |
| Prompt injection from issues | Layer 1: explicit allowlist |
| Credential exposure in issues | Layer 3: content sanitization |
| Visibility change attack | Re-verify on each operation |
| Generated code bypass | Security is mandatory, no option to disable |

### Content Sanitization

Before including content in GitHub issues, the following are automatically redacted:

- API keys (Anthropic, OpenAI, AWS patterns)
- GitHub tokens (PAT, OAuth, App tokens)
- Prompt injection markers

```python
from gaius.acp import sanitize_issue_content

# Automatically redacts secrets and strips injection attempts
safe_content = sanitize_issue_content(raw_content)
```

### Cadence Policy

To prevent runaway automation:

- Max 3 GitHub issues per 24 hours
- Min 5 minutes between restart attempts
- Max 3 restarts per endpoint per hour
- All changes on `acp-claude/health-fix` branch for human review

### Guru Meditation Codes

| Code | Description |
|------|-------------|
| `#ACP.00000001.CONNFAIL` | Connection to Claude Code failed |
| `#ACP.00000002.TIMEOUT` | Connection timeout |
| `#ACP.00000003.NOTCONN` | Operation on disconnected client |
| `#ACP.00000004.PROMPTTIMEOUT` | Prompt response timeout |
| `#ACP.00000005.PROMPTFAIL` | Prompt execution failed |
| `#ACP.00000010.GHSECFAIL` | GitHub security check failed |
| `#ACP.SEC.00000002.NOTALLOWED` | Repo not in allowlist |
| `#ACP.SEC.00000003.NOTPRIVATE` | Repo not private |
| `#ACP.SEC.00000004.NOTCONFIGURED` | No repos configured |

### Development Workflow

All ACP-related code changes should go through human review:

```bash
# Switch to the ACP development branch
git checkout acp-claude/health-fix

# Test ACP connection
uv run python -c "
import asyncio
from gaius.acp import GaiusACPClient

async def test():
    async with GaiusACPClient() as client:
        print(f'Connected: {client.session_id}')

asyncio.run(test())
"

# After testing, submit for human review before merging to trunk
```

### Integration with Health System

The HealthObserver daemon (`gaius.health.observe`) automatically escalates to ACP when:

1. An incident exceeds the configured FMEA RPN threshold
2. Local remediation has failed
3. The incident fingerprint is not in cooldown

```python
# From health/observe.py - escalation path
if incident.rpn_score > self.escalation_threshold:
    await self._escalate_to_acp(incident)
```

See [`src/gaius/acp/README.md`](src/gaius/acp/README.md) for complete API documentation.

## gRPC Proto Change Management

The Gaius Engine exposes a gRPC API defined in protobuf. Changes to the proto require a specific workflow.

### Key Files

| File | Purpose |
|------|---------|
| `src/gaius/engine/proto/gaius_service.proto` | Proto definitions (source of truth) |
| `src/gaius/engine/proto/gaius_service_pb2.py` | Generated Python bindings |
| `src/gaius/engine/proto/gaius_service_pb2_grpc.py` | Generated gRPC stubs |
| `src/gaius/engine/generated/__init__.py` | Re-exports for clean imports |
| `src/gaius/engine/grpc/servicers/gaius_servicer.py` | Server-side implementation |

### Proto Change Workflow

1. **Edit the proto file** - Append new enum values (don't renumber for wire compatibility)

2. **Regenerate bindings**:
   ```bash
   just proto-generate
   ```

3. **Update generated exports** - Add new symbols to `src/gaius/engine/generated/__init__.py`:
   - Add to the import block
   - Add to the `__all__` list
   - **Critical**: If you skip this, the engine fails with import errors

4. **Update internal enums** - If there's a parallel Python enum (e.g., in `vllm_controller.py`), sync it

5. **Update status mappings** - Add string-to-proto mappings in the servicer's `_STATUS_MAP`

6. **Verify import before restart**:
   ```bash
   uv run python -c "from gaius.engine.generated import NEW_SYMBOL; print('OK')"
   ```

7. **Restart and test**:
   ```bash
   restart-clean
   ```

### Endpoint Status Values

```
PROCESS_STATUS_UNSPECIFIED = 0
PROCESS_STATUS_STOPPED = 1
PROCESS_STATUS_STARTING = 2
PROCESS_STATUS_HEALTHY = 3
PROCESS_STATUS_UNHEALTHY = 4
PROCESS_STATUS_STOPPING = 5
PROCESS_STATUS_FAILED = 6
PROCESS_STATUS_PENDING = 7   # Queued for startup, waiting in line
```

State transitions during startup: `PENDING → STARTING → HEALTHY`

### Testing gRPC Features

**gRPC reflection is not enabled**, so `grpcurl` cannot discover services. Use the CLI instead:

```bash
# Check endpoint status
uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[] | {name, status}'

# Poll during restart to see transitions
for i in {1..15}; do
    sleep 10
    uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[] | {name, status}'
done
```

### Restart and Monitoring

```bash
# Full clean restart (stops everything, cleans up, restarts)
just restart-clean

# Check if gRPC port is listening
nc -zv localhost 50051

# Watch engine logs
tail -f .devenv/processes.log | grep gaius-engine
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Engine fails to start | Missing export in `__init__.py` | Add symbol to imports and `__all__` |
| Port 50051 not listening | gRPC server didn't initialize | Check logs for import errors |
| Status shows wrong value | Missing status mapping | Add to `_STATUS_MAP` |
| `just restart-clean` times out | Engine startup slow | Endpoints still loading, check `/gpu status` |