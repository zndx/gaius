# Cognition

The CognitionService generates autonomous "thoughts" by analyzing recent knowledge base activity. It runs as a set of scheduled background tasks within the engine, operating at three timescales.

## Scheduled Tasks

| Task | Interval | Scope |
|------|----------|-------|
| `cognition_cycle` | Every 4h | Detect patterns across recent KB entries |
| `self_observation` | Every 8h | Meta-cognitive reflection on thought quality and blind spots |
| `engine_audit` | Every 12h | System health patterns, resource utilization trends |

Each task is triggered by the engine's scheduler, not by external cron. Execution uses a reasoning endpoint via the standard inference pipeline.

## Thought Types

| Type | Description | Example |
|------|-------------|---------|
| `PATTERN` | Recurring themes across documents | "Three KB entries this week reference yield curve inversion" |
| `CONNECTION` | Cross-domain relationships | "The risk model's tail assumptions relate to the pension allocation strategy" |
| `CURIOSITY` | Questions warranting investigation | "No KB entries cover regulatory changes since Q3" |
| `SELF_OBSERVATION` | Meta-cognitive observations | "Recent thoughts are heavily weighted toward risk — expand analysis breadth" |

## How It Works

Each cognition cycle:

1. **Retrieve context** — Recent KB entries, existing thought chain, and current objectives
2. **Analyze** — LLM identifies patterns, connections, gaps, and meta-observations
3. **Generate thoughts** — Structured thought objects with type, content, and provenance
4. **Store** — Thoughts saved to the knowledge base as markdown files
5. **Chain** — Each thought records its trigger (scheduled, manual, or reactive) and the inputs that contributed to it

## Thought Chain

Thoughts form a linked provenance chain. Each thought references:
- Its **trigger** — what initiated the cycle (schedule, manual `/cognition` command, or reactive event)
- Its **inputs** — which KB entries and prior thoughts were analyzed
- Its **type** — categorization for downstream filtering

This creates an auditable trail of the system's reasoning over time. The `/thoughts` CLI command displays the chain, and the TUI surfaces recent thoughts in the info panel.

## Self-Observation

The self-observation cycle is distinct from regular cognition. It analyzes the *thought chain itself* rather than KB content:

- Are thoughts converging on one topic at the expense of others?
- Are CURIOSITY thoughts being addressed or accumulating?
- Is thought quality improving or degrading over time?

Self-observation generates `SELF_OBSERVATION` thoughts that feed back into subsequent cognition cycles, creating a reflective loop.

## CLI Commands

```bash
# Trigger cognition cycle manually
uv run gaius-cli --cmd "/cognition" --format json

# View recent thoughts
uv run gaius-cli --cmd "/thoughts" --format json

# Trigger self-observation
uv run gaius-cli --cmd "/self-observe" --format json

# Trigger engine audit
uv run gaius-cli --cmd "/engine-audit" --format json
```
