# Phase 3: Zettelkasten Synthesis

**Date**: 2025-11-30
**Session**: LLM-Powered Knowledge Synthesis

## Summary

Implemented LLM-powered Zettelkasten note generation from hybrid search results. The `/research` command now:
1. Runs hybrid search (BM25 + Vector + Web)
2. Synthesizes results using local LLM (Qwen3-Coder via optillm)
3. Generates structured Zettelkasten notes with citations and wiki-links
4. Verifies KB citations exist
5. Saves to `build/dev/scratch/{date}/`

## Architecture

```
/research "query"
       │
       ├──► Hybrid Search
       │    ├── BM25 (10 results)
       │    ├── Vector (10 results)
       │    └── Web (5 results)
       │         │
       │         ▼
       │    RRF Fusion → Top 10 KB + 5 Web
       │
       └──► LLM Synthesis (optillm + Qwen3)
            │
            ▼
       ┌──────────────────────────────┐
       │  Zettelkasten Note           │
       │  ────────────────            │
       │  - Frontmatter (date, type)  │
       │  - [[wiki-links]] extracted  │
       │  - Synthesized content       │
       │  - KB citations (verified)   │
       │  - Web citations             │
       └──────────────────────────────┘
            │
            ▼
       build/dev/scratch/2025-11-30/
```

## Implementation

### New Module: `gaius.inference.synthesis`

```python
from gaius.inference import ZettelkastenSynthesizer

synthesizer = ZettelkastenSynthesizer()
note = await synthesizer.synthesize(
    query="distributed consensus",
    kb_results=kb_results,
    web_results=web_results,
    domain="computer science",
)

# Verify citations
verification = synthesizer.verify_citations(note)
print(f"Verified: {sum(verification.values())}/{len(verification)}")

# Save
path = note.save()
```

### Key Classes

- `ZettelkastenNote`: Complete note with citations and wiki-links
- `Citation`: KB or web citation with optional regex pattern
- `ZettelkastenSynthesizer`: Orchestrates search → LLM → note

### Citation Format

KB citations include regex patterns for precise location:
```markdown
[Title](current/content/arxiv/paper.md:/pattern.*to.*match/)
```

### Wiki-Link Extraction

The LLM generates `[[wiki-style]]` links for key concepts, normalized to proper conventions:
```markdown
links: [[distributed-systems]], [[consensus-algorithms]], [[consul]]
link-targets: current/topics/distributed-systems.md, current/topics/consensus-algorithms.md, current/topics/consul.md
```

**Naming conventions:**
- `skewer-case` preferred: `distributed-systems`
- Underscores for combined topics: `consensus_raft`
- `CamelCase` for persons: `ThomasNagel` → `current/contacts/ThomasNagel.md`

## Example Output

```markdown
# distributed consensus algorithms

---
created: 2025-11-30T05:19:58
type: zettel
sources: 15
links: [[distributed systems]]
---

Distributed consensus algorithms are fundamental protocols...

## Sources

### Knowledge Base
- [Beluga BFT](current/content/arxiv/.../beluga.md:/Modern.*high\-throughput.*BFT/)
  > Modern high-throughput BFT consensus protocols...

### Web
- [Raft Consensus Algorithm](https://raft.github.io/)
```

## Usage

```bash
# Set optillm API key (local stack)
export OPTILLM_API_KEY=sk-optillm

# Research a topic
uv run gaius-cli --cmd "/research distributed consensus"
uv run gaius-cli --cmd "/research philosophy of consciousness"

# With domain context
uv run gaius-cli --cmd "/domain computer science" --cmd "/research raft protocol"
```

## Files

```
src/gaius/inference/
├── __init__.py      # Added synthesis exports
├── synthesis.py     # New: Zettelkasten synthesis
└── client.py        # LLM client (unchanged)

src/gaius/cli.py     # Updated /research command
```

## Test Results

| Query | KB Sources | Web Sources | Wiki Links | Citations Verified |
|-------|------------|-------------|------------|-------------------|
| distributed consensus | 10 | 5 | 1 | 10/10 |
| philosophy of consciousness | 10 | 5 | 5 | 10/10 |

## Next Steps (Phase 4+)

1. **Eval Loop**: Frontier model judging of synthesis quality
2. **APO**: Automatic prompt optimization based on scores
3. **Incremental indexing**: Re-index on new content
4. **Topic/Project linking**: Auto-create [[topic]] entries
