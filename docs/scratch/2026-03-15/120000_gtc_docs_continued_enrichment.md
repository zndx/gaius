# Continued Documentation Enrichment for GTC 2026

## Session 2: Guide, Operations, and Final Polish

Continued from the previous session's systematic documentation enrichment. This session focused on guide pages (product showcase), operations pages (infrastructure depth), and quality verification.

## Commits Made

### `3dde8e7` — Security enrichment + ACP reference fixes
- Enriched `architecture/security.md` with guru codes per layer and structural design principle
- Fixed "Claude Code" → "Mistral Vibe" in 4 ACP-context files (glossary, guru-codes, workflow-health, changelog)

### `7902f4f` — Guide and operations enrichment (9 files, +173/-61 lines)
- **guide/tui.md**: Added view mode table (Go/Theta/Swarm), overlay mode table (Topology/Geometry/Dynamics/Agents), MiniGrid scalar fields (κ/π/σ/β), center panel modes, density shading vocabulary
- **guide/quickstart.md**: Added "What You See" section with first-interaction key table
- **guide/mcp.md**: Added MCP tool category breakdown table (163 tools by domain)
- **guide/workflows.md**: Enriched workflow descriptions with pipeline details, FMEA scoring, evolution methods
- **design/ooda.md**: Connected OODA phases to specific topology/curvature overlays and MiniGrid projections
- **operations/deployment.md**: Added service dependency graph, warm start timing, hybrid deployment model
- **operations/monitoring.md**: Added monitoring stack table, key metrics with alert thresholds, windowed rates
- **operations/infrastructure.md**: Added port numbers, service descriptions (37 services, 768-dim embeddings, etc.)
- **operations/gpu.md**: Added RTX 4090 specs (24GB × 6 = 144GB), OR-Tools CP-SAT scheduling reference

## Remaining "Claude Code" References
~30 references remain across guide, design, and appendix pages. All are legitimate product references:
- MCP setup guide (`claude-code-setup.md`) — Claude Code is the MCP client product
- Design inspiration (`inspirations.md`) — Claude Code's slash-command convention
- Co-creation (`co-creation.md`) — development methodology using Claude Code
- Workflow research (`workflow-research.md`) — MCP-driven orchestration
- ACP incident report (`acp-incident-2026-01-01.md`) — historical document

## Documentation Status by Section

| Section | Pages | Status |
|---------|-------|--------|
| Foundations | 7 | All strong (63-128 lines) |
| Architecture | 33 | All enriched (51-165 lines) |
| User Guide | 14 | Key pages enriched (41-134 lines) |
| Design | 6 | All well-written (53-226 lines) |
| Operations | 9 | Now enriched (35-69 lines) |
| Development | 4 | Adequate (56-81 lines) |
| Reference | 6 | Adequate (52-73 lines) |
| Appendix | 2 | Complete (44-180 lines) |

## Pages Still Thin but Appropriate
- `operations/metaflow-service.md` (35 lines) — service setup instructions
- `operations/k8s.md` (43 lines) — K8s configuration
- `operations/just.md` (54 lines) — task runner reference
- `architecture/pgcron.md` (51 lines) — cron job listing

These are appropriately scoped for their content — operational reference doesn't need narrative enrichment.

## Total Commits This Enrichment Campaign (both sessions)
1. `33d9917` — Phase 1: Deepen 6 architecture pages
2. `e696622` — Phase 3: Grok review refinements
3. `91c4ffc` — 12 architecture pages deepened
4. `ccb8254` — 8 architecture + concepts pages enriched
5. `3dde8e7` — Security enrichment + ACP fixes
6. `7902f4f` — Guide + operations enrichment (9 files)

All pushed to trunk, GitHub Actions deploys to Pages.
