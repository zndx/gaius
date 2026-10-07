# Review: a friend's "gaius TBox typing inside NAM" note

Friend pinned gaius 73722dce (2026-09-21) and sdg-corpora c2079e67.

## Their two loading notes are real at their pin, already fixed on trunk
- bd8305c (2026-09-22): `load_pinned_imports` + `ontology_for_owlready` load the CCO import from
  `imports/cco-module.ttl` and drop property/class puns.
- dd0bdc6: same local-import fix for OWLAPI/DeepOnto.
- sdg-corpora dc47bbb8: catalog maps the trailing-slash CCO IRI.

## Divergence they don't know about
- They kept the 13 punned IRIs as classes -> 918. Gaius drops the class typing -> 905
  (verified: `class_verbalizations()` = 905, indexable = 905). Their "matched all 918" is against
  a hand-patched loader, not gaius behaviour.

## Scope differences (not bugs)
- Gaius only MaxSim-grounds `admitted_item` rows (sdg_aperture admission first); never types
  arbitrary text. They skipped admission, so "100% coverage" is a harness property.
- Gaius consumes the top-k as a grounding set for CLT-incidence novel-subsumption pairs
  (`clt_incidence.py`), not a top-1 record type.
- Scoring path (prefixes, MaxSim / query tokens, top 8, no threshold) matches theirs.

## Possible follow-up
- Add a test that loads the real pinned OWL (repo tests use a 3-class fixture, which is why
  neither loading issue showed up in CI).
