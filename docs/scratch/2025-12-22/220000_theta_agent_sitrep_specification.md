# ThetaAgent SITREP Specification

## Overview

The SITREP (Situational Report) is ThetaAgent's core deliverable: a time-horizon-aware situational awareness document optimized for human factors. It synthesizes the **Arrow-Target-Action** model with **Attention Schema Theory** and **hippocampal theta dynamics** to provide actionable intelligence for strategic attention allocation.

## Theoretical Foundation

### The Attention Schema for Action Allocation

Following [Graziano's Attention Schema Theory](https://pmc.ncbi.nlm.nih.gov/articles/PMC4407481/), the SITREP constructs an internal model of your attention allocation—not just *what* you're attending to, but a schematic representation of *how* your finite action pool is distributed across the effect-space.

The S+A+V framework maps to:

| AST Component | Arrow-Target Mapping | SITREP Function |
|---------------|---------------------|-----------------|
| **S** (Self) | Agent with finite action pool | "You have N actions remaining" |
| **A** (Attention) | Current allocation across arrows | "Your attention is distributed as..." |
| **V** (Stimulus) | Arrow-target landscape | "The effect-space contains..." |

### Theta Dynamics for Temporal Organization

The SITREP leverages theta wave principles for temporal structure:

| Theta Mode | SITREP Section | Function |
|------------|----------------|----------|
| **Low theta (2-5 Hz)** | Exploration Scan | Surface new opportunities, anomalies |
| **High theta (6-10 Hz)** | Navigation Focus | Goal-directed status on active arrows |
| **Theta-gamma coupling** | Integration Layer | Bind details to strategic context |
| **Sharp-wave ripple** | Consolidation Summary | Crystallize key decisions |

### Time Horizons

| Horizon | Cycle | Primary Concern | Action Granularity |
|---------|-------|-----------------|-------------------|
| **Day** | θ-day | Tactical execution | Individual nudges |
| **Week** | θ-week | Sprint objectives | Arrow velocity adjustments |
| **Quarter** | θ-quarter | Strategic initiatives | Target placement, new arrows |
| **Open** | θ-∞ | Emergent possibilities | Landscape evolution |

## SITREP Structure

### Header Block

```
╔══════════════════════════════════════════════════════════════════════╗
║  SITREP                                                              ║
║  ══════                                                              ║
║  Horizon: [DAY | WEEK | QUARTER | OPEN]                              ║
║  Generated: YYYY-MM-DD HH:MM                                         ║
║  Theta Phase: [EXPLORATION | NAVIGATION | CONSOLIDATION | REPLAY]    ║
║                                                                      ║
║  Action Pool: ████████░░░░░░░░░░░░ 40% remaining (8 of 20)          ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Section 1: Effect-Space Overview (Low Theta - Exploration)

The broadest scan of the arrow-target landscape. Surfaces:
- Total arrows in flight
- Targets by status (on-track, drifting, at-risk, achieved)
- New signals requiring attention
- Anomalies and unexpected developments

```
┌─────────────────────────────────────────────────────────────────────┐
│  EFFECT-SPACE OVERVIEW                                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Arrows in Flight: 12                                               │
│  ├── On Track:     7  ████████████████░░░░  58%                    │
│  ├── Drifting:     3  ██████░░░░░░░░░░░░░░  25%                    │
│  ├── At Risk:      1  ██░░░░░░░░░░░░░░░░░░   8%                    │
│  └── Achieved:     1  ██░░░░░░░░░░░░░░░░░░   8%                    │
│                                                                     │
│  Targets:          15                                               │
│  ├── Fixed:        9                                                │
│  ├── Moving:       4                                                │
│  └── New:          2                                                │
│                                                                     │
│  ⚡ SIGNALS                                                         │
│  • [HIGH] External dependency shifted for Arrow-7                   │
│  • [MED]  New opportunity emerged in Quadrant-NE                    │
│  • [LOW]  Arrow-3 ahead of schedule                                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Section 2: Priority Trajectories (High Theta - Navigation)

Focused detail on arrows requiring immediate attention. For each:

```
┌─────────────────────────────────────────────────────────────────────┐
│  PRIORITY TRAJECTORIES                                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ▶ ARROW-7: "Q1 Product Launch"                    [AT RISK]       │
│    ─────────────────────────────────────────────────────────────   │
│    Trajectory: ══════════○═══════▶  ◎ ← target drifted            │
│    Drift:      +15° from optimal vector                            │
│    ETA:        2025-01-15 → 2025-01-28 (slipped 13d)              │
│    Cause:      External vendor delay (outside force)               │
│    ┌────────────────────────────────────────────────────────────┐  │
│    │ RECOMMENDED ACTIONS (cost in action units)                 │  │
│    │ ① Nudge arrow: Accelerate internal workstream      [2 AU] │  │
│    │ ② Move target: Descope to core features            [1 AU] │  │
│    │ ③ Fire new:    Parallel vendor track               [4 AU] │  │
│    └────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ▶ ARROW-2: "Infrastructure Migration"             [DRIFTING]     │
│    ─────────────────────────────────────────────────────────────   │
│    Trajectory: ════════════════○══▶    ◎                          │
│    Drift:      -8° (slower than planned)                           │
│    ETA:        2025-02-01 (on schedule despite drift)              │
│    Cause:      Resource contention with Arrow-7                    │
│    ┌────────────────────────────────────────────────────────────┐  │
│    │ RECOMMENDED ACTIONS                                        │  │
│    │ ① No action needed - self-correcting trajectory            │  │
│    │ ② Optional: Small nudge post-Arrow-7 resolution    [1 AU] │  │
│    └────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Section 3: Attention Allocation Model (Theta-Gamma Coupling)

The attention schema itself—a model of where your attention *is* vs. where it *should be*:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ATTENTION ALLOCATION                                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Current Allocation          Recommended Allocation                 │
│  ───────────────────         ───────────────────────                │
│  Arrow-7:  35% ████████      Arrow-7:  45% ██████████ (+10%)       │
│  Arrow-2:  25% █████         Arrow-2:  15% ███       (-10%)        │
│  Arrow-5:  20% ████          Arrow-5:  20% ████      (──)          │
│  Arrow-9:  10% ██            Arrow-9:  10% ██        (──)          │
│  Scatter:  10% ██            Explore:   5% █         (-5%)         │
│                              Reserve:   5% █         (+5%)         │
│                                                                     │
│  ATTENTION DRIFT DETECTED                                           │
│  • Arrow-2 is over-allocated relative to urgency                    │
│  • Arrow-7 is under-allocated relative to risk                      │
│  • Scatter (unfocused) consuming productive capacity                │
│                                                                     │
│  SCHEMA HEALTH: ▓▓▓▓▓▓▓░░░ 70%                                     │
│  (How well current allocation matches strategic priorities)         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Section 4: Decision Points (Sharp-Wave Ripple - Consolidation)

Crystallized action recommendations requiring commitment:

```
┌─────────────────────────────────────────────────────────────────────┐
│  DECISION POINTS                                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ DECISION 1: Arrow-7 Intervention                     [3 AU] │  │
│  │ ──────────────────────────────────────────────────────────── │  │
│  │ Without intervention: 73% chance of miss                     │  │
│  │ With recommended nudge: 89% chance of hit                    │  │
│  │                                                               │  │
│  │ Trade-off: Delays Arrow-2 by ~1 week                         │  │
│  │                                                               │  │
│  │ [ ] APPROVE   [ ] MODIFY   [ ] DEFER                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ DECISION 2: New Arrow - Market Opportunity           [2 AU] │  │
│  │ ──────────────────────────────────────────────────────────── │  │
│  │ Signal detected: Competitor weakness in Segment-X            │  │
│  │ Window: ~6 weeks before market adjusts                       │  │
│  │ Required: Fire new arrow now, allocate 2 AU/week             │  │
│  │                                                               │  │
│  │ Opportunity cost: Reduces reserve capacity                   │  │
│  │                                                               │  │
│  │ [ ] FIRE   [ ] QUEUE   [ ] IGNORE                            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ TENUKI RECOMMENDATION                                        │  │
│  │ ──────────────────────────────────────────────────────────── │  │
│  │ Consider: Move attention entirely away from Arrow-9          │  │
│  │ Rationale: Low strategic value, consuming 10% of pool        │  │
│  │ Action: Let arrow fly unattended or explicitly abandon       │  │
│  │                                                               │  │
│  │ [ ] ABANDON   [ ] AUTOPILOT   [ ] MAINTAIN                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Section 5: Horizon-Specific Views

#### θ-Day (Daily SITREP)

```
┌─────────────────────────────────────────────────────────────────────┐
│  TODAY'S ACTION QUEUE                                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Available Actions: 8 AU                                            │
│  Committed:         5 AU                                            │
│  Discretionary:     3 AU                                            │
│                                                                     │
│  COMMITTED                                                          │
│  ──────────                                                         │
│  09:00  [2 AU]  Arrow-7: Vendor escalation call                    │
│  14:00  [2 AU]  Arrow-5: Architecture review                       │
│  16:00  [1 AU]  Arrow-2: Status sync                               │
│                                                                     │
│  DISCRETIONARY RECOMMENDATIONS                                      │
│  ─────────────────────────────                                      │
│  Priority 1: [1 AU] Nudge Arrow-7 (draft contingency plan)         │
│  Priority 2: [1 AU] Exploration scan of Quadrant-NE signal         │
│  Priority 3: [1 AU] Reserve for emergent needs                     │
│                                                                     │
│  ENERGY FORECAST                                                    │
│  ────────────────                                                   │
│  Morning:   ████████████████░░░░  High (peak cognitive)            │
│  Afternoon: ████████████░░░░░░░░  Moderate                         │
│  Evening:   ████░░░░░░░░░░░░░░░░  Low (avoid decisions)            │
│                                                                     │
│  → Schedule Decision 1 (Arrow-7) for morning peak                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### θ-Week (Weekly SITREP)

```
┌─────────────────────────────────────────────────────────────────────┐
│  WEEKLY TRAJECTORY REVIEW                                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Week: 2025-W52 (Dec 23-29)                                        │
│  Theme: "Stabilization before EOY"                                  │
│                                                                     │
│  ACTION BUDGET                                                      │
│  ─────────────                                                      │
│  Total:     40 AU                                                   │
│  Allocated: 32 AU                                                   │
│  Reserve:    8 AU (20% - healthy)                                  │
│                                                                     │
│  VELOCITY CHANGES THIS WEEK                                         │
│  ──────────────────────────                                         │
│  Arrow-7:  ↓ Decelerated (blocked)                                 │
│  Arrow-2:  → Steady                                                 │
│  Arrow-5:  ↑ Accelerated (breakthrough)                            │
│  Arrow-9:  ↓ Stalled (awaiting decision)                           │
│                                                                     │
│  WEEK-OVER-WEEK DRIFT                                               │
│  ─────────────────────                                              │
│  Effect-space entropy: +12% (more uncertainty)                      │
│  Attention coherence:  -8%  (more scattered)                        │
│  Target stability:     +5%  (fewer moves needed)                    │
│                                                                     │
│  RECOMMENDED WEEKLY THEME                                           │
│  ─────────────────────────                                          │
│  "Unblock Arrow-7, coast Arrow-2, harvest Arrow-5"                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### θ-Quarter (Quarterly SITREP)

```
┌─────────────────────────────────────────────────────────────────────┐
│  QUARTERLY STRATEGIC REVIEW                                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Quarter: 2025-Q1                                                   │
│  Strategic Intent: "Foundation for scale"                          │
│                                                                     │
│  ARROW PORTFOLIO                                                    │
│  ───────────────                                                    │
│  Active:     8 arrows                                               │
│  Completed:  3 arrows (Q4 carryover)                               │
│  Abandoned:  1 arrow  (strategic pivot)                            │
│  Planned:    4 arrows (Q1 initiatives)                             │
│                                                                     │
│  TARGET LANDSCAPE EVOLUTION                                         │
│  ──────────────────────────                                         │
│  Fixed targets:    12 → 9  (3 achieved)                            │
│  Moving targets:    4 → 6  (2 emerged from uncertainty)            │
│  New targets:       0 → 3  (market signals)                        │
│                                                                     │
│  ATTENTION SCHEMA HEALTH (90-day trend)                            │
│  ────────────────────────────────────────                          │
│  Coherence:  ████████████████░░░░  80% → 72% (declining)           │
│  Efficiency: ████████████░░░░░░░░  60% → 68% (improving)           │
│  Foresight:  ██████████████░░░░░░  70% → 75% (improving)           │
│                                                                     │
│  STRATEGIC REBALANCING NEEDED                                       │
│  ─────────────────────────────                                      │
│  • Too many arrows in flight (cognitive overload risk)             │
│  • Consider: Consolidate Arrow-8 and Arrow-11 (similar targets)    │
│  • Consider: Explicit abandonment of Arrow-9 (low ROI)             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### θ-∞ (Open Horizon SITREP)

```
┌─────────────────────────────────────────────────────────────────────┐
│  OPEN HORIZON SCAN                                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Mode: Exploration (Low Theta)                                      │
│  Scope: Unbounded temporal horizon                                  │
│                                                                     │
│  EMERGENT PATTERNS                                                  │
│  ─────────────────                                                  │
│  • Three arrows are converging on adjacent targets                  │
│    → Potential for consolidation into single strategic thrust      │
│                                                                     │
│  • Recurring target drift in Quadrant-SE                           │
│    → Suggests structural instability in that domain                │
│    → Consider: Is this domain worth continued investment?          │
│                                                                     │
│  • Action efficiency declining over 6-month trend                  │
│    → More AU required per unit progress                            │
│    → Possible causes: scope creep, environmental resistance        │
│                                                                     │
│  PHASE SPACE TOPOLOGY                                               │
│  ─────────────────────                                              │
│  Attractors:   2 stable (core business), 1 emerging (new market)   │
│  Repellors:    1 (regulatory constraint zone)                      │
│  Saddle points: 3 (decision forks requiring commitment)            │
│                                                                     │
│  LONG-WAVE SIGNALS                                                  │
│  ─────────────────                                                  │
│  • Technology shift may obsolete Arrow-4's target (18-24 months)   │
│  • Demographic trend favors Arrow-6's domain (3-5 years)           │
│  • Competitive landscape suggests new arrow opportunity (6 months) │
│                                                                     │
│  EXISTENTIAL CONSIDERATIONS                                         │
│  ───────────────────────────                                        │
│  "What arrows should exist that don't yet?"                        │
│  "What targets should be abandoned despite sunk cost?"             │
│  "Where is the effect-space itself evolving?"                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Human Factors Integration

### Cognitive Load Management

The SITREP adapts its density based on detected or declared cognitive state:

| State | Theta Analog | SITREP Mode |
|-------|--------------|-------------|
| **High Focus** | High theta (navigation) | Minimal: Priority trajectories only |
| **Planning** | Low theta (exploration) | Full: All sections, maximum detail |
| **Fatigued** | Pre-ripple (consolidation) | Summary: Decisions only, defer detail |
| **Recovery** | Sharp-wave ripple | Replay: What happened, what consolidated |

### Attention Schema Warnings

The SITREP explicitly models attention allocation failures:

```
⚠ ATTENTION SCHEMA WARNINGS
────────────────────────────
• SCATTER DETECTED: 15% of actions going to untracked micro-tasks
• STALE ALLOCATION: Arrow-9 unchanged for 3 weeks despite drift
• OVER-FOCUS: Arrow-7 consuming 40% but only 20% of value
• BLIND SPOT: No attention on Quadrant-NE for 2 weeks
```

### Theory of Mind (Others' Attention)

Following AST's insight that the same mechanism models both self and other attention:

```
STAKEHOLDER ATTENTION MAP
─────────────────────────
• Board:      Focused on Arrow-7, unaware of Arrow-5 progress
• Team:       Scattered across all arrows, seeking prioritization
• Partners:   Attention drifting from Arrow-2 (they perceive delay)
• Market:     Not yet attending to our Arrow-6 (opportunity window)

RECOMMENDED COMMUNICATION
• Proactively update Board on Arrow-5 (shift their attention)
• Provide Team with clear Arrow-7 priority signal
• Re-engage Partners on Arrow-2 timeline
```

## Implementation Architecture

### Data Sources

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ThetaAgent Data Integration                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  KB (Gaius)                                                         │
│  ├── Projects (arrows)                                              │
│  ├── Objectives (targets)                                           │
│  ├── Activities (actions)                                           │
│  └── Signals (external forces)                                      │
│                                                                     │
│  Calendar / Task Systems                                            │
│  ├── Committed actions                                              │
│  ├── Time allocation                                                │
│  └── Energy patterns                                                │
│                                                                     │
│  Lineage Graph (MetaAgent)                                          │
│  ├── Dependency chains                                              │
│  ├── Causal relationships                                           │
│  └── Information flow                                               │
│                                                                     │
│  External Signals                                                   │
│  ├── Market data                                                    │
│  ├── Stakeholder communications                                     │
│  └── Environmental changes                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Generation Pipeline

```python
class ThetaAgent:
    """SITREP generation with attention schema modeling."""

    def generate_sitrep(
        self,
        horizon: Horizon,  # DAY | WEEK | QUARTER | OPEN
        theta_mode: ThetaMode = None,  # Auto-detect if not specified
        cognitive_state: CognitiveState = None,
    ) -> SITREP:
        # 1. Gather effect-space state
        arrows = self.kb.get_active_initiatives()
        targets = self.kb.get_objectives()
        actions = self.calendar.get_action_pool(horizon)

        # 2. Compute trajectories and drift
        trajectories = [
            self.compute_trajectory(arrow, target)
            for arrow, target in self.match_arrows_targets(arrows, targets)
        ]

        # 3. Build attention schema
        current_allocation = self.infer_attention_allocation(actions)
        recommended_allocation = self.optimize_allocation(
            trajectories,
            actions.remaining,
            horizon
        )
        schema_health = self.compute_schema_health(
            current_allocation,
            recommended_allocation
        )

        # 4. Generate decisions
        decisions = self.crystallize_decisions(
            trajectories,
            actions.remaining,
            horizon
        )

        # 5. Apply human factors adaptation
        sitrep = self.format_sitrep(
            trajectories=trajectories,
            attention_schema=AttentionSchema(
                current=current_allocation,
                recommended=recommended_allocation,
                health=schema_health,
            ),
            decisions=decisions,
            horizon=horizon,
        )

        if cognitive_state == CognitiveState.FATIGUED:
            sitrep = sitrep.compress_to_decisions_only()
        elif cognitive_state == CognitiveState.HIGH_FOCUS:
            sitrep = sitrep.filter_to_priority_only()

        return sitrep
```

## CLI Integration

```bash
# Daily SITREP (default)
uv run gaius-cli --cmd "/sitrep"

# Weekly SITREP
uv run gaius-cli --cmd "/sitrep week"

# Quarterly SITREP
uv run gaius-cli --cmd "/sitrep quarter"

# Open horizon exploration
uv run gaius-cli --cmd "/sitrep open"

# Compressed mode for low-energy states
uv run gaius-cli --cmd "/sitrep --compact"

# Focus mode for execution
uv run gaius-cli --cmd "/sitrep --focus"
```

## TUI Integration

The SITREP integrates with the existing THETA view mode:

- **THETA view** → Displays effect-space as density heatmap
- **Cursor position** → Shows arrow/target detail for that region
- **`/sitrep`** → Generates full report in content panel
- **Time horizon** → Controlled by overlay mode or explicit command

## Metrics and Feedback Loop

### SITREP Effectiveness Tracking

```
SITREP META-METRICS
───────────────────
• Decision adoption rate:     78% (decisions acted upon)
• Prediction accuracy:        65% (trajectory predictions vs actuals)
• Attention schema drift:     -3% (improving coherence over time)
• False alarm rate:           12% (warnings that didn't materialize)
• Missed signal rate:          8% (events SITREP didn't anticipate)
```

These metrics feed back into ThetaAgent's calibration, improving future SITREPs through the same GEPA optimization loop used elsewhere in Gaius.

---

*This specification embodies the synthesis of hippocampal theta dynamics (temporal organization), Attention Schema Theory (self-model of attention), and the Arrow-Target-Action metaphor (finite strategic resources) into a practical daily intelligence product.*
