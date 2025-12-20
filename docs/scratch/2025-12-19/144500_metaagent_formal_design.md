# MetaAgent: Formal Design Document

**Version**: 1.0
**Date**: 2025-12-19
**Status**: Draft
**Authors**: Gaius Development Team
**Branch**: `feature/metaagent`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Design Goals](#3-design-goals)
4. [Architecture Overview](#4-architecture-overview)
5. [Component Design](#5-component-design)
6. [Data Model](#6-data-model)
7. [BDD-Grounded Evaluation Framework](#7-bdd-grounded-evaluation-framework)
8. [Dataset Generation Pipeline](#8-dataset-generation-pipeline)
9. [Learning Loop Architecture](#9-learning-loop-architecture)
10. [Implementation Phases](#10-implementation-phases)
11. [API Specifications](#11-api-specifications)
12. [Failure Modes & Remediation](#12-failure-modes--remediation)
13. [Security Considerations](#13-security-considerations)
14. [Testing Strategy](#14-testing-strategy)
15. [Appendices](#15-appendices)

---

## 1. Executive Summary

MetaAgent is Gaius's orchestration layer for data pipeline intelligence. It enables autonomous agents to observe, understand, and manipulate data pipelines through a combination of visual understanding (NiFi canvas) and analytical insight (Metabase dashboards), with execution remaining in reproducible Metaflow pipelines.

The core innovation is a **BDD-grounded evaluation framework** where the NiFi REST API serves as an oracle for browser agent behavior verification. This enables:

- **Ground truth generation**: API-driven state creation for training data
- **Semantic verification**: Compare flow topology, not pixel positions
- **Curriculum learning**: BDD scenarios form natural difficulty progression
- **Reproducible evaluation**: Scenarios run in CI/CD pipelines

### Key Outcomes

| Metric | Target |
|--------|--------|
| Dataset generation throughput | 100+ examples/hour |
| Agent task success rate | >80% on trained scenarios |
| Ground truth verification accuracy | 100% (API-based) |
| BDD scenario coverage | 50+ core workflows |

---

## 2. Problem Statement

### Current State

Data pipeline management requires human operators to:
1. Visually inspect flow diagrams in tools like NiFi
2. Manually configure processors and connections
3. Monitor execution metrics in separate dashboards
4. Correlate failures across multiple systems

### Challenges

1. **Visual Understanding Gap**: Agents cannot interpret data flow diagrams
2. **Action Grounding**: No verified mapping from visual state to API operations
3. **Evaluation Difficulty**: Hard to measure agent success without ground truth
4. **Training Data Scarcity**: Limited labeled examples of (screenshot, action) pairs

### Opportunity

NiFi provides both:
- A rich visual canvas (screenshot-able)
- A comprehensive REST API (programmable)

This duality enables **grounded training and evaluation**: the API defines truth, the UI provides the visual interface for agent learning.

---

## 3. Design Goals

### Primary Goals

| Goal | Description | Measure |
|------|-------------|---------|
| **G1: Grounded Evaluation** | API serves as oracle for agent behavior | 100% verifiable outcomes |
| **G2: Visual Understanding** | Agents interpret NiFi canvas screenshots | Task success rate >80% |
| **G3: Curriculum Learning** | Progressive difficulty via BDD scenarios | 50+ scenarios across 5 levels |
| **G4: Reproducibility** | All evaluations runnable in CI/CD | Full automation |
| **G5: Separation of Concerns** | Execution in Metaflow, visualization in NiFi | Clean interfaces |

### Non-Goals

- NiFi as complete execution engine (Metaflow steps are only visualized)
- Real-time streaming through NiFi (Metaflow handles core execution)
- Pixel-perfect UI reproduction (semantic equivalence sufficient)

### Design Principles

1. **Fail-Fast**: Surface errors immediately with actionable remediation
2. **API as Oracle**: NiFi REST API is the source of truth for state
3. **Semantic Verification**: Compare topology, not visual layout
4. **BDD-First**: Specifications drive implementation
5. **Incremental Learning**: Curriculum from simple to complex

---

## 4. Architecture Overview

### System Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GAIUS ECOSYSTEM                                │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         GAIUS BOARD (TUI)                           │   │
│  │                    19×19 Spatial Interface                          │   │
│  │                                                                     │   │
│  │  • KB topology visualization    • Agent swarm status                │   │
│  │  • Semantic region navigation   • Command interface                 │   │
│  │                                                                     │   │
│  |                        User Interaction                             |   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                      │
│                            gRPC Services                                   │
│                                     │                                      │
│  ┌──────────────────────────────────┼──────────────────────────────────┐   │
│  │                         METAAGENT LAYER                             │   │
│  │                                  │                                  │   │
│  │  ┌────────────────┐  ┌──────────┴───────────┐  ┌────────────────┐  │   │
│  │  │  OBSERVATION   │  │      EVALUATION      │  │     ACTION     │  │   │
│  │  │                │  │                      │  │                │  │   │
│  │  │ • Screenshots  │  │ • BDD Scenarios      │  │ • NiFi API     │  │   │
│  │  │ • SoM/ToM      │  │ • API Verification   │  │ • Flow Mods    │  │   │
│  │  │ • State Capture│  │ • Semantic Diff      │  │ • Config Ops   │  │   │
│  │  └────────────────┘  └──────────────────────┘  └────────────────┘  │   │
│  │                                  │                                  │   │
│  │                         gRPC Services                               │   │
│  │                                  │                                  │   │
│  └──────────────────────────────────┼──────────────────────────────────┘   │
│                                     │                                       │
│         ┌───────────────────────────┼───────────────────────────┐          │
│         │                           │                           │          │
│         ▼                           ▼                           ▼          │
│  ┌─────────────┐           ┌─────────────┐            ┌─────────────┐      │
│  │  METAFLOW   │           │    NIFI     │            │  METABASE   │      │
│  │ (Execution) │           │  (Visual)   │            │ (Analytics) │      │
│  │             │           │             │            │             │      │
│  │ • K8s/Tilt  │           │ • Canvas    │            │ • Dashboards│      │
│  │ • Versioned │           │ • REST API  │            │ • SQL       │      │
│  │ • Lineage   │           │ • Selenium  │            │ • Alerts    │      │
│  └─────────────┘           └─────────────┘            └─────────────┘      │
│         │                           │                           │          │
│         └───────────────────────────┼───────────────────────────┘          │
│                                     │                                       │
│                                     ▼                                       │
│                          ┌─────────────────┐                               │
│                          │   POSTGRESQL    │                               │
│                          │                 │                               │
│                          │ • lineage_events│                               │
│                          │ • meta.* schema │                               │
│                          │ • agent versions│                               │
│                          │ • bdd_scenarios │                               │
│                          └─────────────────┘                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Interface |
|-----------|---------------|-----------|
| **Metaflow** | Pipeline execution, versioning, lineage | Python API, K8s |
| **NiFi** | Visual monitoring, screenshot source, API oracle | REST API, Selenium |
| **Metabase** | Analytics dashboards, trend visualization | SQL, REST API |
| **MetaAgent** | Orchestration, learning loop, agent coordination | gRPC |
| **PostgreSQL** | Persistent state, analytics, BDD results | SQL |

---

## 5. Component Design

### 5.1 NiFi Integration Layer

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        NIFI INTEGRATION LAYER                           │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        NiFiClient                                │   │
│  │                   (Async HTTP REST Client)                       │   │
│  │                                                                  │   │
│  │  Methods:                                                        │   │
│  │  • get_root_process_group() → ProcessGroup                      │   │
│  │  • create_process_group(parent_id, name) → ProcessGroup         │   │
│  │  • create_processor(parent_id, type, config) → Processor        │   │
│  │  • create_connection(source, dest, rels) → Connection           │   │
│  │  • get_flow_state(pg_id) → FlowState                            │   │
│  │  • delete_process_group(pg_id) → None                           │   │
│  │  • list_processors(pg_id) → List[Processor]                     │   │
│  │  • list_connections(pg_id) → List[Connection]                   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      NiFiStateManager                            │   │
│  │                  (Ground Truth Operations)                       │   │
│  │                                                                  │   │
│  │  Methods:                                                        │   │
│  │  • setup_ground_truth(scenario) → FlowState                     │   │
│  │  • reset_to_initial(pg_id) → None                               │   │
│  │  • capture_state(pg_id) → FlowState                             │   │
│  │  • compare_states(expected, actual) → StateDiff                 │   │
│  │  • serialize_state(state) → JSON                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     NiFiScreenCapture                            │   │
│  │                   (Selenium Integration)                         │   │
│  │                                                                  │   │
│  │  Methods:                                                        │   │
│  │  • capture_screenshot(url) → Image                              │   │
│  │  • capture_with_som(url) → (Image, SoMAnnotations)              │   │
│  │  • validate_screenshot(image) → bool                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 BDD Evaluation Engine

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        BDD EVALUATION ENGINE                            │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      ScenarioLoader                              │   │
│  │                                                                  │   │
│  │  • load_feature(path) → Feature                                 │   │
│  │  • parse_scenario(text) → Scenario                              │   │
│  │  • list_scenarios(difficulty) → List[Scenario]                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      ScenarioRunner                              │   │
│  │                                                                  │   │
│  │  Pipeline:                                                       │   │
│  │  1. setup_ground_truth() - Create expected state via API        │   │
│  │  2. capture_ground_truth() - Screenshot + state JSON            │   │
│  │  3. reset_canvas() - Return to initial conditions               │   │
│  │  4. capture_initial() - Screenshot of starting state            │   │
│  │  5. execute_agent() - Agent performs UI actions                 │   │
│  │  6. capture_result() - Screenshot + state JSON                  │   │
│  │  7. verify_result() - Compare actual vs expected                │   │
│  │  8. record_outcome() - Store in database                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      StateComparator                             │   │
│  │                                                                  │   │
│  │  Comparison Dimensions:                                          │   │
│  │  • Processors: name, type, configuration                        │   │
│  │  • Connections: source, destination, relationships              │   │
│  │  • Process Groups: hierarchy, naming                            │   │
│  │  • Properties: key-value configurations                         │   │
│  │                                                                  │   │
│  │  NOT compared (layout-only):                                     │   │
│  │  • Position coordinates (x, y)                                  │   │
│  │  • Visual styling                                               │   │
│  │  • UI element ordering                                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      ResultRecorder                              │   │
│  │                                                                  │   │
│  │  Records to PostgreSQL:                                          │   │
│  │  • bdd_scenario_runs: execution metadata                        │   │
│  │  • bdd_state_snapshots: before/after states                     │   │
│  │  • bdd_agent_actions: action traces                             │   │
│  │  • bdd_verification_results: pass/fail with diffs               │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Browser Agent Interface

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        BROWSER AGENT INTERFACE                          │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       BrowserAgent                               │   │
│  │                                                                  │   │
│  │  Inputs:                                                         │   │
│  │  • screenshot: PIL.Image (current canvas state)                 │   │
│  │  • instruction: str (natural language task)                     │   │
│  │  • som_annotations: Optional[SoMData] (element locations)       │   │
│  │                                                                  │   │
│  │  Outputs:                                                        │   │
│  │  • actions: List[BrowserAction] (click, type, drag, etc.)       │   │
│  │  • reasoning: str (chain of thought)                            │   │
│  │  • confidence: float (0-1)                                      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     ActionExecutor                               │   │
│  │                                                                  │   │
│  │  Supported Actions:                                              │   │
│  │  • click(x, y) - Single click at coordinates                    │   │
│  │  • double_click(x, y) - Double click                            │   │
│  │  • right_click(x, y) - Context menu                             │   │
│  │  • drag(x1, y1, x2, y2) - Drag and drop                        │   │
│  │  • type(text) - Keyboard input                                  │   │
│  │  • key(name) - Special key (Enter, Escape, etc.)                │   │
│  │  • scroll(direction, amount) - Mouse wheel                      │   │
│  │                                                                  │   │
│  │  Execution Mode:                                                 │   │
│  │  • Selenium WebDriver for real browser                          │   │
│  │  • Playwright for headless CI/CD                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     ActionTracer                                 │   │
│  │                                                                  │   │
│  │  Records:                                                        │   │
│  │  • Timestamp for each action                                    │   │
│  │  • Screenshot before/after each action                          │   │
│  │  • Action parameters                                            │   │
│  │  • Success/failure status                                       │   │
│  │                                                                  │   │
│  │  Output: ActionTrace (JSON-serializable)                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Model

### 6.1 BDD Schema Extension

```sql
-- BDD scenario definitions
CREATE TABLE bdd_scenarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_name TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    difficulty_level INTEGER NOT NULL CHECK (difficulty_level BETWEEN 1 AND 5),
    gherkin_text TEXT NOT NULL,
    expected_state JSONB NOT NULL,
    initial_state JSONB NOT NULL DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(feature_name, scenario_name)
);

-- Scenario execution runs
CREATE TABLE bdd_scenario_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID REFERENCES bdd_scenarios(id),
    agent_version_id UUID REFERENCES agent_versions(id),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'error')),
    error_message TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- State snapshots during execution
CREATE TABLE bdd_state_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES bdd_scenario_runs(id),
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN (
        'ground_truth', 'initial', 'after_action', 'final'
    )),
    flow_state JSONB NOT NULL,
    screenshot_path TEXT,
    som_annotations JSONB,
    captured_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agent action traces
CREATE TABLE bdd_agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES bdd_scenario_runs(id),
    action_index INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    action_params JSONB NOT NULL,
    reasoning TEXT,
    confidence FLOAT,
    success BOOLEAN,
    error_message TEXT,
    screenshot_before_path TEXT,
    screenshot_after_path TEXT,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Verification results with semantic diffs
CREATE TABLE bdd_verification_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES bdd_scenario_runs(id),
    expected_state JSONB NOT NULL,
    actual_state JSONB NOT NULL,
    semantic_diff JSONB NOT NULL,
    processors_correct INTEGER NOT NULL,
    processors_total INTEGER NOT NULL,
    connections_correct INTEGER NOT NULL,
    connections_total INTEGER NOT NULL,
    properties_correct INTEGER NOT NULL,
    properties_total INTEGER NOT NULL,
    overall_score FLOAT NOT NULL,
    verified_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_bdd_runs_scenario ON bdd_scenario_runs(scenario_id);
CREATE INDEX idx_bdd_runs_status ON bdd_scenario_runs(status);
CREATE INDEX idx_bdd_runs_agent ON bdd_scenario_runs(agent_version_id);
CREATE INDEX idx_bdd_snapshots_run ON bdd_state_snapshots(run_id);
CREATE INDEX idx_bdd_actions_run ON bdd_agent_actions(run_id);
```

### 6.2 Flow State Schema

```python
@dataclass
class FlowState:
    """Semantic representation of NiFi flow state."""

    process_group_id: str
    process_group_name: str

    processors: List[ProcessorState]
    connections: List[ConnectionState]
    child_groups: List[FlowState]  # Recursive for nested groups

    # Metadata (not used in semantic comparison)
    captured_at: datetime
    nifi_version: str


@dataclass
class ProcessorState:
    """Processor state for semantic comparison."""

    id: str
    name: str
    type: str  # e.g., "org.apache.nifi.processors.standard.GetHTTP"
    state: str  # STOPPED, RUNNING, DISABLED

    # Configuration properties (semantically significant)
    properties: Dict[str, str]

    # Relationships defined by this processor
    relationships: List[str]

    # Not used in semantic comparison
    position: Optional[Tuple[float, float]] = None
    comments: Optional[str] = None


@dataclass
class ConnectionState:
    """Connection state for semantic comparison."""

    id: str
    name: Optional[str]

    source_id: str
    source_name: str
    source_type: str  # PROCESSOR, INPUT_PORT, etc.

    destination_id: str
    destination_name: str
    destination_type: str

    selected_relationships: List[str]

    # Flow control (semantically significant)
    back_pressure_object_threshold: int
    back_pressure_data_size_threshold: str

    # Not used in semantic comparison
    bends: Optional[List[Tuple[float, float]]] = None
```

### 6.3 Semantic Diff Schema

```python
@dataclass
class SemanticDiff:
    """Result of comparing expected vs actual flow state."""

    # Processor differences
    missing_processors: List[str]  # Expected but not found
    extra_processors: List[str]    # Found but not expected
    processor_mismatches: List[ProcessorMismatch]

    # Connection differences
    missing_connections: List[str]
    extra_connections: List[str]
    connection_mismatches: List[ConnectionMismatch]

    # Property differences
    property_mismatches: List[PropertyMismatch]

    # Summary scores
    processor_accuracy: float  # 0-1
    connection_accuracy: float  # 0-1
    property_accuracy: float   # 0-1
    overall_accuracy: float    # Weighted average

    def is_semantically_equivalent(self, threshold: float = 1.0) -> bool:
        """Check if states are equivalent within threshold."""
        return self.overall_accuracy >= threshold


@dataclass
class ProcessorMismatch:
    processor_name: str
    field: str  # 'type', 'state', 'property:X'
    expected: str
    actual: str


@dataclass
class ConnectionMismatch:
    connection_desc: str  # "ProcessorA -> ProcessorB"
    field: str
    expected: str
    actual: str
```

---

## 7. BDD-Grounded Evaluation Framework

### 7.1 Concept Overview

The BDD-Grounded Evaluation Framework uses the NiFi REST API as an **oracle** for browser agent behavior verification. This addresses the fundamental challenge of evaluating visual agents: how do we know if the agent achieved the correct result?

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    GROUNDED EVALUATION CONCEPT                          │
│                                                                         │
│   Traditional Approach:                                                 │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              │
│   │ Screenshot  │ ──▶ │   Agent     │ ──▶ │  ??? How to │              │
│   │ + Instruct  │     │   Actions   │     │   verify?   │              │
│   └─────────────┘     └─────────────┘     └─────────────┘              │
│                                                 │                       │
│                                          Human review                   │
│                                          (expensive, slow)              │
│                                                                         │
│   ─────────────────────────────────────────────────────────────────    │
│                                                                         │
│   Grounded Approach:                                                    │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              │
│   │ API creates │ ──▶ │   Agent     │ ──▶ │ API verifies│              │
│   │ ground truth│     │   Actions   │     │ actual state│              │
│   └─────────────┘     └─────────────┘     └─────────────┘              │
│         │                                        │                      │
│         └──────────────┬─────────────────────────┘                      │
│                        │                                                │
│                        ▼                                                │
│              ┌─────────────────┐                                        │
│              │ Semantic Diff   │                                        │
│              │ (automated,     │                                        │
│              │  deterministic) │                                        │
│              └─────────────────┘                                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Evaluation Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      EVALUATION PIPELINE                                │
│                                                                         │
│  Phase 1: GROUND TRUTH SETUP                                           │
│  ════════════════════════════                                           │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │ Load BDD     │───▶│ Execute API  │───▶│ Capture      │              │
│  │ Scenario     │    │ Operations   │    │ Ground Truth │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│        │                    │                    │                      │
│        │                    │                    ▼                      │
│        │                    │           ┌──────────────┐               │
│        │                    │           │ • Screenshot │               │
│        │                    │           │ • FlowState  │               │
│        │                    │           │ • SoM/ToM    │               │
│        │                    │           └──────────────┘               │
│        │                    │                                          │
│  Phase 2: CANVAS RESET                                                 │
│  ═════════════════════                                                  │
│        │                    │                                          │
│        │                    ▼                                          │
│        │           ┌──────────────┐    ┌──────────────┐               │
│        │           │ Delete all   │───▶│ Capture      │               │
│        │           │ created      │    │ Initial      │               │
│        │           │ elements     │    │ State        │               │
│        │           └──────────────┘    └──────────────┘               │
│        │                                       │                       │
│  Phase 3: AGENT CHALLENGE                                              │
│  ════════════════════════                                               │
│        │                                       │                       │
│        ▼                                       ▼                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │ Extract      │───▶│ Agent        │───▶│ Execute      │             │
│  │ Instruction  │    │ Inference    │    │ Actions      │             │
│  └──────────────┘    └──────────────┘    └──────────────┘             │
│                             │                    │                     │
│                             │                    ▼                     │
│                             │           ┌──────────────┐              │
│                             │           │ Action Trace │              │
│                             │           │ Recording    │              │
│                             │           └──────────────┘              │
│                             │                                         │
│  Phase 4: VERIFICATION                                                │
│  ═════════════════════                                                 │
│                             │                                         │
│                             ▼                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐            │
│  │ Capture      │───▶│ Semantic     │───▶│ Record       │            │
│  │ Final State  │    │ Comparison   │    │ Results      │            │
│  └──────────────┘    └──────────────┘    └──────────────┘            │
│        │                    │                    │                    │
│        ▼                    ▼                    ▼                    │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐            │
│  │ • Screenshot │    │ • Diff JSON  │    │ • Pass/Fail  │            │
│  │ • FlowState  │    │ • Accuracy % │    │ • Metrics    │            │
│  └──────────────┘    └──────────────┘    └──────────────┘            │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

### 7.3 BDD Feature Structure

```
features/
├── nifi_basics/
│   ├── level_1_navigation.feature      # Canvas navigation, zoom, pan
│   ├── level_2_single_processor.feature # Add one processor
│   └── level_3_simple_flow.feature     # Two processors + connection
│
├── nifi_flows/
│   ├── level_3_linear_flow.feature     # A → B → C
│   ├── level_4_branching_flow.feature  # A → B, A → C
│   └── level_5_complex_flow.feature    # Multiple branches, groups
│
├── nifi_configuration/
│   ├── level_3_processor_config.feature # Set properties
│   ├── level_4_connection_config.feature # Back pressure, etc.
│   └── level_5_controller_services.feature # Shared services
│
├── nifi_operations/
│   ├── level_2_start_stop.feature      # Start/stop processors
│   ├── level_3_enable_disable.feature  # Enable/disable
│   └── level_4_clear_queues.feature    # Queue management
│
└── steps/
    ├── nifi_setup_steps.py             # Ground truth setup
    ├── nifi_verify_steps.py            # State verification
    ├── agent_steps.py                  # Agent execution
    └── common_steps.py                 # Shared utilities
```

### 7.4 Example Feature File

```gherkin
# features/nifi_flows/level_3_linear_flow.feature

@level-3 @flow-creation @linear
Feature: Create linear data flow
  As a vision-language agent
  I want to create a simple linear flow in NiFi
  So that I can orchestrate sequential data processing

  Background:
    Given a clean NiFi canvas
    And the agent has access to the NiFi UI at "http://localhost:8450/nifi"

  @smoke @critical
  Scenario: Create two-processor HTTP-to-JSON flow
    """
    This scenario tests the fundamental ability to:
    1. Add multiple processors to the canvas
    2. Connect them with a relationship
    3. Configure basic properties
    """

    # Define ground truth via API
    Given the expected flow contains processors:
      | name          | type                                              |
      | FetchHTTP     | org.apache.nifi.processors.standard.InvokeHTTP   |
      | ParseJSON     | org.apache.nifi.processors.standard.EvaluateJsonPath |

    And processor "FetchHTTP" has properties:
      | property      | value                        |
      | HTTP Method   | GET                          |
      | Remote URL    | https://api.example.com/data |

    And the expected connections are:
      | source    | destination | relationships |
      | FetchHTTP | ParseJSON   | Response      |

    # Agent challenge
    When the agent is given the instruction:
      """
      Create a data flow that:
      1. Fetches data from https://api.example.com/data using HTTP GET
      2. Parses the JSON response
      Connect the HTTP processor's Response to the JSON parser.
      """

    And the agent performs actions on the NiFi canvas

    # Verification via API
    Then the canvas should contain 2 processors
    And processor "FetchHTTP" should exist with type containing "InvokeHTTP"
    And processor "ParseJSON" should exist with type containing "EvaluateJsonPath"
    And there should be a connection from "FetchHTTP" to "ParseJSON" on "Response"
    And the semantic accuracy should be at least 0.9

  @data-generation
  Scenario Outline: Create flow with <source_type> to <dest_type>
    """
    Parameterized scenario for generating diverse training data
    """
    Given the expected flow contains processors:
      | name   | type          |
      | Source | <source_type> |
      | Dest   | <dest_type>   |

    And the expected connections are:
      | source | destination | relationships   |
      | Source | Dest        | <relationship>  |

    When the agent is given the instruction:
      """
      Create a flow with a <source_desc> processor connected to a <dest_desc> processor
      using the <relationship> relationship.
      """

    And the agent performs actions on the NiFi canvas

    Then the semantic accuracy should be at least 0.8

    Examples:
      | source_type | dest_type | relationship | source_desc | dest_desc |
      | GetFile     | PutFile   | success      | file reader | file writer |
      | GetHTTP     | PutS3     | Response     | HTTP fetch  | S3 upload |
      | ConsumeKafka| PublishKafka | success   | Kafka consumer | Kafka publisher |
```

### 7.5 Step Definitions

```python
# features/steps/nifi_setup_steps.py

from behave import given, when, then
from behave.runner import Context
from gaius.agents.metaagent.nifi.client import NiFiClient
from gaius.agents.metaagent.nifi.state import NiFiStateManager
from gaius.agents.metaagent.bdd.comparator import StateComparator

@given('a clean NiFi canvas')
async def step_clean_canvas(context: Context):
    """Reset NiFi to a clean state."""
    state_manager = NiFiStateManager()
    context.root_pg_id = await state_manager.get_root_process_group_id()
    await state_manager.clear_process_group(context.root_pg_id)

    # Capture initial state
    context.initial_state = await state_manager.capture_state(context.root_pg_id)
    context.initial_screenshot = await state_manager.capture_screenshot()


@given('the expected flow contains processors')
async def step_define_expected_processors(context: Context):
    """Create expected processors via API (ground truth)."""
    state_manager = NiFiStateManager()
    context.expected_processors = {}

    for row in context.table:
        processor = await state_manager.create_processor(
            parent_id=context.root_pg_id,
            name=row['name'],
            processor_type=row['type']
        )
        context.expected_processors[row['name']] = processor


@given('processor "{name}" has properties')
async def step_configure_processor(context: Context, name: str):
    """Configure processor properties via API."""
    state_manager = NiFiStateManager()
    processor = context.expected_processors[name]

    properties = {row['property']: row['value'] for row in context.table}
    await state_manager.update_processor_properties(processor.id, properties)


@given('the expected connections are')
async def step_define_expected_connections(context: Context):
    """Create expected connections via API."""
    state_manager = NiFiStateManager()
    context.expected_connections = []

    for row in context.table:
        source = context.expected_processors[row['source']]
        dest = context.expected_processors[row['destination']]
        relationships = row['relationships'].split(',')

        connection = await state_manager.create_connection(
            source_id=source.id,
            destination_id=dest.id,
            relationships=relationships
        )
        context.expected_connections.append(connection)

    # Capture ground truth state
    context.ground_truth_state = await state_manager.capture_state(context.root_pg_id)
    context.ground_truth_screenshot = await state_manager.capture_screenshot()

    # Reset canvas for agent challenge
    await state_manager.clear_process_group(context.root_pg_id)
    context.challenge_screenshot = await state_manager.capture_screenshot()


# features/steps/agent_steps.py

@when('the agent is given the instruction')
def step_set_instruction(context: Context):
    """Store the instruction for agent execution."""
    context.instruction = context.text.strip()


@when('the agent performs actions on the NiFi canvas')
async def step_execute_agent(context: Context):
    """Execute the browser agent on the NiFi canvas."""
    from gaius.agents.browser import BrowserAgent
    from gaius.agents.metaagent.bdd.tracer import ActionTracer

    agent = BrowserAgent()
    tracer = ActionTracer()

    # Execute agent with tracing
    context.agent_result = await agent.execute_task(
        screenshot=context.challenge_screenshot,
        instruction=context.instruction,
        target_url=context.nifi_url,
        tracer=tracer
    )

    context.action_trace = tracer.get_trace()

    # Capture final state
    state_manager = NiFiStateManager()
    context.final_state = await state_manager.capture_state(context.root_pg_id)
    context.final_screenshot = await state_manager.capture_screenshot()


# features/steps/nifi_verify_steps.py

@then('the canvas should contain {count:d} processors')
async def step_verify_processor_count(context: Context, count: int):
    """Verify processor count via API."""
    client = NiFiClient()
    processors = await client.list_processors(context.root_pg_id)
    assert len(processors) == count, \
        f"Expected {count} processors, found {len(processors)}: {[p.name for p in processors]}"


@then('processor "{name}" should exist with type containing "{type_fragment}"')
async def step_verify_processor_type(context: Context, name: str, type_fragment: str):
    """Verify processor exists with expected type."""
    client = NiFiClient()
    processors = await client.list_processors(context.root_pg_id)

    matching = [p for p in processors if p.name == name]
    assert len(matching) == 1, f"Expected processor '{name}', found: {[p.name for p in processors]}"

    processor = matching[0]
    assert type_fragment in processor.type, \
        f"Processor '{name}' has type '{processor.type}', expected to contain '{type_fragment}'"


@then('there should be a connection from "{source}" to "{dest}" on "{relationship}"')
async def step_verify_connection(context: Context, source: str, dest: str, relationship: str):
    """Verify connection exists via API."""
    client = NiFiClient()

    processors = await client.list_processors(context.root_pg_id)
    source_proc = next((p for p in processors if p.name == source), None)
    dest_proc = next((p for p in processors if p.name == dest), None)

    assert source_proc, f"Source processor '{source}' not found"
    assert dest_proc, f"Destination processor '{dest}' not found"

    connections = await client.list_connections(context.root_pg_id)
    matching = [
        c for c in connections
        if c.source_id == source_proc.id
        and c.destination_id == dest_proc.id
        and relationship in c.selected_relationships
    ]

    assert len(matching) >= 1, \
        f"No connection from '{source}' to '{dest}' on '{relationship}'"


@then('the semantic accuracy should be at least {threshold:f}')
async def step_verify_semantic_accuracy(context: Context, threshold: float):
    """Compare actual state to ground truth."""
    comparator = StateComparator()
    diff = comparator.compare(
        expected=context.ground_truth_state,
        actual=context.final_state
    )

    context.semantic_diff = diff

    assert diff.overall_accuracy >= threshold, \
        f"Semantic accuracy {diff.overall_accuracy:.2f} below threshold {threshold}\n" \
        f"Missing processors: {diff.missing_processors}\n" \
        f"Extra processors: {diff.extra_processors}\n" \
        f"Missing connections: {diff.missing_connections}\n" \
        f"Extra connections: {diff.extra_connections}"
```

### 7.6 Curriculum Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      CURRICULUM DIFFICULTY LEVELS                       │
│                                                                         │
│  Level 1: NAVIGATION (Foundation)                                       │
│  ════════════════════════════════                                       │
│  • Pan canvas                                                           │
│  • Zoom in/out                                                          │
│  • Select elements                                                      │
│  • Open context menus                                                   │
│                                                                         │
│  Prerequisites: None                                                    │
│  Success rate target: 95%                                               │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Level 2: SINGLE ELEMENT (Basic Manipulation)                           │
│  ════════════════════════════════════════════                           │
│  • Add one processor from toolbar                                       │
│  • Delete a processor                                                   │
│  • Start/stop a processor                                               │
│  • Rename a processor                                                   │
│                                                                         │
│  Prerequisites: Level 1 complete                                        │
│  Success rate target: 90%                                               │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Level 3: SIMPLE FLOWS (Composition)                                    │
│  ═══════════════════════════════════                                    │
│  • Create two-processor linear flow                                     │
│  • Configure processor properties                                       │
│  • Create connections with relationships                                │
│  • Set basic connection properties                                      │
│                                                                         │
│  Prerequisites: Level 2 complete                                        │
│  Success rate target: 85%                                               │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Level 4: COMPLEX FLOWS (Advanced Composition)                          │
│  ═════════════════════════════════════════════                          │
│  • Branching flows (one source, multiple destinations)                  │
│  • Merging flows (multiple sources, one destination)                    │
│  • Process groups (nested organization)                                 │
│  • Controller services configuration                                    │
│                                                                         │
│  Prerequisites: Level 3 with 85%+ accuracy                              │
│  Success rate target: 75%                                               │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Level 5: EXPERT OPERATIONS (Full Capability)                           │
│  ════════════════════════════════════════════                           │
│  • Multi-step flow modifications                                        │
│  • Template instantiation                                               │
│  • Variable registry usage                                              │
│  • Flow versioning operations                                           │
│  • Troubleshooting (inspect queued data, provenance)                    │
│                                                                         │
│  Prerequisites: Level 4 with 75%+ accuracy                              │
│  Success rate target: 65%                                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Dataset Generation Pipeline

### 8.1 Pipeline Overview

The NiFi SoM/ToM dataset generation pipeline creates training data for vision-language models. With the BDD framework, we now have **two complementary data sources**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    DATASET GENERATION SOURCES                           │
│                                                                         │
│  Source 1: TEMPLATE-BASED (Current)                                     │
│  ══════════════════════════════════                                     │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │ Flow         │───▶│ Screenshot   │───▶│ Template     │              │
│  │ Definition   │    │ + SoM/ToM    │    │ Instructions │              │
│  │ (Metaflow)   │    │              │    │              │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│                                                                         │
│  Pros: Fast, deterministic, scalable                                   │
│  Cons: Limited instruction diversity                                    │
│                                                                         │
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  Source 2: BDD-GROUNDED (New)                                          │
│  ════════════════════════════                                           │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │ BDD          │───▶│ Ground Truth │───▶│ Verified     │              │
│  │ Scenario     │    │ + Agent Run  │    │ (state, act) │              │
│  │              │    │              │    │ pairs        │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│                                                                         │
│  Pros: Verified ground truth, action traces, diverse                   │
│  Cons: Slower, requires agent execution                                │
│                                                                         │
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  Combined Strategy:                                                     │
│  ═════════════════                                                      │
│                                                                         │
│  1. Bootstrap with template-based data (high volume)                   │
│  2. Train initial model                                                │
│  3. Run BDD scenarios with initial model                               │
│  4. Collect verified successes as additional training data             │
│  5. Fine-tune on verified data                                         │
│  6. Repeat (curriculum learning)                                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 BDD-to-Dataset Conversion

```python
# src/gaius/datasets/nifi_som/bdd_converter.py

@dataclass
class BDDDatasetEntry:
    """Dataset entry generated from BDD scenario run."""

    # Identifiers
    scenario_id: str
    run_id: str

    # Input data
    initial_screenshot: Path
    initial_som: Dict[str, Any]
    instruction: str

    # Ground truth
    ground_truth_screenshot: Path
    ground_truth_state: Dict[str, Any]

    # Agent execution (if successful)
    action_trace: List[Dict[str, Any]]
    final_screenshot: Path
    final_state: Dict[str, Any]

    # Verification
    semantic_accuracy: float
    is_success: bool

    # Metadata
    difficulty_level: int
    tags: List[str]


class BDDDatasetConverter:
    """Convert BDD scenario runs to training dataset entries."""

    def __init__(self, db_url: str, output_dir: Path):
        self.db_url = db_url
        self.output_dir = output_dir

    async def convert_successful_runs(
        self,
        min_accuracy: float = 0.9,
        difficulty_levels: Optional[List[int]] = None
    ) -> List[BDDDatasetEntry]:
        """Extract successful runs as training data."""

        # Query successful runs
        runs = await self._query_successful_runs(min_accuracy, difficulty_levels)

        entries = []
        for run in runs:
            entry = await self._convert_run(run)
            if entry:
                entries.append(entry)

        return entries

    async def export_magma_format(
        self,
        entries: List[BDDDatasetEntry],
        output_path: Path
    ) -> None:
        """Export to Magma training format."""

        magma_entries = []
        for entry in entries:
            magma_entry = {
                "image": str(entry.initial_screenshot),
                "conversations": [
                    {
                        "from": "human",
                        "value": f"<image>\n{entry.instruction}"
                    },
                    {
                        "from": "gpt",
                        "value": self._format_action_trace(entry.action_trace)
                    }
                ],
                "metadata": {
                    "source": "bdd_grounded",
                    "scenario_id": entry.scenario_id,
                    "difficulty": entry.difficulty_level,
                    "semantic_accuracy": entry.semantic_accuracy
                }
            }
            magma_entries.append(magma_entry)

        with open(output_path, 'w') as f:
            for entry in magma_entries:
                f.write(json.dumps(entry) + '\n')
```

### 8.3 Integration with Existing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    INTEGRATED DATASET PIPELINE                          │
│                                                                         │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    DatasetService (gRPC)                        │   │
│  │                                                                 │   │
│  │  Endpoints:                                                     │   │
│  │  • SubmitDatasetJob (existing) - Template-based generation     │   │
│  │  • SubmitBDDEvaluation (new) - Run BDD scenarios               │   │
│  │  • ConvertBDDToDataset (new) - Extract training data           │   │
│  │  • GetDatasetStatus (existing)                                 │   │
│  │  • CancelDatasetJob (existing)                                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                     ┌──────────────┴──────────────┐                    │
│                     │                             │                    │
│                     ▼                             ▼                    │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐     │
│  │   Template Generator        │  │   BDD Evaluation Engine     │     │
│  │                             │  │                             │     │
│  │   • Metaflow projection    │  │   • Scenario execution      │     │
│  │   • Screenshot capture      │  │   • Agent invocation        │     │
│  │   • SoM annotation         │  │   • State verification      │     │
│  │   • Instruction generation │  │   • Result recording        │     │
│  └─────────────────────────────┘  └─────────────────────────────┘     │
│                     │                             │                    │
│                     └──────────────┬──────────────┘                    │
│                                    │                                    │
│                                    ▼                                    │
│                     ┌─────────────────────────────┐                    │
│                     │   Dataset Aggregator        │                    │
│                     │                             │                    │
│                     │   • Merge sources           │                    │
│                     │   • Quality filtering       │                    │
│                     │   • Format conversion       │                    │
│                     │   • S3/MinIO export         │                    │
│                     └─────────────────────────────┘                    │
│                                    │                                    │
│                                    ▼                                    │
│                     ┌─────────────────────────────┐                    │
│                     │   gaius-datasets (MinIO)    │                    │
│                     │                             │                    │
│                     │   /template-generated/      │                    │
│                     │   /bdd-grounded/            │                    │
│                     │   /combined/                │                    │
│                     └─────────────────────────────┘                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Learning Loop Architecture

### 9.1 Continuous Improvement Cycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     METAAGENT LEARNING LOOP                             │
│                                                                         │
│                                                                         │
│     ┌─────────┐                                          ┌─────────┐   │
│     │         │                                          │         │   │
│     │ OBSERVE │◀─────────────────────────────────────────│EVALUATE │   │
│     │         │                                          │         │   │
│     └────┬────┘                                          └────▲────┘   │
│          │                                                    │        │
│          │  Generate dataset                    Semantic diff │        │
│          │  (template + BDD)                    + XAI rubric  │        │
│          │                                                    │        │
│          ▼                                                    │        │
│     ┌─────────┐                                          ┌────┴────┐   │
│     │         │                                          │         │   │
│     │  LEARN  │─────────────────────────────────────────▶│   ACT   │   │
│     │         │                                          │         │   │
│     └────┬────┘                                          └────▲────┘   │
│          │                                                    │        │
│          │  Train/fine-tune VLM              Execute actions │        │
│          │                                   via browser      │        │
│          │                                                    │        │
│          ▼                                                    │        │
│     ┌─────────┐                                               │        │
│     │         │                                               │        │
│     │  PLAN   │───────────────────────────────────────────────┘        │
│     │         │                                                        │
│     └─────────┘                                                        │
│          │                                                             │
│          │  Select next BDD                                            │
│          │  scenario (curriculum)                                      │
│          │                                                             │
│                                                                        │
│  ══════════════════════════════════════════════════════════════════   │
│                                                                        │
│  OBSERVE: Capture screenshots, generate SoM/ToM annotations           │
│  LEARN:   Train vision-language model on accumulated data             │
│  PLAN:    Select next challenge from curriculum                        │
│  ACT:     Execute browser actions on NiFi canvas                      │
│  EVALUATE: Compare result to ground truth via API                     │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Curriculum Progression Logic

```python
# src/gaius/agents/metaagent/curriculum.py

class CurriculumManager:
    """Manages agent progression through BDD curriculum."""

    def __init__(self, db: Database):
        self.db = db

    async def get_next_scenario(
        self,
        agent_version_id: str
    ) -> Optional[BDDScenario]:
        """Select next scenario based on agent performance."""

        # Get agent's current level
        stats = await self._get_agent_stats(agent_version_id)
        current_level = stats.current_level
        level_accuracy = stats.level_accuracy

        # Check if ready to advance
        if level_accuracy >= LEVEL_THRESHOLDS[current_level]:
            # Advance to next level
            next_level = current_level + 1
            if next_level > MAX_LEVEL:
                return None  # Curriculum complete

            await self._record_level_advancement(agent_version_id, next_level)
            current_level = next_level

        # Select scenario from current level
        # Prefer scenarios not yet attempted, then failed ones
        scenario = await self._select_scenario(
            agent_version_id,
            level=current_level
        )

        return scenario

    async def record_attempt(
        self,
        agent_version_id: str,
        scenario_id: str,
        success: bool,
        accuracy: float
    ) -> None:
        """Record scenario attempt result."""

        await self.db.execute("""
            INSERT INTO bdd_scenario_runs
            (scenario_id, agent_version_id, status, overall_accuracy)
            VALUES ($1, $2, $3, $4)
        """, scenario_id, agent_version_id,
             'passed' if success else 'failed', accuracy)

        # Update agent stats
        await self._update_agent_stats(agent_version_id)


LEVEL_THRESHOLDS = {
    1: 0.95,  # Must achieve 95% on Level 1 to advance
    2: 0.90,
    3: 0.85,
    4: 0.75,
    5: 0.65,
}
```

### 9.3 Integration with Evolution Daemon

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    EVOLUTION INTEGRATION                                │
│                                                                         │
│  Existing Evolution Daemon:                                            │
│  ══════════════════════════                                             │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  evolution_daemon.py                                            │   │
│  │                                                                 │   │
│  │  • Monitors GPU utilization                                     │   │
│  │  • Triggers agent optimization when idle                        │   │
│  │  • Uses held-out evaluation set                                 │   │
│  │  • APO/GEPA prompt optimization                                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    │ Extend with                        │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  BDD Evaluation Integration                                     │   │
│  │                                                                 │   │
│  │  • BDD scenarios as held-out evaluation                        │   │
│  │  • Grounded accuracy as optimization metric                    │   │
│  │  • Curriculum-aware agent selection                            │   │
│  │  • Successful runs feed back to training data                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Evolution Cycle (Enhanced):                                           │
│  ═══════════════════════════                                            │
│                                                                         │
│  1. Select agent for optimization (browser_agent, flow_agent, etc.)   │
│  2. Generate candidate prompts via APO                                 │
│  3. Evaluate candidates on BDD scenarios (grounded!)                  │
│  4. Select best candidate based on semantic accuracy                   │
│  5. If improved, promote to active                                     │
│  6. Convert successful runs to training data                           │
│  7. Trigger fine-tuning if sufficient new data                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Implementation Phases

### Phase 1: Foundation (Complete)

**Status**: ✅ Delivered 2025-12-19

| Deliverable | Status | Notes |
|-------------|--------|-------|
| NiFi SoM/ToM Generator | ✅ | 6,351 lines, 16 modules |
| DatasetService gRPC | ✅ | Priority queue, streaming |
| gaius-dataset CLI | ✅ | submit/status/cancel/lineage |
| NiFi REST Client | ✅ | Async httpx |
| meta.* Schema | ✅ | 10 analytics tables |
| Fail-fast Infrastructure | ✅ | Guru Meditation codes |
| XAI Calibration | ✅ | 6-dimension rubric |

### Phase 2: BDD Framework (Next)

**Target**: 2025-01 (4 weeks)

| Week | Deliverables |
|------|--------------|
| 1 | BDD schema migration, ScenarioLoader, basic step definitions |
| 2 | StateComparator, SemanticDiff, NiFiStateManager |
| 3 | ScenarioRunner, ActionTracer, result recording |
| 4 | Level 1-2 scenarios, CLI integration, documentation |

**Exit Criteria**:
- [ ] 20+ BDD scenarios across Levels 1-2
- [ ] Full evaluation pipeline functional
- [ ] CLI commands: `gaius-bdd run`, `gaius-bdd status`, `gaius-bdd report`
- [ ] Integration tests passing

### Phase 3: Browser Agent (Following)

**Target**: 2025-02 (4 weeks)

| Week | Deliverables |
|------|--------------|
| 1 | BrowserAgent interface, ActionExecutor (Selenium) |
| 2 | VLM integration (use existing model or API) |
| 3 | Level 3 scenarios, curriculum manager |
| 4 | BDD-to-dataset converter, training pipeline integration |

**Exit Criteria**:
- [ ] Browser agent achieves >50% accuracy on Level 2
- [ ] Successful runs automatically converted to training data
- [ ] Curriculum progression working

### Phase 4: Learning Loop (Future)

**Target**: 2025-Q2

| Milestone | Description |
|-----------|-------------|
| Fine-tuning Pipeline | Automated fine-tuning triggered by data threshold |
| Evolution Integration | BDD accuracy as evolution metric |
| Level 4-5 Scenarios | Complex multi-step operations |
| Self-Improvement | Agent improves via curriculum without intervention |

---

## 11. API Specifications

### 11.1 gRPC Service Extensions

```protobuf
// Addition to gaius_service.proto

// BDD Evaluation Service
service BDDEvaluationService {
  // Run a single BDD scenario
  rpc RunScenario(RunScenarioRequest) returns (stream ScenarioProgress);

  // Run all scenarios at a difficulty level
  rpc RunCurriculumLevel(RunCurriculumRequest) returns (stream ScenarioProgress);

  // Get scenario run results
  rpc GetScenarioResults(GetResultsRequest) returns (ScenarioResults);

  // Convert successful runs to dataset
  rpc ExportToDataset(ExportDatasetRequest) returns (ExportDatasetResponse);
}

message RunScenarioRequest {
  string scenario_id = 1;
  string agent_version_id = 2;
  bool capture_traces = 3;
}

message ScenarioProgress {
  string run_id = 1;
  string phase = 2;  // setup, reset, execute, verify
  float progress = 3;
  string message = 4;

  // Final result (when phase = "complete")
  bool success = 5;
  float semantic_accuracy = 6;
  SemanticDiff diff = 7;
}

message SemanticDiff {
  repeated string missing_processors = 1;
  repeated string extra_processors = 2;
  repeated string missing_connections = 3;
  repeated string extra_connections = 4;
  float overall_accuracy = 5;
}

message RunCurriculumRequest {
  int32 level = 1;
  string agent_version_id = 2;
  int32 max_scenarios = 3;
}

message GetResultsRequest {
  string agent_version_id = 1;
  optional int32 level = 2;
  optional string scenario_id = 3;
}

message ScenarioResults {
  repeated ScenarioResult results = 1;

  message ScenarioResult {
    string scenario_id = 1;
    string scenario_name = 2;
    int32 level = 3;
    int32 attempts = 4;
    int32 successes = 5;
    float best_accuracy = 6;
    string last_run_id = 7;
  }
}

message ExportDatasetRequest {
  float min_accuracy = 1;
  repeated int32 levels = 2;
  string output_format = 3;  // magma, llava, raw
  string output_path = 4;
}

message ExportDatasetResponse {
  int32 entries_exported = 1;
  string output_path = 2;
  string lineage_event_id = 3;
}
```

### 11.2 CLI Commands

```bash
# BDD Scenario Management
gaius-bdd list [--level N] [--tag TAG]
gaius-bdd show <scenario-id>
gaius-bdd create --feature <path> --gherkin <path>

# BDD Execution
gaius-bdd run <scenario-id> [--agent-version ID]
gaius-bdd run-level <level> [--max N] [--agent-version ID]
gaius-bdd run-all [--levels 1,2,3] [--agent-version ID]

# Results and Reporting
gaius-bdd status <run-id>
gaius-bdd results [--agent-version ID] [--level N]
gaius-bdd report [--format html|json|markdown]

# Dataset Export
gaius-bdd export --min-accuracy 0.9 --levels 1,2,3 --format magma
```

---

## 12. Failure Modes & Remediation

### 12.1 BDD-Specific Failure Modes

| Code | Component | Failure | Remediation |
|------|-----------|---------|-------------|
| `#BDD.00000001.SCENARIONOTFOUND` | ScenarioLoader | Scenario ID not in database | Verify scenario exists: `gaius-bdd list` |
| `#BDD.00000002.NIFISTATEERROR` | NiFiStateManager | Cannot capture/compare state | `/health fix nifi` |
| `#BDD.00000003.AGENTEXECERROR` | BrowserAgent | Agent execution failed | Check agent logs, verify Selenium |
| `#BDD.00000004.SELENIUMUNAVAIL` | ActionExecutor | Selenium not available | `uv sync --extra browser` |
| `#BDD.00000005.COMPARISONFAILED` | StateComparator | State comparison error | Check NiFi API connectivity |

### 12.2 KB Heuristic Template

```markdown
# BDD Scenario Not Found

**Guru Meditation**: #BDD.00000001.SCENARIONOTFOUND

## Symptom

Error when running `gaius-bdd run <scenario-id>`:
```
Scenario 'xyz' not found in database.
```

## Cause

The specified scenario ID does not exist in the `bdd_scenarios` table.

## Observation

```python
# Check if scenario exists
result = await db.fetchone(
    "SELECT id FROM bdd_scenarios WHERE id = $1",
    scenario_id
)
if not result:
    # This is the failure
    pass
```

## Solution

1. List available scenarios:
   ```bash
   gaius-bdd list
   ```

2. If scenario should exist, check migration status:
   ```bash
   dbmate status
   ```

3. If scenario needs to be created:
   ```bash
   gaius-bdd create --feature features/nifi_basics/level_1.feature
   ```

## Health Fix

```bash
/health fix bdd
```

This will:
1. Verify database connectivity
2. Check bdd_scenarios table exists
3. Re-run migrations if needed
4. Report scenario count
```

---

## 13. Security Considerations

### 13.1 NiFi Access Control

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SECURITY ARCHITECTURE                                │
│                                                                         │
│  Development Mode (Current):                                           │
│  ═══════════════════════════                                            │
│  • NiFi runs in HTTP-only mode (no TLS)                                │
│  • No authentication required                                          │
│  • Suitable for local development only                                 │
│                                                                         │
│  Production Mode (Future):                                             │
│  ═════════════════════════                                              │
│  • TLS required for all connections                                    │
│  • Client certificate authentication                                   │
│  • API token-based access for automation                               │
│  • Audit logging for all operations                                    │
│                                                                         │
│  Agent Isolation:                                                      │
│  ════════════════                                                       │
│  • Agents operate in sandboxed process groups                          │
│  • Cannot access production flows                                      │
│  • Resource quotas (CPU, memory, queue depth)                          │
│  • Automatic cleanup after evaluation                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 13.2 Data Protection

| Data Type | Protection | Storage |
|-----------|------------|---------|
| Screenshots | May contain sensitive data | Encrypted at rest (MinIO) |
| Flow configurations | API credentials | Sanitized before storage |
| Action traces | User interactions | Anonymized for training |
| BDD results | Performance data | Access-controlled |

---

## 14. Testing Strategy

### 14.1 Test Pyramid

```
                    ┌───────────────┐
                    │   E2E Tests   │  BDD scenarios as E2E
                    │   (Slow)      │  Full pipeline verification
                    └───────┬───────┘
                            │
                ┌───────────┴───────────┐
                │   Integration Tests   │  NiFi API, gRPC, DB
                │   (Medium)            │  Component interactions
                └───────────┬───────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │           Unit Tests                  │  State comparison
        │           (Fast)                      │  Parsing, serialization
        └───────────────────────────────────────┘
```

### 14.2 Test Categories

```python
# tests/bdd/test_state_comparator.py

class TestStateComparator:
    """Unit tests for semantic state comparison."""

    def test_identical_states_match(self):
        """Identical states should have 100% accuracy."""
        state = create_test_flow_state()
        comparator = StateComparator()
        diff = comparator.compare(state, state)
        assert diff.overall_accuracy == 1.0

    def test_missing_processor_detected(self):
        """Missing processor should reduce accuracy."""
        expected = create_test_flow_state(processors=2)
        actual = create_test_flow_state(processors=1)

        comparator = StateComparator()
        diff = comparator.compare(expected, actual)

        assert len(diff.missing_processors) == 1
        assert diff.processor_accuracy == 0.5

    def test_position_ignored(self):
        """Processor position should not affect comparison."""
        state1 = create_test_flow_state(position=(0, 0))
        state2 = create_test_flow_state(position=(100, 200))

        comparator = StateComparator()
        diff = comparator.compare(state1, state2)

        assert diff.overall_accuracy == 1.0


# tests/bdd/test_scenario_runner.py

class TestScenarioRunner:
    """Integration tests for scenario execution."""

    @pytest.mark.integration
    async def test_ground_truth_setup(self, nifi_client):
        """Ground truth should be created via API."""
        runner = ScenarioRunner(nifi_client)
        scenario = load_test_scenario("simple_flow")

        await runner.setup_ground_truth(scenario)

        state = await nifi_client.get_flow_state()
        assert len(state.processors) == 2
        assert len(state.connections) == 1

    @pytest.mark.integration
    async def test_canvas_reset(self, nifi_client):
        """Canvas should be clean after reset."""
        runner = ScenarioRunner(nifi_client)

        # Setup some state
        await runner.setup_ground_truth(load_test_scenario("simple_flow"))

        # Reset
        await runner.reset_canvas()

        state = await nifi_client.get_flow_state()
        assert len(state.processors) == 0
        assert len(state.connections) == 0
```

### 14.3 BDD Self-Test

The BDD framework itself is tested using BDD:

```gherkin
# features/meta/bdd_framework.feature

Feature: BDD Framework Self-Test
  The BDD evaluation framework should correctly verify itself

  Scenario: API-created flow matches ground truth
    Given a clean NiFi canvas
    And we create a processor "Test" via API
    When we capture the flow state
    And we compare to expected state with processor "Test"
    Then the semantic accuracy should be 1.0

  Scenario: Missing processor is detected
    Given a clean NiFi canvas
    And the expected state has processor "Expected"
    When we capture the actual state (empty)
    Then the semantic diff should show missing processor "Expected"
    And the semantic accuracy should be 0.0
```

---

## 15. Appendices

### Appendix A: NiFi API Reference

Key endpoints used:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/nifi-api/flow/process-groups/{id}` | GET | Get process group details |
| `/nifi-api/process-groups/{id}/processors` | POST | Create processor |
| `/nifi-api/process-groups/{id}/connections` | POST | Create connection |
| `/nifi-api/processors/{id}` | PUT | Update processor |
| `/nifi-api/processors/{id}` | DELETE | Delete processor |
| `/nifi-api/connections/{id}` | DELETE | Delete connection |

### Appendix B: Processor Type Reference

Common processor types for BDD scenarios:

| Short Name | Full Type |
|------------|-----------|
| GetFile | `org.apache.nifi.processors.standard.GetFile` |
| PutFile | `org.apache.nifi.processors.standard.PutFile` |
| InvokeHTTP | `org.apache.nifi.processors.standard.InvokeHTTP` |
| EvaluateJsonPath | `org.apache.nifi.processors.standard.EvaluateJsonPath` |
| SplitJson | `org.apache.nifi.processors.standard.SplitJson` |
| ConsumeKafka | `org.apache.nifi.kafka.pubsub.ConsumeKafka` |
| PublishKafka | `org.apache.nifi.kafka.pubsub.PublishKafka` |

### Appendix C: Related Documents

- `docs/scratch/2025-12-19/143000_metaagent_design_roadmap.md` - Initial roadmap
- `docs/scratch/2025-12-19/143001_metaagent_vision_diagram.md` - Architecture diagrams
- `CLAUDE.md` - Fail-fast policy documentation
- `current/heuristics/gaius/engine/` - KB heuristics

### Appendix D: Glossary

| Term | Definition |
|------|------------|
| **BDD** | Behavior-Driven Development - specifications as executable tests |
| **Ground Truth** | Expected state created via API, used to verify agent behavior |
| **Semantic Diff** | Comparison of flow topology, ignoring visual layout |
| **SoM** | Set-of-Mark - visual annotation of UI elements |
| **ToM** | Theory of Mind - annotations about element purpose/function |
| **Curriculum** | Ordered sequence of scenarios with increasing difficulty |
| **Oracle** | Authoritative source of truth (NiFi API in this context) |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-19 | Gaius Team | Initial draft |

---

*This document is maintained in `docs/scratch/2025-12-19/` and will be promoted to `docs/current/` upon approval.*
