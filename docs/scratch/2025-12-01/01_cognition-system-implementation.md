# Cognition System Implementation

**Date:** 2025-12-01
**Feature:** "What Have You Been Thinking About?"

## Overview

Implemented a comprehensive cognition system that enables Gaius to answer "What have you been thinking about?" on startup. The system generates thoughts between sessions, tracks research threads, and provides session continuity through handoffs.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        STARTUP GREETING                         │
│  "Good morning. While you were away, I've been thinking..."    │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   COGNITION   │   │    SESSION    │   │  REFLECTION   │
│    AGENT      │   │    MANAGER    │   │    AGENT      │
│               │   │               │   │               │
│ - Patterns    │   │ - Handoff     │   │ - Synthesis   │
│ - Connections │   │ - Open threads│   │ - Questions   │
│ - Curiosities │   │ - Interests   │   │ - Confidence  │
│ - Momentum    │   │ - Context     │   │ - Evolution   │
└───────────────┘   └───────────────┘   └───────────────┘
        │                     │                     │
        └──────────┬──────────┴──────────┬──────────┘
                   │                     │
                   ▼                     ▼
           ┌─────────────┐       ┌─────────────┐
           │   KB + DB   │       │  Inference  │
           │  (storage)  │       │  (LLM/GPU)  │
           └─────────────┘       └─────────────┘
```

## Files Created

| File | Purpose |
|------|---------|
| `db/migrations/20251201000002_cognition_memory.sql` | Schema for thoughts, sessions, threads, user interests, cognition cycles |
| `src/gaius/agents/cognition.py` | CognitionAgent with think(), pattern detection, connection finding |
| `src/gaius/core/session.py` | SessionManager with start/end/handoff, thread detection |
| `src/gaius/agents/reflection.py` | ReflectionAgent with reflect(), deep synthesis, confidence calibration |

## Files Modified

| File | Changes |
|------|---------|
| `src/gaius/agents/roles.py` | Added Synthesizer, Questioner, Metacognizer roles |
| `src/gaius/core/config.py` | Added CognitionConfig and SessionConfig dataclasses |
| `config/base.conf` | Added cognition and session HOCON settings |
| `src/gaius/app.py` | Integrated startup greeting (Zettelkasten output) |
| `src/gaius/mcp_server.py` | Added 12 new MCP tools for cognition/session/reflection |

## Key Components

### 1. CognitionAgent (`src/gaius/agents/cognition.py`)

Generates thoughts between sessions:
- **Patterns**: Detects emerging themes across content
- **Connections**: Finds cross-domain links
- **Curiosities**: Generates questions worth exploring
- **Momentum**: Tracks topics gaining attention

```python
agent = get_cognition_agent()
result = await agent.think(max_thoughts=5)
# Returns: thoughts, patterns_detected, connections_found, curiosities_generated
```

### 2. SessionManager (`src/gaius/core/session.py`)

Manages session lifecycle and continuity:
- `start_session()`: Begin session, get handoff from previous
- `end_session()`: Capture state, detect open threads
- `get_handoff()`: Generate "where we left off" summary
- Thread detection via query clustering

```python
manager = get_session_manager()
session, handoff = await manager.start_session()
```

### 3. ReflectionAgent (`src/gaius/agents/reflection.py`)

Deep, quality thinking on demand:
- `reflect(depth)`: Quick/moderate/deep synthesis
- `quick_thought(topic)`: Brief thought on specific topic
- `compare_domains()`: Cross-domain pattern analysis
- `calibrate_understanding()`: Confidence assessment

```python
agent = get_reflection_agent()
result = await agent.reflect(depth="deep")
# Returns: synthesis, questions, confidence_notes, recommendations
```

### 4. Startup Greeting

On app start, generates a Zettelkasten note at `scratch/<iso-date>/<timestamp>_thoughts.md` containing:
- Active thoughts from cognition agent
- Session handoff (where we left off)
- Quick reflection on current state
- Questions worth exploring

The note opens in the center content panel editor.

## New MCP Tools

### Cognition
- `trigger_cognition`: Run a cognition cycle
- `get_recent_thoughts`: Get active thoughts
- `what_are_you_thinking`: Synthesis of current thinking

### Session
- `start_session`: Start new session
- `end_session`: End current session
- `get_session_handoff`: Get handoff info
- `list_open_threads`: List active research threads
- `create_research_thread`: Create new thread

### Reflection
- `reflect`: Deep reflection at specified depth
- `quick_thought`: Brief thought on topic
- `compare_domains`: Cross-domain comparison
- `calibrate_understanding`: Confidence assessment

## New Swarm Roles

Added three roles for cognition/reflection:
- **Synthesizer**: Cross-domain pattern synthesis
- **Questioner**: Curiosity-driven question generation
- **Metacognizer**: Understanding quality assessment

## Configuration

New HOCON settings in `config/base.conf`:

```hocon
gaius.cognition {
  enabled = true
  content_threshold = 10       # Items before auto-cognition
  time_threshold_hours = 4     # Max hours between cycles
  max_thoughts = 20            # Active thought limit
  greeting_thoughts = 3        # Show on startup
  stale_days = 7
  use_llm = true
}

gaius.session {
  enabled = true
  gap_hours = 4                # Gap = new session
  track_threads = true
  handoff_llm = true
  max_threads = 10
}
```

## Database Schema

Tables created:
- `cognition_thoughts`: Thought stream with salience/confidence/novelty scores
- `sessions`: Session lifecycle with handoff summaries
- `research_threads`: Persistent investigations across sessions
- `user_interests`: Learned topic preferences
- `cognition_cycles`: Track when cognition runs

Helper functions:
- `time_since_last_cognition(profile)`
- `time_since_last_session(profile)`
- `archive_stale_thoughts(days_old)`

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Usage | Always rich | Every cognition cycle uses LLM for quality synthesis |
| Thread Detection | Auto-detect | Infer threads from query clustering automatically |
| Greeting Style | Zettelkasten note | Persisted to scratch/, becomes part of KB |
| Interface | Symmetric | Shared service layer; MCP and TUI equally capable |

## Next Steps

1. Run database migration: `psql -f db/migrations/20251201000002_cognition_memory.sql`
2. Test startup greeting by launching Gaius
3. Use MCP tools to test cognition/reflection
4. Consider adding scheduled cognition via pg_cron
