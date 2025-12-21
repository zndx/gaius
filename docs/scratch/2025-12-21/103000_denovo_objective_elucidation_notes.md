# De Novo Objective Elucidation - Analysis Notes

**Date**: 2025-12-21
**Source**: `research-synthesis-verification_abstract-extension.md`
**Status**: Synthesis of GPT-5.2 extension with RASE integration analysis

---

## Core Insight

The document proposes a paradigm shift: **objectives are not external artifacts that drift out of sync—they are living, validated projections of the KB onto the operational surface**.

This aligns perfectly with RASE's intrinsic verifiability principle but extends it further:
- RASE: The operational environment is the verification oracle
- De Novo OE: The operational environment *generates* the objectives themselves

---

## Key Concepts

### 1. Objective as Verifiable Contract

An objective binds together five elements:

| Element | Description | RASE Analog |
|---------|-------------|-------------|
| Intent | What we want | Scenario description |
| Context | Where/why it matters | Domain constraints |
| Affordances | What system can do | Available tools/commands |
| Verification | How we know success | Oracle + constraints |
| Provenance | Where evidence lives | TraceableId + DigitalThread |

This is essentially a ScenarioRequirement with explicit affordance and storage metadata.

### 2. Progressive Disclosure Pattern

Borrowed from Claude Code Skills:
- Frontmatter is cheap (metadata first)
- Body is expensive (pulled on demand)
- Execution affordances are explicitly constrained

This maps to how we should structure RASE verification cases:
- Quick schema validation (syntactic gates)
- Deeper constraint checking (semantic gates)
- Full execution with traces (empirical gates)

### 3. Gate Hierarchy

Three levels of objective validation:

**Syntactic Gates** (cheap, fast):
- Document parses
- Schema valid
- References resolve

**Semantic Gates** (medium cost):
- Non-trivial (not "improve quality")
- Decomposable (has stages)
- Actionable (names affordances)

**Empirical Gates** (expensive, definitive):
- Tests pass
- Metrics achieved
- Artifacts match expectations

This is exactly the GradedReward pattern from RASE—partial credit for partial success.

### 4. The In Situ Discovery Loop

1. **Snapshot context** - KB + tools + recent runs
2. **Propose candidates** - Cluster themes → objective candidates
3. **Compile to docs** - Enforce schema, ensure verifiability
4. **Execute verification** - Smallest proof first
5. **Promote/demote** - Gates pass → active; fail → blocked + subobjectives
6. **Regenerate affordances** - Failures spawn new commands/topics

This IS the RASE loop, but applied recursively to objective generation itself.

---

## Synthesis: De Novo OE + RASE

The document essentially describes **meta-RASE**:
- RASE trains agents on intrinsically verifiable tasks
- De Novo OE generates those tasks from the KB itself

### Unified Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    DE NOVO OBJECTIVE ELUCIDATION                │
│                                                                 │
│  KB State + Operational Surface + Gap Analysis                  │
│                           │                                     │
│                           ▼                                     │
│              ┌─────────────────────────┐                       │
│              │  Objective Candidates   │                       │
│              │  (frontmatter + gates)  │                       │
│              └───────────┬─────────────┘                       │
│                          │                                     │
│         ┌────────────────┼────────────────┐                   │
│         ▼                ▼                ▼                   │
│    Syntactic         Semantic         Empirical               │
│      Gates            Gates            Gates                  │
│    (parse)          (resolve)        (execute)               │
│         │                │                │                   │
│         └────────────────┴────────────────┘                   │
│                          │                                     │
│                          ▼                                     │
│              ┌─────────────────────────┐                       │
│              │  Validated Objectives   │                       │
│              │  [[current/objectives/]]│                       │
│              └───────────┬─────────────┘                       │
│                          │                                     │
└──────────────────────────┼──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                         RASE LOOP                               │
│                                                                 │
│   Objective → BDD Scenario → Execute → Verify → Train          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### KB Layout (Proposed)

```
current/
├── objectives/
│   ├── <zettel-id>.md           # Objective definition
│   ├── evidence/
│   │   └── <zettel-id>/
│   │       └── <run-id>.md      # Thin manifest → hx pointers
│   └── templates/               # Reusable skeletons
├── commands/
│   └── <cmd-name>.md            # Skill-format command definitions
└── ontology/
    ├── <domain>.owl             # Validated ontologies
    └── topics/
        └── <concept>.md         # High-value verbalized concepts
```

### Objective Schema (Agent Skills Format)

```yaml
---
name: research-synthesis-verification
description: Verify that synthesized KB entries accurately ground claims in sources
compatibility: Requires web_search, semantic_search, httpx
metadata:
  domain: kb
  type: rase-objective
  priority: high
  environment: kb-operations  # Maps to Atropos env
allowed-tools: WebSearch WebFetch Read Write mcp__gaius__*
---

# Research Synthesis Verification

## Intent
Ensure synthesized documents contain verifiable claims...

## Success Criteria (Gates)
1. [Syntactic] Document parses as valid markdown
2. [Syntactic] All wikilinks resolve
3. [Semantic] Contains at least N citations
4. [Empirical] Citations return HTTP 200
5. [Empirical] Semantic similarity to sources > threshold

## Verification Harness
- Constraint: CitationsVerifiable(min=1)
- Constraint: WikilinksResolve()
- Constraint: SemanticCoherence(threshold=0.7)

## Evidence
- hx://gaius-datasets/rsv/<run-id>/...
```

---

## Integration Path

### Phase 1: Objective Schema + KB Layout

1. Create `current/objectives/` and `current/commands/` in KB
2. Define objective YAML schema (extending Skills format)
3. Implement objective document parser (reuse Skills frontmatter)

### Phase 2: Connect Objectives to RASE

4. Map objective gates → RASE constraints
5. Objective `verification-harness` → VerificationCase generation
6. Evidence paths → TraceableId + OpenLineage

### Phase 3: De Novo Generation

7. Implement capability gap → objective candidate pipeline
8. KB synthesis + operational surface → proposed objectives
9. Objective validation loop (syntactic → semantic → empirical)

### Phase 4: Atropos Integration

10. Objective metadata → Atropos environment config
11. Gates → reward functions
12. Evidence → training data pipeline

---

## Implications for Today's Work

The Research Synthesis Verification example I proposed earlier is a *specific instance* of a de novo objective. The document suggests we should:

1. **Store it as a first-class objective** in `current/objectives/`
2. **Define explicit gates** (not just "it works")
3. **Link to affordances** (which commands/tools enable it)
4. **Track evidence** (hx pointers for bulk outputs)

This means before implementing RSV constraints, we should:
1. Create the KB structure for objectives
2. Write the RSV objective document
3. Then implement the verification harness

The objective document *becomes* the specification for the RASE loop.

---

## Open Questions

1. **Ontology generation loop**: The document describes LLM → OWL → verbalization → topic recovery. How does this integrate with RASE? Is ontology generation itself an objective, or a meta-capability?

2. **Command surface convergence**: The document suggests KB commands should use Skills format. Should we implement this before or after RASE verification?

3. **hx storage discipline**: Need to define the hx:// URI scheme and MinIO bucket layout for evidence artifacts.

4. **Recursion depth**: If objectives generate objectives, what prevents infinite regress? Answer: empirical gates are terminal—either you pass or you don't.

---

## Recommendation

Start with **Research Synthesis Verification as the first objective document**:
1. It's concrete and immediately useful
2. It has clear gates (citations verifiable, links resolve, semantic coherence)
3. It uses existing infrastructure (web_search, semantic_search)
4. It validates the objective schema before we generalize

Then use RSV as the template for de novo objective elucidation.
