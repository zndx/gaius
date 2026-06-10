# GTC 2026 Docs: Deepen, Review, Refine

## Summary

Three-phase documentation improvement targeting TDA researchers from Carlsson's lab at BluelightAI attending GTC 2026.

## Phase 1: Deepen Architecture Pages

Enriched 6 architecture pages from source READMEs (244-542 lines each → 37-97 line doc pages):

| Page | Before | After | Key additions |
|------|--------|-------|---------------|
| inference.md | 57 lines | ~95 lines | OR-Tools CP-SAT scheduler, synthesis pipeline, tiered evaluation |
| agents.md | 59 lines | ~95 lines | Latent swarm embedding mechanics, ThetaAgent 5-stage pipeline, metaagent routing |
| rase.md | 52 lines | ~85 lines | Constraint composition, reward strategies, oracle invariants, accuracy formula |
| visualization.md | 81 lines | ~105 lines | Grammar feature-to-weight table, mesh generators, seeded RNG, GPU rendering |
| overview.md | 97 lines | ~110 lines | 8-layer architecture, mathematical foundations, execution paths |
| health.md | 69 lines | ~85 lines | HealthObserver daemon, incident lifecycle, healing audit trail |

Also fixed: "Claude Code" → "Mistral Vibe" in health.md line 24.

## Phase 2: Publish

Committed as `33d9917`, pushed to trunk. CI/CD deploys to GitHub Pages.

## Phase 3: Grok Review + Refine

Sent 5 pages to Grok 4.1 Fast via `ExternalInferenceRouter`. Scores:

| Page | Precision | Depth | Tone |
|------|-----------|-------|------|
| introduction.md | 7 | 5 | 6 |
| overview.md | 8 | 7 | 5 |
| visualization.md | 4 | 6 | 5 |
| rase.md | 9 | 7 | 6 |
| fmea.md | 9 | 7 | 9 |

### Accepted feedback (precision + tone)

- **introduction**: Clarified PH computed on original embeddings, defined complexity, noted threshold is heuristic
- **overview**: Defined FMEA/NVAR abbreviations, tightened promotional language
- **visualization**: Added Ollivier-Ricci equation with GraphRicciCurvature params, specified persistent Betti numbers, clarified b1/b2
- **rase**: Defined MBSE and RLVR, specified accuracy formula (uniform weighting)
- **fmea**: "quantitative" → "structured ordinal", clarified S/O/D are ordinal scales

### Rejected feedback

- Adding TDA domain extensions to RASE page (out of scope — RASE is agent verification)
- Adding benchmarks to overview (not architecture overview material)
- Cutting Pliny reference (it's the project name)
- Removing Go board conventions (design element, not decoration)
- Extensive TDA compute details on viz page (that's the core/tda.py page's job)

Refinements committed as `e696622`, pushed to trunk.

## Artifacts

- `scripts/xai_review_batch.py` — reusable multi-page Grok review script
- Total: 2 commits, 290 lines added, 181 removed across 7 files
