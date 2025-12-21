# RASE Objectives Implementation Summary

**Date**: 2025-12-21
**Status**: Phase 1+2 Complete

## Overview

Implemented De Novo Objective Elucidation system for RASE (Rapid Agent Systems Engineering). This enables objectives to be defined as first-class KB entities with intrinsic verification, providing verifiable reward signals for agent training without external model dependencies.

## Key Components

### 1. KB Domain Package (`src/gaius/rase/domains/kb/`)

- **state.py**: KBState, KBDocument, KBLink, Citation models implementing SystemState protocol
- **objective.py**: Objective, ObjectiveFrontmatter, ObjectiveGate, GateLevel for defining verification goals
- **constraints.py**: DocumentParses, WikilinksResolve, HasCitations, CitationsAccessible, SemanticCoherence, FrontmatterValid, OutputStructureValid
- **verification.py**: KBVerificationCase and objective_to_verification_case factory
- **oracle.py**: KBOracle for intrinsic verification (API-as-oracle pattern)
- **evidence.py**: Bridge to HX evidence capture

### 2. HX Evidence Storage (`src/gaius/hx/`)

- **evidence_tables.py**: Iceberg schema for `rase.evidence` table (20 fields)
- **evidence.py**: EvidenceCapture class following ExchangeCapture patterns
- Stores evidence in Iceberg via MinIO with thin KB manifests

### 3. Evolution Daemon Integration (`src/gaius/agents/evolution/`)

- **objective_generator.py**: Generates TaskItems from KB objectives
- **daemon_oracle.py**: Intrinsic verification scorer using RASE
- **calibration.py**: Outer loop validation with Cerebras/XAI
- Updated **daemon.py** with new config options and calibration cycle

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Evolution Daemon                               │
│                                                                     │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │                 Intrinsic Loop (Inner)                       │  │
│   │                                                              │  │
│   │   Objective Generator → Agent → Daemon Oracle → Reward       │  │
│   │          ↓                           ↓                       │  │
│   │   KB Objectives           KBOracle → Evidence Capture        │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │               Calibration Loop (Outer)                       │  │
│   │                                                              │  │
│   │   Held-out Tasks → Intrinsic Score ─┐                        │  │
│   │                                     ├→ Correlation Analysis  │  │
│   │   Held-out Tasks → External Score ──┘                        │  │
│   │                     (Cerebras/XAI)                           │  │
│   └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## First Objective: Research Synthesis Verification (RSV)

Located at `build/dev/current/objectives/rsv.md`:

- **Purpose**: Verify synthesized KB documents accurately ground claims in sources
- **Gates**:
  1. DocumentParses (syntactic)
  2. FrontmatterValid (syntactic)
  3. WikilinksResolve (semantic)
  4. HasCitations (semantic)
  5. CitationsAccessible (empirical)

## MCP Tool

Added `verify_objective` tool to `mcp_server.py`:

```python
result = await oracle.verify_objective(objective)
# Returns: verdict, accuracy, reward, constraint_results
```

## Evolution Daemon Config

New configuration options in `EvolutionConfig`:

```python
# RASE Intrinsic Verification Settings
use_intrinsic_verification: bool = True
kb_root: str = "build/dev"
calibration_cycle_interval: int = 20
prefer_cerebras: bool = True
capture_evidence: bool = True
```

## BFO Alignment

Following Basic Formal Ontology (BFO) as the upper ontology standard (Cloudera team requirement):

- **bfo:Process**: Verification process
- **bfo:InformationContentEntity**: KB documents
- **bfo:Quality**: Verification properties

## Evidence Storage

Evidence stored in Iceberg at `hx://rase.evidence`:

- Partitioned by domain and month
- Contains verification results, constraint outcomes, digital thread
- KB manifests link to bulk evidence

## Next Steps

1. Add more objectives (wikilink-integrity, citation-freshness, semantic-grounding)
2. Implement abstract extension mechanism for objective derivation
3. Create database migration for `evolution_calibrations` table
4. Add MCP tools for calibration status and forcing calibration cycles
