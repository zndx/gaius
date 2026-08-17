# Generalize the docling flow to accept any PDF URL

**Date:** 2026-06-28
**Scope:** `gaius.flows.docling`, CLI `/flow run docling`, MCP `extract_pdf`

## Goal

The docling PDF→markdown flow was hardcoded to arXiv (metadata fetch,
abstract-based scoring, topic corpus, KB zettelkasten). Generalize it to convert
*any* PDF URL and write the markdown to a caller-supplied local directory —
while leaving the arXiv pipeline byte-for-byte intact.

## Design decision: branch in place, do **not** rename

`ArxivDoclingFlow` (class name) and `create_zettelkasten` (step name) are matched
as **string literals** elsewhere:

- `engine/services/flow_scheduler_service.py` routes LISTEN/NOTIFY completion
  events with `event.flow_type == "ArxivDoclingFlow"` (Metaflow emits the class
  name as `flow_type`).
- `datasets/nifi_som/{generator,cli,instructions}.py` encode the flow's class
  name and step list as strings for SoM dataset generation.

Renaming would silently break event routing and dataset generation. So the class
name and step names are **retained**, and the flow is generalized by branching on
a new `self.mode` (`"arxiv"` | `"generic"`) inside the existing linear step graph.

## Changes

### `flows/docling/flow.py`
- New params: `source_url` (any PDF URL), `output_dir` (local dest). `arxiv_url`
  is now optional (default `""`).
- `start`: resolve URL from either param; `self.arxiv_id = extract_arxiv_id(url)`;
  `mode = "arxiv" if (arxiv_id and not output_dir) else "generic"`. Setting
  `output_dir` **forces** generic mode even for an arXiv URL (and still resolves
  the real arXiv PDF). Split into `_start_arxiv` / `_start_generic` helpers.
  Fail-fast guru codes: `#DOCLING.00000004.NO_URL`, `#DOCLING.00000005.NO_OUTPUT_DIR`.
- `archive_step`: KB archive gated to arXiv mode (generic PDF saved in output step
  where a clean title is available).
- `convert_to_markdown`: shared core; also exports `plain_text` and, in generic
  mode, derives `title` from the first markdown heading (`_title_from_markdown`).
- `score_relevance` / `extract_topics`: skipped in generic mode (no abstract/corpus).
- `create_zettelkasten`: branches to `_write_generic_output`, which writes
  `<stem>.md` / `.txt` / `.pdf` into `output_dir` (`stem = safe_filename(title)`)
  and prints a `Created output:` token.
- `end`: mode-aware labels (Source URL / Output vs arXiv ID / KB Note).
- **Bug fix:** `start`/`end` used `self.correlation_id`, which is unset in step
  task processes (Metaflow doesn't persist `__init__` attributes across steps).
  Switched to the intended lazy accessor `self.get_correlation_id()`. This was a
  latent crash on the local-metadata execution path, pre-existing in arXiv mode.

### `flows/runner.py`
- `run_flow_with_gpu_management` stdout parser now also recognizes the
  `Created output:` token (generic-mode output path).

### `cli.py` `_flow_run`
- Destination dir parsed from 2nd positional (non-flag) or
  `--output-dir=`/`--output=`/`--out=`. With a dest dir → generic branch
  (`--source_url` + `--output_dir`, scoring/topics off). arXiv branch unchanged.
  Non-arXiv URL with no dest dir → friendly error (no execution).
- Usage docstrings updated.

### `mcp_server.py`
- New tool `extract_pdf(url, output_dir, archive_pdf=True, use_gpu=True)` — the
  generic counterpart to `fetch_paper`.

## Verification (CLI / flow, real work — no fallbacks)

- `/flow run docling <autodesk-url> <dir> --no-gpu` → CLI returns `mode: generic`
  with correct url/output_dir (routing layer verified).
- Full flow executed end-to-end (local Metaflow metadata) through all 8 steps:
  download 318,078 B → docling 37,920 chars → scoring+topics skipped → wrote
  `.md`/`.txt`/`.pdf`; title derived as "A First-Order Logic Formalization of the
  Industrial…". Output bytes identical to a direct docling extraction.
- `/flow run docling <non-arxiv-url>` (no dir) → friendly error, no execution.
- `extract_arxiv_id` routing table confirmed (arXiv abs/bare id → arxiv; autodesk
  / generic pdf → generic).

## Environment note

The standard `/flow run` path runs the flow as a Metaflow subprocess against the
**remote metadata service** at `localhost:30180` (Metaflow NodePort). That service
was down during this session (`Connection refused`) — this affects arXiv mode
identically and is unrelated to these changes. End-to-end verification used
`METAFLOW_DEFAULT_METADATA=local METAFLOW_DEFAULT_DATASTORE=local`, a legitimate
standalone Metaflow backend. With the platform up (`devenv processes up`), the
CLI path works as demonstrated.
