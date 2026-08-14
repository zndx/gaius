# Just Task Runner

Gaius uses [Just](https://github.com/casey/just) as its task runner, replacing devenv-tasks which had SQLite locking issues.

## Why Just

devenv-tasks 2.0.0 introduced a `tasks.db` SQLite file that deadlocks when tasks call `devenv up`. Just is a pure command runner with no state files — it reads `justfile` and executes recipes.

## Key Recipes

```bash
just --list              # Show all available recipes

# Core operations
just up                  # devenv up -d (product stack; systemd start uses this)
just down                # devenv processes down (this project only)
just restart-clean       # Full clean restart (preferred)
just proto-generate      # Regenerate gRPC protobuf bindings

# GPU management
just gpu-cleanup         # Kill orphan vLLM/CUDA processes
just gpu-deep-cleanup    # Aggressive GPU memory cleanup

# Documentation
just docs-build          # Build mdbook documentation

# Kubernetes
just k8s-cleanup         # Clean up K8s resources
```

## restart-clean

The most important recipe. Delegates to `scripts/restart-clean.sh`:

1. Stops all devenv processes
2. Kills stale vLLM/CUDA processes
3. Cleans up GPU memory
4. Strips DEVENV_* environment variables (uses `env -i`)
5. Restarts everything fresh

Warm start time: ~13 seconds (Nix cached, tasks.db warm).

```bash
just restart-clean
```

## Usage

Invoke from the devenv shell (or any shell with just + devenv):

```bash
devenv shell
just <recipe>
```

Recipes are defined in `justfile` at the project root.
