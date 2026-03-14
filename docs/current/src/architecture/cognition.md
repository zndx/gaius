# Cognition

The CognitionService generates autonomous "thoughts" by analyzing recent knowledge base activity. It runs as a scheduled background task within the engine.

## Scheduled Tasks

| Task | Interval | Purpose |
|------|----------|---------|
| `cognition_cycle` | Every 4h | Detect patterns in recent KB activity |
| `self_observation` | Every 8h | Meta-cognitive reflection on thought patterns |
| `engine_audit` | Every 12h | System health and resource analysis |

## Thought Types

| Type | Description |
|------|-------------|
| `PATTERN` | Recurring themes across documents |
| `CONNECTION` | Cross-domain relationships discovered |
| `CURIOSITY` | Questions warranting investigation |
| `SELF_OBSERVATION` | Meta-cognitive observations about thought quality |

## How It Works

Each cognition cycle:

1. Retrieves recent KB entries and thought history
2. Analyzes for patterns, connections, and gaps
3. Generates thoughts using a reasoning endpoint
4. Stores thoughts in the knowledge base
5. Records in the thought chain for provenance

## CLI Commands

```bash
# Trigger cognition cycle manually
uv run gaius-cli --cmd "/cognition" --format json

# View recent thoughts
uv run gaius-cli --cmd "/thoughts" --format json

# Trigger self-observation
uv run gaius-cli --cmd "/self-observe" --format json
```

## Thought Chain

Thoughts are linked in a chain with provenance tracking. Each thought references its trigger (scheduled, manual, or reactive) and the inputs that contributed to it. This creates an auditable trail of the system's reasoning.
