# ThinkPanel Engine Integration: Signs of Life

## Summary

Updated the ThinkPanel widget to poll the engine for autonomous activity, showing "signs of life" that demonstrate the engine is continuously performing valuable work. The TUI now serves as a window into the engine's autonomous cognition, evolution, and inference activity.

## Changes

### 1. CognitionProxy (`src/gaius/client/engine_proxy.py`)

Added new proxy class for cognition service access:

```python
class CognitionProxy:
    async def get_recent_thoughts(limit: int = 10) -> list[dict]
    async def get_activity() -> dict  # Comprehensive "signs of life"
    async def get_status() -> dict
    async def trigger_cycle(max_thoughts: int, trigger_reason: str) -> dict
```

Factory function: `get_cognition_proxy()`

### 2. Engine Server (`src/gaius/engine/server.py`)

Added two new cognition actions:

- `recent_thoughts`: Returns recent thoughts from cognition agent with type, title, summary, timestamp
- `activity`: Returns comprehensive activity summary (cognition running, cycles, current task, thoughts today)

### 3. ThinkPanel Widget (`src/gaius/widgets/think_panel.py`)

Complete rewrite with engine integration:

**New Layout:**
```
+- Engine Activity ----------------------------------------+
| ● Cognition: 12 cycles, last 3m ago                     |
| ● Evolution: running, next: leader                       |
| ● GPUs: 4 endpoints, 45% util                           |
+----------------------------------------------------------+
+- Recent Thoughts ----------------------------------------+
| 14:32 pattern: recurring theme in consensus              |
| 14:28 connection: raft ↔ paxos similarity               |
| 14:15 curiosity: why does CAP limit availability?        |
+----------------------------------------------------------+
+- Local Traces -------------------------------------------+
| 14:10 swarm: pension-analysis (7 agents)                |
+----------------------------------------------------------+
```

**Features:**
- Polls engine every 5 seconds for activity
- Shows cognition daemon status (running/stopped, cycle count, last activity)
- Shows evolution daemon status (running/stopped, cycle count, next agent)
- Shows GPU/endpoint status (healthy endpoints, utilization)
- Displays recent thoughts from cognition agent with types (pattern, connection, curiosity, etc.)
- Still shows local traces from TUI-initiated operations

**Visual Indicators:**
- Panel title shows engine health: `◉ Think` (green) or `○ Think` (red)
- Panel border color: cyan (healthy) or red (unhealthy)
- Status indicators: `●` (running/healthy) or `○` (stopped/unhealthy)

### 4. EngineActivity Dataclass

New dataclass to cache engine activity state:

```python
@dataclass
class EngineActivity:
    cognition_running: bool
    cycles_completed: int
    last_cycle_at: Optional[datetime]
    current_task: Optional[str]
    evolution_running: bool
    evolution_cycles: int
    next_agent: Optional[str]
    thoughts: list[dict]
    engine_healthy: bool
    endpoints_running: int
    gpu_utilization: float
    last_update: Optional[datetime]
    update_error: Optional[str]
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ TUI (GaiusApp)                                              │
│                                                             │
│  ThinkPanel                                                 │
│  ├─ Polls every 5s                                         │
│  ├─ Shows engine "signs of life"                           │
│  └─ Falls back to local traces if engine unavailable       │
└─────────────────────────────────────────────────────────────┘
              ↓ gRPC
┌─────────────────────────────────────────────────────────────┐
│ Engine (gaius-engine)                                       │
│                                                             │
│  CognitionService                                          │
│  ├─ Runs cognition cycles autonomously                     │
│  ├─ Generates thoughts (patterns, connections, curiosity)  │
│  └─ Records to database                                    │
│                                                             │
│  EvolutionService                                          │
│  ├─ Runs agent optimization cycles                         │
│  └─ Improves agent prompts over time                       │
│                                                             │
│  HealthService                                             │
│  ├─ Monitors GPU health                                    │
│  └─ Tracks endpoint status                                 │
└─────────────────────────────────────────────────────────────┘
```

## Usage

The ThinkPanel automatically polls when mounted. Press `g` to cycle through center panel modes and view the Think panel.

When the engine is running:
- Green indicators show active services
- Recent thoughts appear in real-time
- GPU/endpoint status updates automatically

When the engine is not running:
- Red indicators and "Engine not running" message
- Local traces still displayed from TUI operations

## Key Message

The TUI is now explicitly a *window into* the engine's autonomous activity, not the source of that activity. The engine performs valuable work continuously, and the TUI simply provides visibility and the ability to guide that work's direction.
