# Pairs are not the ontology

The "64 novel pairs" from the 2026-W38 run are a process leftover, not
a measure to refine.

Atelier already retired this habit. `docs/src/architecture/classification.md`
says the subsumption/LLM-mediated alignment dance is gone: the head emits
the vocabulary directly, with no runtime alignment step. Theta's
`clt_incidence.novel_directed_pairs` and Aspect C's "pairing substrate
BERTSubs scores" (2026-09-20) carried that older thinking forward.

The design to stay on is Aegir's entailed stack, **OWL ⊨ SKOS ⊨ SHACL**:

- OWL is the HermiT-certified artifact.
- SKOS is an entailed annotation face of that OWL, not an independent
  scheme and not a list of hypothesized class–class links.
- SHACL is the closed-world view of the same OWL (`sh:targetClass` names
  a realized class).
- The aperture is SKOS-in-Qdrant grounded in that stack, for the
  week-or-longer window, and it still has to backtest on the accumulated
  corpus.

Do not tune the pair count, the 0.8 gate, or the TBox-holdout MRR.
Those numbers describe the procedure that happened to run. They are not
ontology efficacy.
