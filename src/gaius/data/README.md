# Data Assets

Static assets bundled with the Gaius package.

## Ontologies

The consolidation TBox is **not** in this directory. Theta BERTSubs Intra
loads the HermiT-certified OWL at

`external/sdg-corpora/ontology/sdg-ontology.owl`

via `gaius.agents.theta.tbox.certified_ontology_path`. SKOS terminology is
grounded to that ontology. CLT is a content graph, not a TBox.

`ontologies/gaius_domain.owl` is retired: it was a private BERTSubs sibling
list and is not HermiT-certified SDG OWL. Do not point consolidation at it.
