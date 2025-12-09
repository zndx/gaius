# Phase 2: Qdrant Vector Search

**Date**: 2025-11-30
**Session**: Semantic Search Infrastructure

## Summary

Implemented vector/semantic search using Qdrant and sentence-transformers, integrated with RRF fusion for hybrid search combining BM25 + Vector + Web results.

## Implementation

### New Module: `gaius.inference.search.vector`

```python
from gaius.inference.search import VectorSearch, get_vector_search

vs = get_vector_search()
vs.index_kb()  # 1464 chunks indexed

results = vs.search("distributed consensus algorithms", top_k=5)
for r in results:
    print(f"[{r.score:.3f}] {r.path}")
```

### Architecture

```
/search "query"
       │
       ├──► BM25 (bm25s)        ──► Lexical matches (exact terms)
       │    10 results
       │
       ├──► Vector (Qdrant)     ──► Semantic matches (meaning)
       │    10 results              all-MiniLM-L6-v2, 384 dim
       │
       └──► Brave API           ──► Web results
            5 results
              │
              ▼
       ┌──────────────────┐
       │  RRF Fusion      │  Reciprocal Rank Fusion
       │  k=60            │  score = Σ(1/(k+rank))
       └──────────────────┘
              │
              ▼
       Top 10 KB results (source: bm25, vector, or bm25+vector)
       + 5 web results
```

### Key Features

- **Sentence-transformers**: Local embedding model (all-MiniLM-L6-v2)
- **Chunking**: 512 char chunks with 64 char overlap, sentence boundary aware
- **Qdrant storage**: 1464 chunks at `/raid/qdrant/gaius` (port 6339)
- **RRF fusion**: Documents found by both BM25 and Vector rank higher
- **Source tracking**: Each result shows `source: bm25+vector` or single source

### Files

```
src/gaius/inference/search/
├── __init__.py    # Added vector exports
├── brave.py       # Web search
├── bm25.py        # Lexical search
└── vector.py      # New: semantic search

pyproject.toml     # Added qdrant-client, sentence-transformers
src/gaius/cli.py   # Updated /search with RRF fusion
```

## Configuration

Environment variables:
```bash
QDRANT_HOST=localhost      # Default
QDRANT_PORT=6339           # From devenv.nix
QDRANT_COLLECTION=gaius_kb # Default
EMBEDDING_MODEL=all-MiniLM-L6-v2  # Fast, 384 dim
```

Alternative models:
- `all-mpnet-base-v2`: 768 dim, better quality
- `nomic-ai/nomic-embed-text-v1.5`: 768 dim, excellent quality

## Usage

```bash
# Hybrid search (BM25 + Vector + Web)
uv run gaius-cli --cmd "/search distributed consensus" --format json

# Semantic query (vector excels here)
uv run gaius-cli --cmd "/search meaning of life existential questions"
```

## Results

### Distributed Consensus Query
```
source: bm25+vector  →  Beluga BFT paper (found by both)
source: bm25+vector  →  BlueBottle blockchain paper
source: bm25         →  Swarm Intelligence (lexical match only)
source: vector       →  Federated learning paper (semantic similarity)
```

### Existential Philosophy Query
```
source: bm25+vector  →  Philosophies of Life
source: bm25+vector  →  Workshop on Meaning, LLMs
source: vector       →  Consciousness Reading List (semantic)
```

## Dependencies Added

```toml
search = [
    "qdrant-client>=1.12.0",
    "sentence-transformers>=3.0.0",
]
```

## Index Statistics

- **Documents**: 393 markdown files
- **Chunks**: 1464 (avg ~4 chunks per doc)
- **Embedding dim**: 384
- **Index time**: ~30 seconds (CPU)

## Next Steps (Phase 3+)

1. **LLM Synthesis**: Generate Zettelkasten notes from search results
2. **Citation verification**: Ensure regex patterns resolve
3. **Eval loop**: Frontier judge scoring
4. **Incremental indexing**: Update on new content
