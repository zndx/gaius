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