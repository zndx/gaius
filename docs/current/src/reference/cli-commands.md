# CLI Commands

63 slash commands are available in both the TUI and CLI interfaces. Commands are executed via:

```bash
# TUI: press / then type command
/health

# CLI: use --cmd flag
uv run gaius-cli --cmd "/health" --format json
```

## Command Categories

### Health & Diagnostics

| Command | Description |
|---------|-------------|
| `/health` | Run all health checks |
| `/health <category>` | Run checks for category (gpu, endpoints, infrastructure) |
| `/health fix <service>` | Apply automated fix strategy |
| `/health observer` | Health Observer daemon status |
| `/health incidents` | List active incidents |
| `/fmea` | FMEA summary with RPN scores |
| `/fmea catalog` | List all failure modes |
| `/fmea detail <id>` | Failure mode details |

### GPU & Endpoints

| Command | Description |
|---------|-------------|
| `/gpu status` | Endpoint and GPU status |
| `/gpu health` | GPU memory, temperature, utilization |

### Agents & Evolution

| Command | Description |
|---------|-------------|
| `/swarm` | Run swarm analysis |
| `/evolve status` | Evolution daemon status |
| `/evolve trigger` | Trigger evolution cycle |
| `/cognition` | Trigger cognition cycle |
| `/thoughts` | View recent thoughts |
| `/sitrep` | Situational report |
| `/theta consolidate` | Run theta consolidation |

### Knowledge Base

| Command | Description |
|---------|-------------|
| `/search <query>` | Search knowledge base |
| `/kb list` | List KB entries |
| `/kb create` | Create KB entry |

### System

| Command | Description |
|---------|-------------|
| `/state` | Current application state |
| `/render` | Render card visualizations |
| `/xai budget` | XAI API budget status |

> **Note**: This is a representative subset. Run `/help` in the TUI for the complete list, or see the dispatch table in `src/gaius/cli.py`.
