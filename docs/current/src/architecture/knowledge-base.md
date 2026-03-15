# Knowledge Base

The knowledge base is a markdown-first document store organized as a zettelkasten. It lives under `build/dev/` (gitignored) and is accessible through MCP tools for CRUD operations.

## Directory Structure

```
build/dev/
├── current/            # Active work (manually curated)
│   ├── projects/       # Project-specific documents
│   ├── articles/       # Article directories with frontmatter
│   ├── content/domains/ # Domain-specific content
│   └── heuristics/     # Guru meditation heuristic files
│       └── gaius/
├── scratch/            # Zettelkasten notes (organized by date)
│   ├── 2026-03-14/
│   │   ├── 103045_my_analysis.md
│   │   └── 142200_research_notes.md
│   └── 2026-03-13/
└── archive/            # Quarterly archives
    └── 2026Q1/
        └── attachments/
```

**current/** contains active, manually curated work. Articles, projects, and domain content live here. Heuristic files for guru meditation codes are stored at `current/heuristics/gaius/{category}/{name}.md`.

**scratch/** is the zettelkasten. Files are organized by date and named with a time prefix: `{HHMMSS}_{title}.md`. This is where Metaflow pipelines deposit processed content and where daily research notes accumulate.

**archive/** holds quarterly archives with binary attachments (PDFs, images) that are too large for the scratch directory.

## MCP Tools

The KB is fully accessible through MCP tools, enabling AI assistants and agents to read, write, and search the knowledge base:

| Tool | Operation |
|------|-----------|
| `search_kb` | Full-text search across all KB content |
| `read_kb` | Read a specific file by path |
| `create_kb` | Create a new file at a given path |
| `update_kb` | Update an existing file |
| `list_kb` | List files in a directory |
| `delete_kb` | Delete a file |

```bash
# Search the knowledge base
uv run gaius-cli --cmd "/search_kb 'persistent homology'"

# Read a specific file
uv run gaius-cli --cmd "/read_kb scratch/2026-03-14/103045_analysis.md"
```

## Path Conventions

Metaflow flows use helper methods on `GaiusFlow` to generate consistent paths:

```python
# Zettelkasten path: scratch/{date}/{HHMMSS}_{title}.md
path = self.zettelkasten_path("My Analysis")
# -> "scratch/2026-03-14/103045_my_analysis.md"

# Archive path: current/archive/{quarter}/attachments/{filename}
path = self.archive_path("paper.pdf")
# -> "current/archive/2026Q1/attachments/paper.pdf"
```

## Integration with Pipelines

The KB serves as both input and output for the [data pipeline](./data-pipeline.md):

- **Input**: Articles with frontmatter and zettelkasten notes drive the [article curation](./article-curation.md) flow
- **Output**: Processed papers, research summaries, and draft articles are written back to scratch/ or current/
- **Lineage**: KB file paths appear as Dataset nodes in the [lineage graph](./lineage.md), enabling provenance queries from source URL to KB entry

## Storage Backend

KB operations go through `gaius.storage.kb_ops`, which manages the filesystem-backed store. The `GAIUS_KB_ROOT` environment variable overrides the default `build/dev/` location. Content is not stored in the database -- the KB is a plain filesystem hierarchy, making it easy to browse, grep, and version control externally.

## Sync to HX

Raw content (PDFs, API responses) is stored separately in the HX data lake (Apache Iceberg) to prevent the KB from being overwhelmed with unprocessed data. Only curated summaries and processed markdown enter the KB.
