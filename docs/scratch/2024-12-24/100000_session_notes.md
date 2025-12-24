# Session Notes: 2024-12-24

## What Got Built

1. **NG-RC Forward Dynamics** (`engine/services/ngrc.py`)
   - NGRCPredictor using polynomial features of time-delay embeddings
   - Learns dx/dt = f(x) from trajectory data
   - Serialization for model persistence
   - KB growth tracking for retraining triggers

2. **CLI Commands** for `/ngrc` (train, predict, model, status)

3. **Design Documentation** for phase portrait situational awareness

## Key Conceptual Breakthroughs

### Phase Portrait as SA Metaphor
- SITREP is not a summary, it's a phase portrait of organizational cognition
- Attractors = stable conclusions
- Basins = evidence sets that lead to same conclusion
- Separatrices = tipping points (invisible in Columbia disaster)
- Drift velocity = how fast understanding is changing
- Well depth = entrenchment (can be earned OR artificial)

### NVAR ↔ Swarm Co-evolution
- NVAR (continuous): maintains flow field, encodes memory, cheap compute
- Swarm (episodic): explores new KB content, expensive compute
- Divergence between prediction and observation = something changed
- Interventions: EXPAND (fetch more) / REFINE (synthesize) / SURFACE (escalate)

### Crisis Mode Detection
- **Katrina mode**: high tempo, information flood, destabilizing attractors
- **Columbia mode**: normal tempo, suspicious stability, floating evidence
- Key metric: "stability achieved by exclusion, not integration"

### Floating Evidence
- KB content that swarm agents mention but never integrate into consensus
- The blind spot made visible
- System should track and refuse to let it fade

### Dissent Energy
- When agents consistently pull away from consensus in same direction
- That's signal, not noise
- High dissent energy + deep well = dangerous artificial stability

## Architecture Direction

**Engine separation**: gaius-engine as standalone gRPC service
- Topology, NG-RC, swarm orchestration, evolution
- Multiple clients: TUI (dev), A2UI/3D (product)

**A2UI integration**: Agents emit declarative UI components
- Framework-agnostic (renders in WebGL, Flutter, or TUI)
- Incremental updates as dynamics evolve
- Component catalog: phase_portrait, drift_indicator, floating_evidence_list

**3D Visualization**: Phase portrait as navigable space
- Fly through semantic space
- See attractors as gravity wells
- Drift as flow field
- Floating evidence as orphaned particles

## Tomorrow's Considerations

1. Floating evidence tracker (schema + TopologyService)
2. Dissent energy metric (add to snapshot persistence)
3. Mode assessment function (katrina/columbia/normal)
4. Engine extraction feasibility
5. A2UI component catalog design

## Files Changed This Session

- `db/migrations/20251224000001_swarm_temporal_topology.sql`
- `src/gaius/engine/services/topology_service.py`
- `src/gaius/engine/services/ngrc.py` (new)
- `src/gaius/engine/services/__init__.py`
- `src/gaius/engine/grpc/server.py`
- `src/gaius/engine/server.py`
- `src/gaius/engine/grpc/servicers/gaius_servicer.py`
- `src/gaius/cli.py`
- `docs/scratch/2024-12-24/*.md`
