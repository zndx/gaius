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

End-to-end knowledge synthesis: define a topic, curate articles from the web (via Brave search), create cards with enriched metadata and topology features, render LuxCore visualizations, and publish a collection. Each run produces ~20 cards in under 2 minutes. The pipeline flows through NiFi ingestion → Metaflow processing → Nomic embedding → Qdrant indexing → PostgreSQL storage → R2 rendering.

### [Health Workflow](./workflow-health.md)

System diagnosis and remediation: run health checks, interpret Guru Meditation Codes, apply self-healing fixes, and monitor recovery. The Health Observer daemon runs continuously, scoring incidents via FMEA (Severity × Occurrence × Detection). When RPN exceeds threshold, it escalates to Mistral Vibe via the Agent Client Protocol.

### [Evolution Workflow](./workflow-evolution.md)

Agent improvement cycle: generate training tasks (from ideation, calibration, or held-out queries), trigger evaluation against a ground-truth oracle, compare candidates via the DaemonOracle, and promote successful agents. Evolution runs opportunistically during GPU idle periods (<30% utilization). Methods include APO and GEPA optimization with TIES/DARE parameter-space merging.

## Workflow Principles

**Self-healing first.** When something breaks, try `/health fix <service>` before manual intervention. The self-healing system learns from each invocation.

**Test via CLI.** After any code change or operation, verify the result with `gaius-cli`. Previous outputs are invalidated by changes -- always re-run the command.

**Fail fast.** Gaius surfaces errors immediately with actionable remediation paths. If a step fails, the error message tells you what to do next. There are no silent fallbacks.

**Observe, then act.** Use the OODA loop: observe system state (`/health`, `/gpu status`), orient by comparing overlays, decide on an action, then act. Do not skip the observation step.
