# M2: Think Mode + enterApp Implementation

## Summary

Completed Milestone 2 of the Gaius v1.0 roadmap, implementing reasoning observability and configurable startup.

## Deliverables Completed

### 1. Think Mode (CenterPanelMode cycling)

**Changes to `src/gaius/core/state.py`:**
- Added `CenterPanelMode` enum: GRAPH, THINK, NONE
- Added `ReasoningTrace` dataclass for capturing inference/search traces
- Extended `AppState` with:
  - `center_panel_mode`: Current center panel mode
  - `active_reasoning`: Current reasoning text being displayed
  - `reasoning_traces`: History of reasoning traces (max 50)
- Added `cycle_center_panel_mode()` method for 'g' key cycling
- Added `add_reasoning_trace()` and `set_active_reasoning()` methods

**Created `src/gaius/widgets/think_panel.py`:**
- `ThinkPanel` widget (40x21, same size as GraphView)
- Two-section layout:
  - **Active Reasoning**: Real-time inference stream (top)
  - **Recent Traces**: Condensed trace history (bottom)
- Color-coded operation types (search=blue, synthesis=green, inference=yellow, swarm=magenta)
- Methods: `stream_reasoning()`, `complete_trace()`, `clear_active()`

**Updated `src/gaius/app.py`:**
- `g` key now cycles: GRAPH → THINK → NONE → GRAPH
- Status bar shows current center panel mode with color coding
- `action_toggle_graph()` manages visibility of GraphView and ThinkPanel

### 2. enterApp Startup Procedure

**App initialization changes:**
- `GaiusApp.__init__()` now accepts `profile` argument
- Loads HOCON config via `get_config(profile=profile)`
- `_apply_config()` applies UI state from HOCON config
- `on_mount()` runs `_run_startup_commands()` and shows situational summary

**Startup procedure:**
- Reads `gaius.startup.commands` from HOCON config
- Executes commands in order on app start
- Shows situational awareness summary if `show_situational = true`
- Profile-specific startup sequences (e.g., weathership sets domain to "research")

**CLI enhancement:**
- `uv run gaius --profile weathership` loads specific profile

### 3. OpenTelemetry Foundation

**Created `src/gaius/core/telemetry.py`:**
- OpenTelemetry facade with NoOp fallbacks when OTel not installed
- `get_tracer()`, `get_meter()` functions
- `@trace_operation()` decorator for tracing functions
- Pre-defined metrics:
  - `gaius.search.count` - Search operations counter
  - `gaius.inference.count` - Inference calls counter
  - `gaius.inference.latency` - Inference latency histogram
  - `gaius.swarm.rounds` - Swarm round counter
- Convenience functions: `record_search()`, `record_inference()`, `record_swarm_round()`
- Initialized from config via `init_from_config()`

**Config support:**
- HOCON `gaius.telemetry.*` section controls:
  - `enabled`: Enable/disable telemetry
  - `exporter`: "console" or "otlp"
  - `endpoint`: OTLP collector endpoint
  - `service_name`: Service identifier

## Files Modified

| File | Changes |
|------|---------|
| `src/gaius/core/state.py` | Added CenterPanelMode, ReasoningTrace, state methods |
| `src/gaius/widgets/__init__.py` | Export ThinkPanel |
| `src/gaius/widgets/think_panel.py` | **NEW** - Think panel widget |
| `src/gaius/core/telemetry.py` | **NEW** - OpenTelemetry facade |
| `src/gaius/core/__init__.py` | Export telemetry functions |
| `src/gaius/app.py` | Profile loading, enterApp, g-key cycling |

## Usage

```bash
# Run with default profile
uv run gaius

# Run with specific profile
uv run gaius --profile weathership

# Press 'g' to cycle: graph → think → none
```

## Next Steps (M3)

M3: Real Grid Data + TDA includes:
1. Projection pipeline (UMAP/PCA)
2. TDA integration (giotto-tda)
3. KB → Grid feedback loop
4. Background TDA computation worker

## Design Decisions Applied

1. **Think panel replaces GraphView space** - same 40x21 dimensions, 'g' cycles modes
2. **DB + HOCON sync** - Database is source of truth, HOCON provides defaults
3. **NoOp telemetry fallbacks** - Graceful degradation if OTel not installed
