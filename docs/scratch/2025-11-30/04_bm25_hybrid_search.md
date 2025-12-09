# Phase 1: BM25 Hybrid Search

**Date**: 2025-11-30
**Session**: Search Infrastructure

## Summary

Implemented BM25 lexical search over KB markdown files and integrated it with existing Brave web search into a hybrid `/search` command.

## Implementation

### New Module: `gaius.inference.search.bm25`

```python
from gaius.inference.search import KBSearch, get_kb_search

kb = get_kb_search()
kb.build_index()  # Indexes 393 KB documents

results = kb.search("distributed consensus", top_k=5)
for r in results:
    print(f"{r.path}: {r.score:.2f}")
    print(f"  Citation: {r.citation}")
```

### Features

- **BM25 via bm25s**: Fast lexical search with English stemming (PyStemmer)
- **Automatic indexing**: Builds on first search, cached in memory
- **Citation patterns**: Each result includes a regex pattern for precise citation:
  ```
  current/content/arxiv/paper.md:/consensus.*distributed.*agreement/
  ```
- **Hybrid search**: `/search` now queries both KB (BM25) and web (Brave) in parallel

### Files

```
src/gaius/inference/search/
├── __init__.py      # Added KBSearch exports
├── brave.py         # Existing Brave API client
└── bm25.py          # New BM25 KB search

pyproject.toml       # Added bm25s, PyStemmer to [search] extra
src/gaius/cli.py     # Updated /search for hybrid results
```

## Usage

```bash
# Hybrid search (KB + web)
uv run gaius-cli --cmd "/search distributed consensus" --format json

# Returns:
{
  "query": "distributed consensus",
  "kb_results": [
    {
      "source": "kb",
      "path": "current/content/arxiv_cs_dc/2025-11-30/beluga-bft.md",
      "title": "Beluga: Block Synchronization for BFT Consensus",
      "snippet": "Modern high-throughput BFT consensus protocols...",
      "score": 3.83,
      "citation": "current/content/arxiv_cs_dc/.../beluga-bft.md:/Modern.*high\\-throughput.*BFT/"
    }
  ],
  "web_results": [
    {
      "source": "web",
      "url": "https://raft.github.io/",
      "title": "Raft Consensus Algorithm",
      "snippet": "..."
    }
  ]
}
```

## Architecture

```
/search "query"
       │
       ├──► BM25 (bm25s)     ──► KB results with citations
       │    - 393 documents indexed
       │    - English stemming
       │    - Regex patterns for citation anchors
       │
       └──► Brave API        ──► Web results
            - Fresh external content
            - 5 results per query
```

## Next Steps (Phase 2+)

1. **Qdrant integration**: Add semantic/vector search
2. **Result fusion**: RRF to merge BM25 + vector + web rankings
3. **LLM synthesis**: Generate Zettelkasten notes with citations
4. **Eval loop**: Frontier model judging + APO

## Dependencies Added

```toml
[project.optional-dependencies]
search = [
    "gaius[inference]",
    "bm25s>=0.2.0",
    "PyStemmer>=2.2.0",
]
```

Install: `uv sync --extra search`
