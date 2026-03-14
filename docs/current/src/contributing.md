# Contributing

Gaius is an experiment in augmented cognition. Contributions that advance this vision are welcome.

## Development Setup

```bash
# Clone and enter
git clone https://github.com/zndx/gaius.git
cd gaius

# Start devenv (provides all system dependencies)
devenv shell

# Install Python dependencies
uv sync

# Start all platform components
devenv processes up

# Or use a clean restart
just restart-clean

# Run the TUI
uv run gaius

# Run the CLI
uv run gaius-cli --cmd "/health" --format json
```

## Project Structure

```
gaius/
├── src/gaius/          # Python source (26 packages)
│   ├── app.py          # TUI application
│   ├── cli.py          # Non-interactive CLI
│   ├── mcp_server.py   # MCP server (163 tools)
│   ├── engine/         # gRPC engine (37 services)
│   ├── health/         # Self-healing infrastructure
│   ├── agents/         # Agent system
│   └── ...
├── scripts/
│   ├── processes/      # Process startup scripts
│   └── lib/            # Shared helpers
├── docs/current/       # mdbook documentation
├── config/             # HOCON configuration
├── justfile            # Task runner recipes
├── devenv.nix          # Development environment
├── pyproject.toml      # Python dependencies
└── CLAUDE.md           # Development guidelines
```

## Development Workflow

### Testing Changes

The CLI is the product. After every code change, verify via CLI:

```bash
# After editing code — always re-test
uv run gaius-cli --cmd "/health" --format json
```

Previous test outputs are invalidated by code changes. Don't reason from stale context — run the command again.

### Key Recipes

```bash
just --list              # Show all available tasks
just restart-clean       # Full clean restart
just proto-generate      # Regenerate gRPC bindings
just gpu-cleanup         # Clean up GPU processes
just docs-build          # Build documentation
```

## Design Principles

When contributing, these principles are mandatory:

1. **Fail-fast**: Errors surface immediately with guru codes and remediation hints. No silent degradation.
2. **Engine-first**: Business logic belongs in engine services, not in interfaces.
3. **Self-healing first**: Prefer `/health fix` over manual remediation.
4. **Keyboard-first**: Every operation available via keyboard.
5. **CLI verification**: All new features must be testable via `gaius-cli`.

## Code Style

- Python 3.12+ features welcome
- Type hints for public interfaces
- Local imports inside functions for lazy loading in service modules
- Use `from gaius.core.config import get_database_url` for DB URL (never hardcode)

## Commit Messages

Use conventional commit style:
```
feat: add temporal overlay mode
fix: correct grid boundary check
docs: expand TDA explanation
refactor: simplify swarm initialization
```

## Pull Request Process

1. Create a feature branch
2. Make changes with clear commits
3. Verify via CLI: `uv run gaius-cli --cmd "/health" --format json`
4. Ensure `cd docs/current && mdbook build` succeeds if docs changed
5. Submit PR with description of changes
