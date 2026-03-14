# The CLI

Gaius provides a non-interactive command-line interface through `gaius-cli`. It executes the same slash commands available in the TUI but returns structured output suitable for scripting, piping, and automation.

## Basic Usage

```bash
uv run gaius-cli --cmd "/command" --format json
```

The `--cmd` flag specifies the slash command to run (with or without the leading `/`). The `--format` flag controls output format -- `json` produces machine-readable output, while the default produces human-readable text.

## Examples

Check system health:

```bash
uv run gaius-cli --cmd "/health" --format json
```

Query GPU and endpoint status:

```bash
uv run gaius-cli --cmd "/gpu status" --format json
```

Check evolution state:

```bash
uv run gaius-cli --cmd "/evolve status" --format json
```

View the current application state:

```bash
uv run gaius-cli --cmd "/state" --format json
```

## Available Commands

Gaius has 63 slash commands covering health diagnostics, agent management, inference control, knowledge base operations, evolution, visualization, and observability. The full command reference is in the [CLI Commands](../reference/cli-commands.md) section.

Common command categories:

| Prefix | Domain | Example |
|--------|--------|---------|
| `/health` | System health | `/health`, `/health fix engine` |
| `/gpu` | GPU/endpoints | `/gpu status`, `/gpu cleanup` |
| `/evolve` | Agent evolution | `/evolve status`, `/evolve trigger` |
| `/kb` | Knowledge base | `/kb search <query>` |
| `/render` | Visualization | `/render cards` |
| `/observe` | Observability | `/observe metrics` |

## Connection to the Engine

The CLI connects to the same gRPC engine (port 50051) as the TUI. Both interfaces are thin clients that send commands to the engine and display results. If the engine is not running, the CLI will report a connection error -- start services with `devenv processes up -d` or `just restart-clean`.

## Next Steps

- **[Command Patterns](./cli-patterns.md)** -- JSON output, jq piping, polling techniques
- **[Scripting](./scripting.md)** -- using gaius-cli in shell scripts
