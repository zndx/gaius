# Gaius Database

PostgreSQL schema for state persistence, evolution tracking, cognition memory, and operational health.

## Architecture

```mermaid
graph TB
    subgraph "Extensions"
        AGE[Apache AGE<br/>Graph Queries]
        CRON[pg_cron<br/>Scheduled Jobs]
    end

    subgraph "Content Layer"
        PROFILES[profiles]
        SOURCES[feed_sources]
        CONTENT[content_items]
    end

    subgraph "Cognition Layer"
        THOUGHTS[cognition_thoughts]
        SESSIONS[sessions]
        THREADS[research_threads]
        INTERESTS[user_interests]
    end

    subgraph "Evolution Layer"
        VERSIONS[agent_versions]
        EVALS[agent_evaluations]
        CYCLES[evolution_cycles]
        HELD[held_out_queries]
    end

    subgraph "Operations Layer"
        JOBS[scheduler_jobs]
        AIOPS[aiops_events]
        MLOPS[mlops_events]
        FMEA[fmea_catalog]
    end

    subgraph "State Layer"
        GRID[grid_snapshots]
        CURRENT[current_state]
        PREFS[ui_preferences]
        HISTORY[command_history]
    end

    PROFILES --> SOURCES
    SOURCES --> CONTENT
    VERSIONS --> EVALS
    VERSIONS --> CYCLES
    AIOPS --> FMEA
    MLOPS --> FMEA
    GRID --> CURRENT
```

## Schema Overview

### Schemas

| Schema | Purpose |
|--------|---------|
| `public` | Main application tables |
| `gaius_hx` | Historical data (partitioned) |
| `ag_catalog` | Apache AGE graph catalog |

### Extensions

| Extension | Purpose |
|-----------|---------|
| `pg_cron` | Scheduled jobs (cognition, archival) |
| `age` | Graph queries for lineage tracking |

## Table Catalog

### Content Management

#### `profiles`
Knowledge base profiles for customization.

```sql
CREATE TABLE profiles (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    feed_config JSONB DEFAULT '{}',
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### `feed_sources`
Content ingestion source configuration.

```sql
CREATE TABLE feed_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    source_type source_type NOT NULL,  -- arxiv, biorxiv, rss, api, philpapers, docs, brave, philevents
    base_url TEXT NOT NULL,
    config JSONB DEFAULT '{}',
    fetch_interval_minutes INTEGER DEFAULT 60,
    active BOOLEAN DEFAULT true,
    last_fetch_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Config Examples:**
```json
{"categories": ["cs.DC"], "max_results": 50}           // arxiv
{"areas": ["epistemology", "philosophy-of-mind"]}      // philpapers
{"sitemap": true, "paths": ["/docs/", "/api/"]}        // docs
```

#### `content_items`
Fetched content with embedding references.

```sql
CREATE TABLE content_items (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES feed_sources(id),
    external_id TEXT,           -- arxiv ID, DOI, URL hash
    url TEXT,
    title TEXT NOT NULL,
    authors TEXT[],
    summary TEXT,
    content TEXT,
    content_type TEXT DEFAULT 'text/plain',
    metadata JSONB DEFAULT '{}',
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    kb_path TEXT,               -- Path in build/dev/ if written to KB
    embedding_id TEXT,          -- Qdrant point ID
    UNIQUE(source_id, external_id)
);
```

### Cognition Memory

#### `cognition_thoughts`
Background thoughts from pattern detection.

```sql
CREATE TABLE cognition_thoughts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thought_type TEXT NOT NULL,     -- pattern, connection, curiosity, momentum, observation, synthesis, self_observation
    status TEXT NOT NULL DEFAULT 'active',  -- active, surfaced, acknowledged, stale, archived
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,                   -- 1-2 sentence version
    domains TEXT[] DEFAULT '{}',
    kb_paths TEXT[] DEFAULT '{}',
    source_entries TEXT[] DEFAULT '{}',
    related_thoughts UUID[] DEFAULT '{}',
    salience FLOAT DEFAULT 0.5,     -- 0-1 importance
    confidence FLOAT DEFAULT 0.5,   -- 0-1 certainty
    novelty FLOAT DEFAULT 0.5,      -- 0-1 newness
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    surfaced_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    profile_name TEXT DEFAULT 'default',
    generator_model TEXT,
    tokens_used INTEGER DEFAULT 0,
    generation_context JSONB DEFAULT '{}'
);
```

**Thought Types:**

| Type | Description |
|------|-------------|
| `pattern` | Emerging trends across content |
| `connection` | Cross-domain links discovered |
| `curiosity` | Questions to investigate |
| `momentum` | Trending topics |
| `observation` | Notable changes detected |
| `synthesis` | Consolidated understanding |
| `self_observation` | Meta-cognition about thinking patterns |

#### `sessions`
User session tracking for continuity.

```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name TEXT NOT NULL DEFAULT 'default',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    initial_domain TEXT,
    final_domain TEXT,
    open_threads JSONB DEFAULT '[]',
    key_topics JSONB DEFAULT '[]',
    research_notes TEXT,
    metrics JSONB DEFAULT '{}',
    handoff_generated BOOLEAN DEFAULT FALSE,
    handoff_summary TEXT,
    handoff_kb_path TEXT
);
```

#### `research_threads`
Persistent open investigations across sessions.

```sql
CREATE TABLE research_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name TEXT NOT NULL DEFAULT 'default',
    topic TEXT NOT NULL,
    domain TEXT,
    status TEXT NOT NULL DEFAULT 'active',  -- active, paused, completed, abandoned
    priority TEXT DEFAULT 'normal',
    initial_query TEXT,
    goal TEXT,
    current_focus TEXT,
    queries JSONB DEFAULT '[]',
    kb_entries TEXT[] DEFAULT '{}',
    insights JSONB DEFAULT '[]',
    next_steps TEXT,
    query_count INTEGER DEFAULT 0,
    entry_count INTEGER DEFAULT 0,
    swarm_run_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_session_id UUID REFERENCES sessions(id),
    last_session_id UUID REFERENCES sessions(id)
);
```

### Agent Evolution

#### `agent_versions`
Agent configuration management and rollback.

```sql
CREATE TABLE agent_versions (
    version_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT DEFAULT 'system',
    parent_version TEXT REFERENCES agent_versions(version_id),
    is_active BOOLEAN DEFAULT FALSE,
    metrics JSONB DEFAULT '{}',
    evaluation_count INTEGER DEFAULT 0,
    avg_overall_score FLOAT DEFAULT 0.0,
    best_overall_score FLOAT DEFAULT 0.0,
    change_notes TEXT DEFAULT ''
);

-- Only one active version per agent
CREATE UNIQUE INDEX idx_agent_versions_single_active
ON agent_versions(agent_id) WHERE is_active = TRUE;
```

**Config Structure:**
```json
{
    "system_prompt": "You are a strategic leader...",
    "model": "Qwen/QwQ-32B",
    "temperature": 0.7,
    "max_tokens": 2048,
    "task_type": "reasoning",
    "optillm_technique": "mcts"
}
```

#### `agent_evaluations`
Detailed evaluation history.

```sql
CREATE TABLE agent_evaluations (
    id SERIAL PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES agent_versions(version_id),
    overall_score FLOAT NOT NULL,
    dimension_scores JSONB DEFAULT '{}',
    summary TEXT,
    strengths JSONB DEFAULT '[]',
    weaknesses JSONB DEFAULT '[]',
    improvement_suggestions JSONB DEFAULT '[]',
    task_prompt TEXT,
    agent_output TEXT,
    context TEXT,
    eval_type TEXT DEFAULT 'training',  -- training, held_out, real_world
    task_category TEXT,
    task_difficulty FLOAT,
    evaluator_model TEXT,
    tokens_used INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### `evolution_cycles`
Evolution cycle history with held-out tracking.

```sql
CREATE TABLE evolution_cycles (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    version_before TEXT REFERENCES agent_versions(version_id),
    version_after TEXT REFERENCES agent_versions(version_id),
    strategy TEXT NOT NULL,             -- apo, gepa, hybrid
    trigger_type TEXT NOT NULL,         -- idle, manual, scheduled
    success BOOLEAN NOT NULL,
    improvement_percent FLOAT DEFAULT 0.0,
    baseline_score FLOAT,
    final_score FLOAT,
    training_examples_used INTEGER DEFAULT 0,
    held_out_examples_used INTEGER DEFAULT 0,
    candidates_evaluated INTEGER DEFAULT 0,
    training_scores JSONB DEFAULT '{}',
    held_out_scores JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    preempted BOOLEAN DEFAULT FALSE,
    error TEXT
);
```

#### `held_out_queries`
Rolling window of queries not used for training.

```sql
CREATE TABLE held_out_queries (
    id SERIAL PRIMARY KEY,
    query_hash TEXT UNIQUE NOT NULL,
    input_prompt TEXT NOT NULL,
    expected_output TEXT,
    context TEXT,
    domain TEXT,
    category TEXT,
    difficulty FLOAT,
    source_type TEXT NOT NULL,  -- swarm, research, manual
    source_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    use_count INTEGER DEFAULT 0,
    excluded_from_training BOOLEAN DEFAULT TRUE,
    exclusion_reason TEXT DEFAULT 'held_out_pool'
);
```

### Job Scheduling

#### `scheduler_jobs`
Persistent inference job queue.

```sql
CREATE TABLE scheduler_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model TEXT NOT NULL,
    messages JSONB NOT NULL,
    priority job_priority NOT NULL DEFAULT 'normal',  -- critical, high, normal, low
    status job_status NOT NULL DEFAULT 'pending',     -- pending, scheduled, running, completed, failed, cancelled
    preferred_endpoint TEXT,
    assigned_endpoint TEXT,
    estimated_tokens INT DEFAULT 500,
    deadline_ms INT DEFAULT 30000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result TEXT,
    error TEXT,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    latency_ms INT DEFAULT 0,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    role TEXT,
    metadata JSONB DEFAULT '{}'
);
```

**Priority Levels:**

| Priority | Use Case |
|----------|----------|
| `critical` | User-facing, leader synthesis |
| `high` | Swarm agents |
| `normal` | Background tasks |
| `low` | Speculative inference |

### AIOps/MLOps

#### `aiops_events`
Infrastructure health events.

```sql
CREATE TABLE aiops_events (
    id SERIAL PRIMARY KEY,
    event_id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    category VARCHAR(64) NOT NULL,      -- stuck_state, gpu_error, memory_pressure, endpoint_failure
    severity aiops_severity NOT NULL,   -- low, medium, high, critical
    status aiops_status NOT NULL DEFAULT 'detected',
    endpoint VARCHAR(64),
    description TEXT NOT NULL,
    context JSONB DEFAULT '{}',
    remediation_action VARCHAR(255),
    remediation_result JSONB,
    approved_by VARCHAR(64),
    approved_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    -- FMEA columns
    failure_mode_id VARCHAR(32) REFERENCES fmea_catalog(failure_mode_id),
    runtime_severity INT CHECK (runtime_severity BETWEEN 1 AND 10),
    runtime_occurrence INT CHECK (runtime_occurrence BETWEEN 1 AND 10),
    runtime_detection INT CHECK (runtime_detection BETWEEN 1 AND 10),
    rpn_score INT CHECK (rpn_score BETWEEN 1 AND 1000)
);
```

**Status Workflow:**

```mermaid
stateDiagram-v2
    [*] --> detected
    detected --> auto_remediated: Low/Medium severity
    detected --> pending_approval: High/Critical severity
    pending_approval --> approved: User approves
    pending_approval --> rejected: User rejects
    approved --> resolved: Action succeeds
    approved --> failed: Action fails
    auto_remediated --> resolved
    failed --> detected: Retry
```

#### `mlops_events`
Model lifecycle events.

```sql
CREATE TABLE mlops_events (
    id SERIAL PRIMARY KEY,
    event_id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    category VARCHAR(64) NOT NULL,      -- model_degradation, training_failure, drift_detected, promotion
    severity aiops_severity NOT NULL,
    status aiops_status NOT NULL DEFAULT 'detected',
    agent_id VARCHAR(64),
    model_version VARCHAR(128),
    description TEXT NOT NULL,
    metrics JSONB DEFAULT '{}',
    remediation_action VARCHAR(255),
    remediation_result JSONB,
    resolved_at TIMESTAMPTZ,
    -- FMEA columns
    failure_mode_id VARCHAR(32) REFERENCES fmea_catalog(failure_mode_id),
    runtime_severity INT,
    runtime_occurrence INT,
    runtime_detection INT,
    rpn_score INT
);
```

### FMEA (Failure Mode and Effects Analysis)

#### `fmea_catalog`
Static failure mode definitions.

```sql
CREATE TABLE fmea_catalog (
    failure_mode_id VARCHAR(32) PRIMARY KEY,  -- GPU_001, VLLM_002, MQ_003
    category VARCHAR(32) NOT NULL,            -- gpu, vllm, model_quality, evolution, emergent, resource, infra
    name VARCHAR(128) NOT NULL,
    description TEXT,
    base_severity INT NOT NULL CHECK (base_severity BETWEEN 1 AND 10),
    base_occurrence INT NOT NULL CHECK (base_occurrence BETWEEN 1 AND 10),
    base_detection INT NOT NULL CHECK (base_detection BETWEEN 1 AND 10),
    detection_method VARCHAR(64),             -- health_check, metric_threshold, anomaly, manual
    detection_query TEXT,
    detection_threshold JSONB DEFAULT '{}',
    recommended_actions TEXT[],
    escalation_tier INT DEFAULT 0,            -- 0=auto, 1=agent, 2=approval
    preventive_controls TEXT[],
    detective_controls TEXT[],
    mitigative_controls TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**RPN Calculation:**

$$RPN = Severity \times Occurrence \times Detection$$

| Score Range | Risk Level | Action |
|-------------|------------|--------|
| 1-50 | Low | Monitor |
| 51-100 | Moderate | Plan remediation |
| 101-200 | High | Priority remediation |
| 201-1000 | Critical | Immediate action |

#### `fmea_occurrences`
Failure mode occurrence history for dynamic O score.

```sql
CREATE TABLE fmea_occurrences (
    id SERIAL PRIMARY KEY,
    failure_mode_id VARCHAR(32) NOT NULL REFERENCES fmea_catalog(failure_mode_id),
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    endpoint VARCHAR(64),
    context JSONB DEFAULT '{}'
);
```

#### `fmea_outcomes`
Remediation outcomes for adaptive learning.

```sql
CREATE TABLE fmea_outcomes (
    id SERIAL PRIMARY KEY,
    failure_mode_id VARCHAR(32) NOT NULL REFERENCES fmea_catalog(failure_mode_id),
    aiops_event_id INT REFERENCES aiops_events(id),
    mlops_event_id INT REFERENCES mlops_events(id),
    rpn_score INT NOT NULL,
    severity INT NOT NULL,
    occurrence INT NOT NULL,
    detection INT NOT NULL,
    action_taken VARCHAR(128),
    tier_used INT,                            -- 0, 1, or 2
    success BOOLEAN NOT NULL,
    duration_ms INT,
    downtime_seconds INT,
    sla_breach BOOLEAN DEFAULT FALSE,
    detection_lead_time_seconds INT,
    detected_by VARCHAR(32),                  -- automation, user_report, monitoring
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### `fmea_adjustments`
Context-specific S/O/D adjustments learned from outcomes.

```sql
CREATE TABLE fmea_adjustments (
    id SERIAL PRIMARY KEY,
    failure_mode_id VARCHAR(32) NOT NULL REFERENCES fmea_catalog(failure_mode_id),
    endpoint VARCHAR(64),
    hour_of_day INT CHECK (hour_of_day BETWEEN 0 AND 23),
    adjusted_severity INT CHECK (adjusted_severity BETWEEN 1 AND 10),
    adjusted_occurrence INT CHECK (adjusted_occurrence BETWEEN 1 AND 10),
    adjusted_detection INT CHECK (adjusted_detection BETWEEN 1 AND 10),
    sample_count INT DEFAULT 0,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(failure_mode_id, endpoint, hour_of_day)
);
```

### Grid State

#### `grid_snapshots`
UMAP projection history.

```sql
CREATE TABLE grid_snapshots (
    id SERIAL PRIMARY KEY,
    kb_root VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    n_documents INT,
    coverage FLOAT,
    method VARCHAR(32),         -- umap, pca
    allocations JSONB,          -- 19x19 density matrix
    tda_features JSONB,         -- Betti numbers, entropy
    generation BIGINT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### `current_state`
Cached grid state for instant TUI startup.

```sql
CREATE TABLE current_state (
    kb_root TEXT PRIMARY KEY,
    snapshot_id INT REFERENCES grid_snapshots(id) ON DELETE SET NULL,
    generation BIGINT DEFAULT 0,
    state_json JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**State JSON Structure:**
```json
{
    "documents": [...],
    "clusters": [...],
    "allocations": [[...]],
    "tda": {
        "betti_0": 15,
        "betti_1": 3,
        "persistence_entropy": 2.4
    },
    "geometry": {
        "ricci_curvature": {...}
    }
}
```

#### `ui_preferences`
Per-client UI settings.

```sql
CREATE TABLE ui_preferences (
    client_id TEXT PRIMARY KEY,
    cursor_x INT DEFAULT 9,
    cursor_y INT DEFAULT 9,
    view_mode TEXT DEFAULT 'go',
    overlay_mode TEXT DEFAULT 'none',
    iso_mode TEXT DEFAULT 'curvature',
    center_panel_mode TEXT DEFAULT 'graph',
    left_panel_visible BOOLEAN DEFAULT TRUE,
    right_panel_visible BOOLEAN DEFAULT TRUE,
    domain TEXT,
    preferences_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Activity Tracking

#### `activity_log`
User and system activity tracking.

```sql
CREATE TABLE activity_log (
    id SERIAL PRIMARY KEY,
    profile_name TEXT NOT NULL DEFAULT 'default',
    event_type activity_type NOT NULL,
    domain TEXT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Activity Types:**
- `query` - Search queries
- `domain_change` - Domain focus changes
- `swarm_run` - Multi-agent analysis
- `tda_compute` - Topological computation
- `projection` - Grid projection
- `kb_create` / `kb_update` - Knowledge base operations
- `command` - Slash commands
- `startup` / `shutdown` - Session lifecycle
- `research_complete` / `reflection_complete` - Background processing
- `evolution_cycle` - Agent evolution

## Views

### `evolution_performance`
Recent evolution cycle statistics.

```sql
CREATE VIEW evolution_performance AS
SELECT
    agent_id,
    COUNT(*) as total_cycles,
    COUNT(*) FILTER (WHERE success) as successful_cycles,
    AVG(improvement_percent) FILTER (WHERE success) as avg_improvement,
    MAX(improvement_percent) as best_improvement,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000) as avg_duration_ms,
    MAX(started_at) as last_cycle_at
FROM evolution_cycles
WHERE started_at > NOW() - INTERVAL '7 days'
GROUP BY agent_id;
```

### `eval_score_comparison`
Held-out vs training score comparison (overfitting detection).

```sql
CREATE VIEW eval_score_comparison AS
SELECT
    e.version_id,
    v.agent_id,
    AVG(e.overall_score) FILTER (WHERE e.eval_type = 'training') as training_score,
    AVG(e.overall_score) FILTER (WHERE e.eval_type = 'held_out') as held_out_score,
    COUNT(*) FILTER (WHERE e.eval_type = 'training') as training_count,
    COUNT(*) FILTER (WHERE e.eval_type = 'held_out') as held_out_count,
    AVG(e.overall_score) FILTER (WHERE e.eval_type = 'training') -
    AVG(e.overall_score) FILTER (WHERE e.eval_type = 'held_out') as overfit_gap
FROM agent_evaluations e
JOIN agent_versions v ON e.version_id = v.version_id
GROUP BY e.version_id, v.agent_id
HAVING COUNT(*) FILTER (WHERE e.eval_type = 'held_out') > 0;
```

### `active_agent_configs`
Currently active agent configurations.

```sql
CREATE VIEW active_agent_configs AS
SELECT
    agent_id,
    version_id,
    config,
    avg_overall_score,
    evaluation_count,
    created_at
FROM agent_versions
WHERE is_active = TRUE;
```

## Functions

### `update_current_state`
Atomically update state with incremented generation.

```sql
CREATE FUNCTION update_current_state(
    p_kb_root TEXT,
    p_snapshot_id INT,
    p_state_json JSONB
) RETURNS BIGINT
```

### `upsert_current_state_if_newer`
Idempotent update: only applies if incoming generation > current.

```sql
CREATE FUNCTION upsert_current_state_if_newer(
    p_kb_root TEXT,
    p_snapshot_id INT,
    p_generation BIGINT,
    p_state_json JSONB
) RETURNS BOOLEAN
```

### `archive_stale_thoughts`
Archive cognition thoughts older than N days.

```sql
CREATE FUNCTION archive_stale_thoughts(days_old INTEGER DEFAULT 7) RETURNS INTEGER
```

### `time_since_last_cognition`
Get time since last cognition cycle.

```sql
CREATE FUNCTION time_since_last_cognition(p_profile TEXT DEFAULT 'default') RETURNS INTERVAL
```

## pg_cron Jobs

Background scheduled jobs:

| Schedule | Job | Description |
|----------|-----|-------------|
| `0 * * * *` | `archive_stale_content()` | Archive old content items |
| `0 4 * * *` | `archive_stale_thoughts(7)` | Archive 7-day old thoughts |
| `*/15 * * * *` | Cognition trigger | Check if cognition should run |

## Migrations

Migrations are managed with [dbmate](https://github.com/amacneil/dbmate):

```bash
# Run pending migrations
dbmate up

# Rollback last migration
dbmate rollback

# Check status
dbmate status

# Create new migration
dbmate new description_here
```

### Migration Files

| Migration | Description |
|-----------|-------------|
| `20251130000001_initial_schema.sql` | Profiles, sources, content items |
| `20251130000002_seed_profiles_sources.sql` | Initial data |
| `20251130000003_pg_cron_jobs.sql` | Background jobs |
| `20251130000004_add_philevents.sql` | PhilEvents source type |
| `20251130000005_activity_tracking.sql` | Activity logging |
| `20251130000006_agent_versions.sql` | Agent versioning |
| `20251201000001_scheduler_jobs.sql` | Job queue |
| `20251201000002_cognition_memory.sql` | Thoughts, sessions, threads |
| `20251204000001_evolution_tracking.sql` | Evolution cycles, held-out |
| `20251207000001_cognition_self_awareness.sql` | Self-observation thoughts |
| `20251208000001_apache_age_lineage.sql` | Graph-based lineage |
| `20251210000001_routing_analytics.sql` | Request routing tracking |
| `20251212000001_thin_client_state.sql` | State caching |
| `20251214000001_evolution_periodic_tasks.sql` | Scheduled evolution |
| `20251214000002_kb_sync.sql` | KB synchronization |
| `20251214000003_aiops_tracking.sql` | AIOps/MLOps events |
| `20251215000001_fmea_catalog.sql` | FMEA catalog and tracking |

## Connection

```bash
# Default development connection
GAIUS_DATABASE_URL="postgres://gaius:gaius@localhost:5432/gaius?sslmode=disable"

# With devenv
devenv up postgres
```

## See Also

- [Parent README](../README.md) - Project overview
- [Storage README](../src/gaius/storage/README.md) - Database access layer
- [Health README](../src/gaius/health/README.md) - FMEA integration
- [Agents README](../src/gaius/agents/README.md) - Evolution tracking
