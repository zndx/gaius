# /ask and /watch Command Implementation

**Date**: 2025-12-05 23:15
**Phase**: Agentic CLI Interface

## Summary

Implemented `/ask` as the primary agentic interface and `/watch` for OTel telemetry observability. These commands provide the foundation for self-diagnosing platform issues and capturing remediations as heuristics.

## `/ask` Command - "/ask away!"

The general-purpose entry point to gaius-engine's capabilities with intelligent query routing.

### Usage

```bash
/ask <question>              # Auto-route based on query analysis
/ask --reason <question>     # Force reasoning mode (chain-of-thought)
/ask --search <question>     # Force search + synthesis mode
/ask --swarm <question>      # Force multi-agent analysis
/ask --platform <error>      # Diagnose platform issues
/ask --save                  # Save response to KB as heuristic
```

### Auto-Routing Logic

| Pattern | Mode | Description |
|---------|------|-------------|
| "error", "failed", "not found" | platform | Diagnoses issues, gathers diagnostics |
| "what is", "how does", "explain" | search | Hybrid search + synthesis |
| "analyze", "assess", "strategy" | swarm | Multi-agent domain analysis |
| Default | reasoning | Chain-of-thought reasoning |

### Modes

1. **Reasoning Mode** (`--reason`)
   - Uses `cot_reflection` technique
   - Best for logic, math, analysis
   - Returns structured step-by-step response

2. **Search Mode** (`--search`)
   - Hybrid BM25 + Vector + Web search
   - With `--save`: delegates to `/research` for Zettelkasten note
   - Without `--save`: quick synthesis

3. **Swarm Mode** (`--swarm`)
   - Invokes multiple specialist agents
   - Synthesizes perspectives
   - Domain-aware analysis

4. **Platform Mode** (`--platform`)
   - Gathers component diagnostics:
     - gaius-engine health
     - KB search status
     - Vector search (Qdrant)
     - Web search availability
   - Uses LLM for remediation advice
   - With `--save`: captures as KB heuristic

### Example: Platform Diagnostics

```json
{
  "mode": "platform",
  "diagnostics": [
    {"component": "gaius-engine", "status": "healthy"},
    {"component": "kb_search", "status": "error", "error": "No module named 'bm25s'"},
    {"component": "vector_search", "status": "error"},
    {"component": "web_search", "status": "available"}
  ],
  "response": "**Diagnosis**: Missing bm25s module...\n**Remediation**: pip install bm25s..."
}
```

## `/watch` Command - OTel Observability

Provides telemetry filtering for debugging and agent self-diagnosis.

### Usage

```bash
/watch                       # Show recent traces (default)
/watch status                # OTel collector status
/watch traces [filter]       # Watch traces with filter
/watch spans [filter]        # Watch spans with filter
/watch metrics [name]        # Watch specific metric
/watch logs [filter]         # Watch logs with filter
/watch service <name>        # Filter by service name
/watch operation <name>      # Filter by operation name
/watch clear                 # Clear watch buffers
```

### Filter Syntax

```bash
/watch traces service:gaius-engine
/watch spans operation:ask
/watch logs level:error
```

### Status Output

```json
{
  "otel_available": true,
  "otel_endpoint": "not set",
  "otel_service_name": "gaius",
  "tracer_provider": "ProxyTracerProvider",
  "engine_telemetry": {
    "connected": true,
    "services_reporting": ["orchestrator", "scheduler", "evolution", "grid", "tda"]
  }
}
```

## Integration: /ask + /watch

Agents responding to `/ask` can use `/watch` to gather telemetry:

```
User: /ask --platform why is inference slow?

Agent internally:
1. /watch metrics gpu_utilization
2. /watch traces operation:inference
3. /watch logs level:error
4. Synthesize diagnostics with telemetry context
```

## BDD Features Added

### `features/commands.feature`

- 15 scenarios for `/ask` command modes
- 12 scenarios for `/watch` command
- Covers auto-routing, flags, filters, error handling

### `features/engine.feature` (new)

- 15 scenarios for engine connectivity
- Feature flag behavior (GAIUS_ALLOW_FALLBACKS)
- Service health queries via engine
- Integration with `/ask`

## Files Modified

| File | Change |
|------|--------|
| `src/gaius/cli.py` | Added `/ask` modes, `/watch` command, help updates |
| `features/commands.feature` | Added 27 BDD scenarios |
| `features/engine.feature` | New file with 15 scenarios |

## Architecture

```
User Query
    │
    ▼
/ask (auto-route)
    │
    ├─► --platform ──► Diagnostics + LLM Remediation
    │                      │
    │                      ├── gaius-engine health
    │                      ├── kb_search status
    │                      ├── vector_search status
    │                      └── web_search status
    │
    ├─► --search ────► Hybrid Search + Synthesis
    │                      │
    │                      └── With --save: /research (Zettelkasten)
    │
    ├─► --swarm ─────► Multi-Agent Analysis
    │
    └─► --reason ────► Chain-of-Thought Reasoning

/watch (telemetry)
    │
    ├─► status ──────► OTel configuration
    ├─► traces ──────► Recent operations
    ├─► spans ───────► Span details
    ├─► metrics ─────► GPU, evolution, etc.
    └─► logs ────────► Log entries
```

## Next Steps

1. **OTel Collector Integration**: Connect `/watch` to actual OTel collector API
2. **Agent Tool Access**: Allow agents to invoke `/watch` programmatically
3. **Heuristic KB Structure**: Define schema for platform heuristics
4. **Streaming Traces**: Real-time trace streaming in TUI ThinkPanel
