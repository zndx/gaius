# OODA Loop

Boyd's OODA (Observe-Orient-Decide-Act) loop describes competitive decision-making under uncertainty. Gaius is explicitly designed to accelerate each phase.

## The Loop in Gaius

### Observe

The grid displays current system state at a glance. Persistent homology overlays reveal structural features (H1 death loops mark feedback cycles). Curvature heatmaps show where topic clusters have clear boundaries (positive κ) versus ambiguous transitions (negative κ). Agent positions indicate where each analytical lens is focused.

**Tools**: Grid view, `/health`, `/gpu status`, overlay modes (`o`), MiniGrid Iso views

### Orient

Context-building by cycling overlays without leaving your position. The topology overlay reveals structural relationships. The geometry overlay shows curvature. The dynamics overlay shows gradient flow direction. Each overlay reframes the same data — the same position means something different in each frame.

The MiniGrids provide three orthographic projections centered on the cursor, updated with each movement. Scalar fields (curvature κ, persistence π, complexity σ, boundary β) are interpolated via IDW and rendered as elevation maps.

**Tools**: Overlay cycling (`o`), `/search`, `/sitrep`, MiniGrid projections, Iso mode cycling

### Decide

Slash commands, domain changes, and focus actions translate understanding into intent. Tenuki (`t`) jumps the cursor to a strategically significant position — borrowed from Go, where playing away from the current fight is sometimes the strongest move.

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
