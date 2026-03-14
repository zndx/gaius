# Design Philosophy

Gaius is more than a visualization tool—it's an experiment in augmented cognition. The design integrates principles from human factors engineering, situational awareness research, and decades of interface evolution to create something genuinely new.

## Foundational Principles

### 1. Spatial Cognition First

Humans evolved to navigate physical space. We have dedicated neural hardware for:
- **Allocentric mapping**: Understanding space from a fixed reference frame
- **Path integration**: Tracking position through movement
- **Landmark recognition**: Identifying significant points

Gaius exploits this by mapping abstract data onto a navigable grid. The cursor becomes your position. Regions become territories. Movement through the grid engages spatial reasoning circuits that spreadsheets leave dormant.

### 2. Perceptual Bandwidth

Vision is our highest-bandwidth sense. Reading text: ~250 words/minute. Recognizing a scene: ~100ms. Gaius prioritizes visual pattern recognition over sequential text processing.

When you see agents clustered in a corner with death loops nearby, you perceive the situation instantly—before you could read a report describing it.

### 3. Modal Efficiency

Modal interfaces concentrate related operations. In normal mode, every key is a navigation or view command—no modifier keys needed. This reduces both physical motion and cognitive load.

Critics of modes cite "mode errors" (typing in wrong mode). Gaius addresses this with:
- Clear mode indicators in status line
- Consistent escape semantics (Esc always returns to normal)
- Mode-appropriate cursor styling (planned)

### 4. Progressive Complexity

New users see a clean grid. They navigate with `hjkl`, toggle modes, quit with `q`. Nothing confusing.

Power users access deeper functionality through slash commands, MCP tools, and CLI scripting. Three interfaces — TUI, CLI, MCP — offer increasing levels of automation.

Complexity is opt-in, not mandatory.

### 5. Transparency Over Magic

Every visual element has an explanation. The grid shows exactly what it's told to show. Agent positions derive from actual embeddings through a defined projection. Death loops come from computed homology.

No black boxes. No "AI magic." Understanding the system enables trusting the system.

## Human Factors Integration

Gaius incorporates principles from human factors engineering—the discipline of designing systems that account for human capabilities and limitations.

### Cognitive Load Management

**Miller's Law**: Working memory holds 7±2 chunks. Gaius manages this by:
- Showing at most 7 agents (one per color)
- Limiting candidate markers to 9 (a-i)
- Using overlays to separate concerns (one layer at a time)

**Hick's Law**: Decision time increases with choice count. Modal operation reduces active choices at any moment.

### Attention and Distraction

The grid provides a stable anchor. Overlays add information; the base never shifts unexpectedly.

Status updates appear in the designated status line—not as popups or animations that hijack attention.

### Error Prevention

**Confirmation for destructive actions**: Clear memory, quit with unsaved changes
**Reversible operations**: Overlay cycles, mode toggles, cursor movement
**Visible state**: Current mode, active features, domain always displayed

### Fitts's Law and Input

Fitts's Law: Target acquisition time depends on distance and size. Keyboard input eliminates targeting entirely—no mouse movement, no precision required.

`hjkl` navigation is the fastest possible input for grid movement.

## Situational Awareness

Situational awareness (SA) is the perception, comprehension, and projection of system states. Gaius is explicitly designed to support all three levels of SA as defined by Endsley (1995).

### Level 1: Perception

*What is happening?*

Gaius provides immediate perception through:
- **Grid state**: See where entities are located
- **Density shading**: See relative magnitudes at a glance
- **Agent positions**: See where each analytical lens is focused
- **Death loops**: See topological features visually

No reading required. No scrolling. The state is visible.

### Level 2: Comprehension

*What does it mean?*

Comprehension emerges from:
- **Spatial relationships**: Clusters = consensus, scatter = uncertainty
- **Overlay transitions**: Compare views to understand multi-dimensional state
- **Color coding**: Consistent agent colors build recognition
- **Historical context**: Memory enables "this is different from before"

### Level 3: Projection

*What will happen next?*

Projection is supported by:
- **Swarm dynamics**: Watch convergence/divergence trends
- **Entropy tracking**: Rising entropy may signal regime change
- **Death loop evolution**: New loops appearing = emerging risk
- **Agent trajectories**: Where is each analytical perspective moving?

### SA Demons (Threats to Awareness)

Endsley identified common SA failures. Gaius defends against them:

| SA Demon | Gaius Defense |
|----------|---------------|
| Attention tunneling | Overlay cycling forces perspective shifts |
| Data overload | Layered disclosure; modes separate concerns |
| Out-of-the-loop | Swarm runs show agent "thinking" in real-time |
| Misplaced salience | Consistent visual vocabulary; no flashy distractions |
| Complexity creep | Feature flags; base UI is minimal |

### The OODA Loop

Boyd's OODA (Observe-Orient-Decide-Act) loop describes competitive decision-making:

1. **Observe**: Grid displays current state
2. **Orient**: Overlays, memory search, agent positions inform context
3. **Decide**: Slash commands, domain changes, focus actions
4. **Act**: Run swarm rounds, mark positions, export insights

Fast OODA loops win. Gaius minimizes latency at every stage.

## Design Tensions

Every design involves tradeoffs. Gaius makes explicit choices:

### Density vs. Clarity
The grid could show more information (color + shape + size). We prioritize clarity—one symbol per cell, overlays for additional dimensions.

### Flexibility vs. Consistency
Custom projections enable domain adaptation. But core navigation (`hjkl`) never changes. Flexibility in content, consistency in interaction.

### Power vs. Accessibility
Modal interfaces have a learning curve. We accept this tradeoff because mastery enables flow states inaccessible to modeless interfaces.

### Automation vs. Control
Agents suggest; humans decide. The swarm provides perspectives, not prescriptions. Autonomy remains with the operator.

## The Goal: Augmented Cognition

Gaius aims to extend human perception into domains we can't naturally sense:
- High-dimensional embedding spaces
- Topological structure of point clouds
- Collective reasoning of agent swarms

By projecting these onto a navigable grid with overlays and keyboard-driven interaction, we make the invisible visible—and navigable.

This is augmentation, not replacement. The human remains in control, with enhanced perception of complex systems.
