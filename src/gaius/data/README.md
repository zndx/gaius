# Data Assets

This directory contains static data assets used by Gaius, including ontologies,
schemas, and reference data that are bundled with the package.

## Structure

```
data/
└── ontologies/
    └── gaius_domain.owl    # OWL ontology for Gaius domain concepts
```

## Ontologies

### `gaius_domain.owl`

An OWL (Web Ontology Language) ontology defining the core domain concepts
for Gaius. This ontology is used by:

- **DeepOnto/BERTSubs**: For subsumption inference in ThetaAgent consolidation
- **Semantic Search**: For concept hierarchy and relationship queries
- **KB Organization**: For taxonomic classification of knowledge entries

**Key Concepts**:
- Infrastructure (GPU, vLLM, endpoints)
- Health (incidents, remediations, heuristics)
- Evolution (agents, versions, evaluations)
- Knowledge (topics, documents, threads)

## Usage

Access data files via `importlib.resources`:

```python
from importlib.resources import files

ontology_path = files("gaius.data.ontologies") / "gaius_domain.owl"
with ontology_path.open() as f:
    owl_content = f.read()
```

Or for DeepOnto integration:

```python
from deeponto.onto import Ontology

onto = Ontology(str(ontology_path))
```

## Adding New Assets

When adding new data assets:

1. Place files in the appropriate subdirectory
2. Ensure `__init__.py` exists in each directory (for package discovery)
3. Update `pyproject.toml` if needed for package data inclusion
4. Document the asset in this README
