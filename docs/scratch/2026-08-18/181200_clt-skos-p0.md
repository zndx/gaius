# CLT SKOS P0 — Gaius sources, Aegir grain, contrib scheme

- Ledger: `admitted_item`, `activation`
- Flow: `CltSkosEvalFlow` (`clt-skos-eval`) ingest → extract → ground
- MaxSim is mandatory. `sdg_aperture` (33 points) lives on devenv Qdrant
  `:6339`, encoded with ColBERTv2 (same e/τ/C as Aegir). No admit-all hatch.
- SKOS home: `external/sdg-corpora/contrib/clt/qwen3-1.7b-20k/` (SHARE
  across Signals). Distinct from SDG scheme. Concepts in P1.
- Run 42: 2 sources → 2 admitted windows, extract skipped.
