# Evolution Workflow

The evolution workflow improves Gaius agents over time through task ideation, training, evaluation, and promotion. This is a cycle that repeats as agents accumulate more data and experience.

## Overview

```
Status check --> Task ideation --> Training --> Evaluation --> Promotion
     ^                                                           |
     |___________________________________________________________|
```

Each cycle produces a new generation of agent versions. Successful versions are promoted to active status; underperformers are retained for comparison but not used in production.

## Step 1: Check Status

Before starting an evolution cycle, check the current state:

```bash
uv run gaius-cli --cmd "/evolve status" --format json
```

This shows the current generation number, active agents, evaluation state, and any capability gaps. Pay attention to:

- **Generation**: which cycle you are on
- **Active agents**: which agent versions are currently serving
- **Capability gaps**: areas where agents underperform

## Step 2: Task Ideation

Generate new training tasks based on identified capability gaps:

```bash
uv run gaius-cli --cmd "/evolve task ideation" --format json
```

The ideation process analyzes recent performance data and gap analysis to propose tasks that target specific weaknesses. Tasks are designed to push agents toward areas where they currently underperform.

## Step 3: Trigger Evolution

Start the evolution cycle. This runs training with the generated tasks and produces new agent versions:

```bash
uv run gaius-cli --cmd "/evolve trigger" --format json
```

Evolution requires healthy inference endpoints. Verify with:

```bash
uv run gaius-cli --cmd "/gpu status" --format json | \
    jq '.data.endpoints[] | {name, status}'
```

All endpoints should show `HEALTHY` before triggering evolution. If they do not, run `/health fix endpoints` first.

## Step 4: Evaluate

After training completes, evaluate the new agent versions against held-out test data:

```bash
# Check evaluation results
uv run gaius-cli --cmd "/evolve status" --format json | jq '.data.evaluation'

# View held-out statistics
uv run gaius-cli --cmd "/evolve held-out stats" --format json
```

Evaluation uses the RASE verification framework. Each agent version is scored on accuracy (0.0-1.0, proportion of constraints satisfied) and compared against previous versions.

## Step 5: Promote or Roll Back

If the new version outperforms the current active version, promote it:

```bash
# View the best version
uv run gaius-cli --cmd "/evolve best" --format json

# Promote (via MCP or direct command)
uv run gaius-cli --cmd "/evolve promote" --format json
```

If the new version underperforms, roll back to a known good version:

```bash
uv run gaius-cli --cmd "/evolve rollback" --format json
```

## Evolution Daemon

For continuous improvement, start the evolution daemon which runs cycles automatically:

```bash
# Start the daemon
uv run gaius-cli --cmd "/evolve daemon start" --format json

# Check daemon status
uv run gaius-cli --cmd "/evolve daemon status" --format json

# Stop the daemon
uv run gaius-cli --cmd "/evolve daemon stop" --format json
```

The daemon monitors capability gaps and triggers evolution cycles when thresholds are exceeded.

## Monitoring Evolution Trends

Track improvement over time:

```bash
uv run gaius-cli --cmd "/evolve trend" --format json
```

This shows how agent performance has changed across generations. Look for:

- **Upward trend**: agents are improving, the evolution cycle is working
- **Plateau**: training tasks may need diversification, or capability limits have been reached
- **Regression**: roll back to a previous version and investigate

## Model Merging

When multiple specialized agent versions exist, model merging can combine their strengths:

```bash
# View merge candidates
uv run gaius-cli --cmd "/evolve merge candidates" --format json

# Trigger a merge
uv run gaius-cli --cmd "/evolve merge" --format json

# View lineage
uv run gaius-cli --cmd "/evolve lineage" --format json
```

Model lineage tracking records the ancestry of each merged version, enabling traceability from the final model back to its training data and parent versions.
