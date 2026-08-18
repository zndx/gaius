# ColBERT-Zero end-to-end

Signals multi-vector SoR is `lightonai/ColBERT-Zero` (128-d, PyLate).

- Aperture `sdg_aperture`: 33 points, Zero MaxSim; τ applied to
  mean MaxSim (raw / n_query_tokens) so strategy `domain_tau=0.1` stays 0–1.
- KB `gaius_kb_colbert_zero`: 111412 chunks, ~43 min rebuild.
  Search smoke: GPU scheduling hits arxiv_cs_dc notes.
- Retired ColNomic collection `gaius_kb_colnomic` is unused leftover.
- Images: `#EM.00000001.NOVISION` (text only).
