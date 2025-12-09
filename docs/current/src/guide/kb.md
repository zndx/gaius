# Knowledge Base Structure

Gaius integrates with a structured knowledge base (KB) organized for both manual curation and automatic capture. The structure follows the Zettelkasten method for scratch notes while supporting traditional project hierarchies.

## Default Location

During development, the KB lives under `build/dev/` in the project directory:

```
build/dev/
├── current/        # Active work (manual organization)
│   ├── projects/
│   └── content/
├── scratch/        # Zettelkasten (auto-organized by date)
│   └── 2025-11-28/
└── archive/        # Quarterly archives
    └── 2025Q4/
        └── attachments/
```

The `build/` directory is gitignored, keeping development data local.

## Overview

```
current/            # Active work (manual organization)
├── projects/       # Project directories
└── content/        # Reference content

scratch/            # Zettelkasten (auto-organized by date)
├── 2025-11-28/
│   ├── 1732816800.md
│   └── 1732831200.md
└── 2025-11-29/

archive/            # Quarterly archives
├── 2025Q4/
│   ├── projects/
│   ├── scratch/
│   └── attachments/
└── 2025Q3/
```

## Directory Structure

### /current - Active Work

Manual organization for ongoing projects and reference material.

```
/current/
├── projects/
│   ├── gaius/
│   │   ├── README.md
│   │   ├── CLAUDE.md
│   │   └── notes/
│   └── pension-model/
│       ├── model.py
│       ├── data/
│       └── reports/
└── content/
    ├── domains/
    │   ├── pension.md
    │   └── supply-chain.md
    └── references/
        ├── tda-intro.pdf
        └── bloomberg-guide.md
```

**Usage patterns:**
- Create project directories as needed
- Organize by topic/domain under `content/`
- Keep actively used files at hand

### /scratch - Zettelkasten Notes

Automatic organization by date and timestamp. Inspired by the Zettelkasten method.

```
/scratch/
├── 2025-11-28/
│   ├── 1732816800.md  # Unix timestamp = 2025-11-28T12:00:00
│   └── 1732831200.md  # Unix timestamp = 2025-11-28T16:00:00
├── 2025-11-27/
│   └── 1732744800.md
└── ...
```

**Filename format:** `<unix-timestamp>.md`

**Benefits:**
- No naming decisions required
- Automatic chronological organization
- Easy to link between notes using timestamps

**Note structure:**
```markdown
# Session Title

## Context
Links to related notes: [[1732744800]], [[pension-model]]

## Content
Main content of the note...

## Links
- Backward: [[previous-related-note]]
- Forward: [[next-related-note]]
```

### /archive - Quarterly Archives

Quarterly migration of completed work.

```
/archive/
├── 2025Q4/
│   ├── projects/     # Migrated from /current/projects
│   ├── scratch/      # Migrated from /scratch
│   └── attachments/  # Binary files (images, PDFs)
└── 2025Q3/
    └── ...
```

**Migration process (quarterly):**
1. Move completed projects from `/current/projects/` to `/archive/<quarter>/projects/`
2. Move old scratch notes from `/scratch/` to `/archive/<quarter>/scratch/`
3. Binary attachments referenced by scratch notes go to `/archive/<quarter>/attachments/`

**Attachment handling:**
When creating scratch notes, place media attachments directly in `/archive/<quarter>/attachments/` to avoid relocating large files later:

```markdown
# Analysis Session

![Chart](file:///archive/2025Q4/attachments/chart-20251128.png)

See detailed report: [Report PDF](/archive/2025Q4/attachments/report.pdf)
```

## Storage Backends

Gaius supports multiple storage backends:

### Local Filesystem (Default)
Standard filesystem at configured path.

### Minio (S3-compatible)
```
s3://gaius-kb/current/
s3://gaius-kb/scratch/
s3://gaius-kb/archive/
```

### Ceph Object Store
```
ceph://kb-pool/current/
ceph://kb-pool/scratch/
ceph://kb-pool/archive/
```

Configuration in environment or config file:
```bash
GAIUS_KB_BACKEND=minio
GAIUS_KB_ENDPOINT=localhost:9000
GAIUS_KB_ACCESS_KEY=...
GAIUS_KB_SECRET_KEY=...
```

## Plan 9 Integration

Following Plan 9's "everything is a file" philosophy, Gaius represents agents as files:

```
/agents/
├── leader      # Virtual file for Leader agent
├── risk        # Virtual file for Risk agent
├── optimizer   # Virtual file for Optimizer agent
├── planner     # Virtual file for Planner agent
├── critic      # Virtual file for Critic agent
├── executor    # Virtual file for Executor agent
└── adversary   # Virtual file for Adversary agent
```

Reading an agent file returns its latest output and state:
```bash
cat /agents/risk
# Returns: Risk agent's current analysis and position
```

Writing to an agent file sends it a query:
```bash
echo "analyze liquidity risk" > /agents/risk
# Triggers Risk agent to analyze and update
```

## File Tree Widget

The left panel in Gaius displays the KB structure:

- **Expandable tree**: Navigate hierarchy
- **File selection**: Click to view in content panel
- **Agent selection**: Click agent to see output
- **Search** (planned): `/find <query>` to search across KB

## Best Practices

1. **Use scratch liberally**: Don't organize prematurely; timestamp files capture context
2. **Link between notes**: Use `[[timestamp]]` or `[[project-name]]` syntax
3. **Archive quarterly**: Keep `/current` and `/scratch` manageable
4. **Attachments in archive**: Avoid moving large files by placing in archive directly
5. **Domain files in content**: Reusable domain definitions go in `/current/content/domains/`
