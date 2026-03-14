# Architecture Decision Records

Key architectural decisions that shaped the system.

## ADR-001: Engine-First Architecture

**Context**: Business logic was scattered across TUI, CLI, and utility scripts, causing duplication and inconsistency.

**Decision**: Centralize all business logic in the gRPC engine. TUI, CLI, and MCP become thin clients.

**Consequences**: Single source of truth for all operations. Engine manages GPU resources centrally. All interfaces get consistent behavior automatically.

## ADR-002: Just Over devenv-tasks

**Context**: devenv-tasks 2.0.0 introduced SQLite locking on `tasks.db` that deadlocks when tasks call `devenv up`.

**Decision**: Migrate from devenv-tasks to Just as the task runner.

**Consequences**: Pure command runner with no state files. Recipes defined in `justfile`. No locking issues. `scripts/restart-clean.sh` still does actual work; Just recipe delegates to it.

## ADR-003: Fail-Fast as Iron-Clad Principle

**Context**: Silent degradation hid problems until they became critical.

**Decision**: All code must surface errors immediately with guru meditation codes and remediation paths. No silent fallbacks.

**Consequences**: Higher initial friction (more explicit error handling) but dramatically faster diagnosis and resolution. Self-healing system built on reliable error detection.

## ADR-004: FMEA for Health Monitoring

**Context**: Simple severity classifications don't capture risk adequately — a rare but invisible failure is more dangerous than a frequent but obvious one.

**Decision**: Adopt FMEA (Failure Mode and Effects Analysis) with RPN scoring for health monitoring.

**Consequences**: Quantitative risk assessment (S x O x D). Tiered remediation based on risk level. Adaptive learning from outcomes.

## ADR-005: LuxCore Over Blender for Visualization

**Context**: Blender's Cycles renderer couldn't render glass convincingly (opaque white blobs).

**Decision**: Use LuxCore unbiased path tracer for card visualization, initially via PyPI, later from source for GPU acceleration.

**Consequences**: Physically accurate glass rendering. GPU-accelerated via PATHOCL engine with CUDA. More complex build process but superior visual quality.

## ADR-006: Process Scripts Over Inline Nix Bash

**Context**: `devenv.nix` contained inline bash blocks that were hard to debug and test.

**Decision**: Move all process startup bash to `scripts/processes/*.sh` with shared helpers. `devenv.nix` becomes a pure service declaration file with one-liner exec blocks.

**Consequences**: Scripts are independently testable. Shared helpers eliminate duplication. Nix store paths passed as environment variables.

## Adding New ADRs

When making significant architectural decisions:

1. Add an entry here with Context, Decision, and Consequences
2. Reference the ADR in relevant code comments
3. Update CLAUDE.md if the decision affects development workflow
