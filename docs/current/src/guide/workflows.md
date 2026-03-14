# Workflows

Gaius supports multi-step workflows that combine CLI commands, MCP tools, and TUI interactions. This section documents the most common patterns.

## What Is a Workflow?

A workflow is a sequence of operations that achieve a goal larger than any single command. For example, researching a topic involves creating KB entries, curating articles, generating cards, and publishing a collection. Each step uses different Gaius capabilities, and the output of one step feeds the next.

## Three Interaction Layers

Workflows can be executed through any combination of the three interfaces:

- **TUI**: interactive exploration, visual pattern recognition, manual curation
- **CLI**: scripted operations, batch processing, automated checks
- **MCP**: AI-assisted orchestration, where Claude Code drives multi-step sequences

The choice depends on the task. Health monitoring is best scripted via CLI. Research curation benefits from MCP-driven AI assistance. Spatial exploration requires the TUI.

## Common Workflows

### [Research Workflow](./workflow-research.md)

End-to-end knowledge synthesis: define a topic, curate articles from the web, create cards with enriched metadata, and publish a collection. This is the primary content pipeline.

### [Health Workflow](./workflow-health.md)

System diagnosis and remediation: run health checks, interpret failures, apply self-healing fixes, and monitor recovery. This workflow is critical for keeping the platform operational.

### [Evolution Workflow](./workflow-evolution.md)

Agent improvement cycle: check evolution status, generate training tasks, trigger evaluation, promote successful agents. This is how Gaius agents get better over time.

## Workflow Principles

**Self-healing first.** When something breaks, try `/health fix <service>` before manual intervention. The self-healing system learns from each invocation.

**Test via CLI.** After any code change or operation, verify the result with `gaius-cli`. Previous outputs are invalidated by changes -- always re-run the command.

**Fail fast.** Gaius surfaces errors immediately with actionable remediation paths. If a step fails, the error message tells you what to do next. There are no silent fallbacks.

**Observe, then act.** Use the OODA loop: observe system state (`/health`, `/gpu status`), orient by comparing overlays, decide on an action, then act. Do not skip the observation step.
