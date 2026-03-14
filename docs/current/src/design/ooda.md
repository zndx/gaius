# OODA Loop

Boyd's OODA (Observe-Orient-Decide-Act) loop describes competitive decision-making under uncertainty. Gaius is explicitly designed to accelerate each phase.

## The Loop in Gaius

### Observe

The grid displays current system state. Health checks, agent positions, and topology overlays provide immediate perception without requiring sequential reading.

**Tools**: Grid view, `/health`, `/gpu status`, overlay modes

### Orient

Context-building through overlays, memory search, and agent analysis. Multiple perspectives (risk, topology, temporal) help frame observations.

**Tools**: Overlay cycling (`o`), `/search`, `/sitrep`, MiniGrid projections

### Decide

Slash commands, domain changes, and focus actions translate understanding into intent.

**Tools**: Command input (`/`), tenuki (`t`), mode cycling (`v`)

### Act

Execute decisions: run analysis, apply fixes, export insights, trigger evolution.

**Tools**: `/health fix`, `/evolve trigger`, `/render`, `/swarm`

## Fast OODA Wins

The competitive advantage of OODA comes from cycle speed. Gaius minimizes latency at every stage:

- **Observe**: Grid renders state instantly (no loading, no scrolling)
- **Orient**: Overlays toggle without delay (pre-computed)
- **Decide**: Keyboard-first eliminates mouse targeting time
- **Act**: Engine RPCs execute in <30s (most <1s)

## OODA for Autonomous Agents

The same loop applies to Gaius's autonomous systems:

| Phase | Health Observer | Evolution Daemon |
|-------|---------------|-----------------|
| Observe | Health checks | GPU utilization monitoring |
| Orient | FMEA risk scoring | Agent performance evaluation |
| Decide | Tier selection (0/1/2) | Candidate ranking |
| Act | Remediation or escalation | Promote or discard |

## Fail Open Supports Observation

The [fail open](../concepts/fail-fast.md) principle directly supports the Observe phase: by surfacing unknown states rather than hiding them, it ensures the OODA loop always has complete visibility.
