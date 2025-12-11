# Co-Creation with Code Agents

Gaius represents a novel architectural pattern: an application co-created with AI code agents, where the development process itself shapes the system's design.

## The Co-Creation Paradigm

Traditional software development follows a clear separation: humans design, humans implement, humans document. Gaius challenges this by integrating Claude Code (powered by Claude Opus 4.5) as a first-class development partner.

This isn't "AI-assisted coding" in the conventional sense. It's a symbiotic development process where:

1. **The human provides vision and judgment** — strategic direction, quality assessment, architectural taste
2. **The code agent provides implementation velocity** — exploring codebases, generating code, maintaining consistency
3. **The system evolves through dialogue** — features emerge from conversation, not specification documents

### Implications for Architecture

When an AI agent is a development partner, certain architectural choices become natural:

**Interface Parity**: CLI, TUI, and MCP interfaces must provide equivalent functionality. Why? Because the code agent (via MCP) needs access to the same operations the human uses (via TUI). Parity isn't a nice-to-have; it's essential for the agent to effectively participate in development and testing.

**Living Documentation in the KB**: Command references live in the Knowledge Base (`[[current/commands/]]`), not frozen in mdbook. The command set evolves as the agent and human add features together. Static documentation would be perpetually stale.

**Self-Describing Systems**: The MCP tools are the API. The CLI commands are the operations. When these are well-named and well-documented, the code agent can discover and use them without additional instruction.

## The Knowledge Base as Shared Memory

A key insight: the KB serves as shared context between human and agent across sessions.

### What Belongs in the KB vs. mdbook

| KB (`build/dev/`) | mdbook (`docs/`) |
|-------------------|------------------|
| Command reference (evolving) | Design philosophy (stable) |
| Current research threads | Architectural foundations |
| Session notes and decisions | Core concepts |
| Feature-specific documentation | User guides |
| Agent-generated analysis | Contributing guidelines |

The distinction: **KB content may change between sessions** as features evolve. **mdbook content captures enduring principles** that guide the evolution.

### Example: The Commands Directory

The command reference in `[[current/commands/]]` was created during a session where we:

1. Audited all commands across CLI, TUI, and MCP
2. Identified parity gaps
3. Documented each interface comprehensively

This documentation now serves multiple purposes:
- **For humans**: Quick reference, training material
- **For code agents**: Discovery of available operations
- **For development**: Gap analysis, parity tracking

If we added the command reference to mdbook, it would be outdated within days. In the KB, it can evolve with the system.

## BDD as Collaborative Specification

Behavior-Driven Development (BDD) takes on new significance in co-created systems.

### Feature Files as Contracts

Gherkin feature files (`features/*.feature`) serve as:

1. **Executable specifications** — Tests that verify behavior
2. **Agent-readable requirements** — Clear, structured descriptions the code agent can understand
3. **Living documentation** — Always synchronized with actual behavior

```gherkin
Feature: Wiki Link Resolution
  As a knowledge worker
  I want broken wiki links to resolve via search
  So that the knowledge graph grows organically

  Scenario: Selecting an unresolved wiki link
    Given a file "test.md" containing "[[nonexistent-topic]]"
    When I select the broken link in the graph panel
    Then a search runs for "nonexistent-topic"
    And a new zettelkasten note is created
    And the original link is updated to point to the new note
```

This scenario was implemented in a single session. The code agent:
- Read the feature file to understand requirements
- Implemented the feature across multiple files
- Created tests to verify the behavior

### Scenarios as Design Discussions

BDD scenarios often emerge from human-agent dialogue:

> **Human**: "When I click a broken link, instead of an error, can it search and create a note?"
>
> **Agent**: "So the flow would be: detect missing target → run search → synthesize note → update original link?"
>
> **Human**: "Yes, and add a backlink from the new note to the origin."

This conversation becomes a scenario. The scenario becomes a test. The test drives the implementation.

## Interface Parity as Architectural Principle

The three interfaces serve different users:

| Interface | Primary User | Interaction Pattern |
|-----------|--------------|---------------------|
| **TUI** | Human (interactive) | Real-time visualization, keyboard navigation |
| **CLI** | Human (scripting), CI/CD | JSON output, automation |
| **MCP** | Code agents, integrations | Structured tool calls |

### Why Parity Matters

When interfaces drift apart:
- The code agent can't test what the human experiences
- Automation scripts break when TUI adds features
- Documentation fragments across interfaces

Gaius addresses this through:

1. **Shared core functions** — CLI and TUI call the same underlying methods
2. **MCP as the comprehensive API** — 80+ tools covering all operations
3. **Regular parity audits** — Tracking gaps in `[[current/commands/index]]`

### The Parity Matrix

The command coverage matrix explicitly tracks which operations are available where:

```
| Command      | CLI | TUI | MCP |
|--------------|-----|-----|-----|
| /search      |  ✓  |  ✓  |  ✓  |  ← Full parity
| /model add   |  ✓  |  -  |  ✓  |  ← TUI gap (priority)
| /init        |  -  |  ✓  |  -  |  ← TUI-specific (OK)
```

This matrix is itself a development artifact that guides prioritization.

## Practical Patterns

### Pattern 1: Agent-Discoverable Operations

Name commands and tools descriptively:
- `scheduler_health_check` not `shc`
- `/evolve trigger` not `/evo t`

The code agent reads these names. Clear naming reduces confusion.

### Pattern 2: JSON-First CLI

CLI commands return structured JSON by default:
```bash
uv run gaius-cli --cmd "/state" --format json
```

This enables:
- Agent parsing of command output
- Scripted verification of behavior
- Pipeline integration

### Pattern 3: Incremental Documentation

Don't write comprehensive documentation upfront. Let it emerge:

1. Implement feature with agent
2. Agent documents as it implements
3. Human reviews and refines
4. Documentation evolves with feature

### Pattern 4: Session Handoff

The KB preserves context across sessions:
- `[[scratch/YYYY-MM-DD/]]` — Daily working notes
- `[[current/commands/]]` — Living reference
- Research threads — Ongoing investigations

When a new session starts, the agent can read recent KB entries to resume context.

## The Meta-Principle

**Systems designed for co-creation with code agents are inherently more maintainable.**

Why? Because the requirements for agent collaboration—clear interfaces, structured data, living documentation, testable behavior—are the same requirements for long-term maintainability.

Designing for an AI collaborator forces us to:
- Make implicit knowledge explicit
- Structure operations consistently
- Document as we build
- Test what we document

These are good practices regardless of whether an agent is involved. The agent just makes them essential.

## Future Directions

### Agent-Initiated Evolution

Currently, the human initiates feature development. Future systems might:
- Have the agent propose features based on usage patterns
- Automatically generate BDD scenarios from user feedback
- Self-document new capabilities as they're added

### Multi-Agent Development

Gaius already uses multi-agent swarms for analysis. The same pattern could apply to development:
- Architect agent proposes structure
- Implementation agent writes code
- Critic agent reviews
- Documentation agent updates KB

### Adaptive Interfaces

If the agent tracks which operations are used most, it could:
- Suggest adding frequently-used MCP tools to TUI
- Identify commands that should be automated
- Propose interface simplifications

## Conclusion

Gaius isn't just a tool for augmented cognition—it's a case study in augmented development. The co-creation paradigm, where human vision and AI implementation velocity combine, produces systems that are:

- **More consistent** — The agent enforces patterns across the codebase
- **Better documented** — Documentation emerges from the development dialogue
- **More testable** — BDD scenarios are natural outputs of requirement discussions
- **Easier to maintain** — Clear interfaces required for agent collaboration benefit all maintainers

The KB as shared memory, interface parity as principle, and BDD as collaborative specification—these patterns aren't specific to Gaius. They're applicable to any system designed for human-AI co-creation.

The future of software development isn't human OR machine. It's human AND machine, each contributing their strengths to create systems neither could build alone.
