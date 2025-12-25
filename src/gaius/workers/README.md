# Gaius Workers

Fetch worker pool for KB upkeep. Polls fetch_jobs from PostgreSQL and executes content fetching from various sources (arXiv, bioRxiv, RSS feeds).

## Architecture

```mermaid
graph TB
    subgraph "Job Queue"
        PG[(PostgreSQL<br/>fetch_jobs)]
    end

    subgraph "Worker Pool"
        MGR[WorkerManager]
        W1[Worker 1]
        W2[Worker 2]
        WN[Worker N]
    end

    subgraph "Fetchers"
        ARXIV[ArxivFetcher]
        BIORXIV[BioRxivFetcher]
        RSS[RSSFetcher]
    end

    subgraph "Output"
        HX[HX Data Lake]
        KB[Knowledge Base]
    end

    PG --> MGR
    MGR --> W1
    MGR --> W2
    MGR --> WN
    W1 --> ARXIV
    W2 --> BIORXIV
    WN --> RSS
    ARXIV --> HX
    BIORXIV --> HX
    RSS --> KB
```

## Module Structure

```
workers/
├── __init__.py       # Module exports
├── config.py         # WorkerConfig
├── models.py         # FetchJob, ContentItem, FetchResult
├── base.py           # BaseFetcher protocol
├── manager.py        # WorkerManager
├── processor.py      # ContentProcessor
├── db.py             # Database operations
├── triage.py         # Job triage and prioritization
├── cli.py            # Worker CLI
├── fetchers/
│   ├── arxiv.py      # ArxivFetcher
│   ├── biorxiv.py    # BioRxivFetcher
│   └── rss.py        # RSSFetcher
└── processing/
    └── summarize.py  # Content summarization
```

## Job Model

```python
@dataclass
class FetchJob:
    id: str
    source: str           # "arxiv", "biorxiv", "rss"
    source_id: str        # arXiv ID, DOI, URL
    priority: int         # 0 = highest
    status: JobStatus     # PENDING, RUNNING, COMPLETE, FAILED
    created_at: datetime
    attempts: int = 0
    max_attempts: int = 3
    metadata: dict = field(default_factory=dict)
```

### Job Status

```python
class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    EXPIRED = "expired"
```

## Worker Manager

Coordinates worker pool:

```python
from gaius.workers import WorkerManager, WorkerConfig

config = WorkerConfig(
    num_workers=4,
    poll_interval=5.0,
    batch_size=10,
)

manager = WorkerManager(config)

# Start processing
await manager.start()

# Graceful shutdown
await manager.stop()
```

### WorkerConfig

```python
@dataclass
class WorkerConfig:
    num_workers: int = 4
    poll_interval: float = 5.0      # Seconds between polls
    batch_size: int = 10            # Jobs per poll
    max_concurrent: int = 8         # Max concurrent fetches
    timeout: float = 60.0           # Per-job timeout
    retry_delay: float = 300.0      # Delay before retry
```

## Fetchers

### ArxivFetcher

```python
from gaius.workers.fetchers import ArxivFetcher

fetcher = ArxivFetcher()

result = await fetcher.fetch(
    source_id="2312.12345",
    metadata={"categories": ["cs.LG"]},
)

print(f"Title: {result.title}")
print(f"PDF: {result.pdf_path}")
print(f"Abstract: {result.abstract}")
```

### FeedSource

For RSS/Atom feeds:

```python
@dataclass
class FeedSource:
    url: str
    name: str
    category: str
    poll_interval: timedelta = timedelta(hours=1)
    enabled: bool = True
```

## Content Processing

### ContentItem

```python
@dataclass
class ContentItem:
    source: str
    source_id: str
    title: str
    content: bytes
    content_type: str      # "application/pdf", "text/html"
    metadata: dict
    fetched_at: datetime
```

### FetchResult

```python
@dataclass
class FetchResult:
    success: bool
    item: ContentItem | None
    error: str | None
    duration_ms: int
```

## Job Triage

Priority-based job scheduling:

```python
from gaius.workers.triage import JobTriage

triage = JobTriage()

# Get next jobs to process
jobs = await triage.get_batch(
    limit=10,
    sources=["arxiv", "biorxiv"],
)

# Mark job complete
await triage.complete(job_id, result)

# Mark job failed (will retry)
await triage.fail(job_id, error="Connection timeout")
```

### Priority Factors

| Factor | Weight | Description |
|--------|--------|-------------|
| Age | 0.3 | Older jobs get priority |
| Attempts | 0.2 | Fewer attempts = higher priority |
| Source | 0.3 | Source-specific weights |
| Manual | 0.2 | User-requested jobs |

## Database Schema

```sql
CREATE TABLE fetch_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(32) NOT NULL,
    source_id VARCHAR(256) NOT NULL,
    priority INT DEFAULT 5,
    status VARCHAR(16) DEFAULT 'pending',
    attempts INT DEFAULT 0,
    max_attempts INT DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    UNIQUE (source, source_id)
);

CREATE INDEX idx_fetch_jobs_status ON fetch_jobs(status);
CREATE INDEX idx_fetch_jobs_priority ON fetch_jobs(priority, created_at);
```

## CLI

```bash
# Start worker daemon
uv run python -m gaius.workers.cli start

# Submit job
uv run python -m gaius.workers.cli submit arxiv 2312.12345

# Check status
uv run python -m gaius.workers.cli status

# List pending jobs
uv run python -m gaius.workers.cli list --status pending --limit 20
```

## Configuration

```python
@dataclass
class WorkerConfig:
    database_url: str = "postgresql://gaius:gaius@localhost:5432/gaius"
    hx_enabled: bool = True          # Store in HX data lake
    kb_enabled: bool = True          # Create KB summaries
    summarize_on_fetch: bool = False # Immediate summarization
```

Environment variables:
- `GAIUS_WORKER_COUNT`: Number of workers
- `GAIUS_POLL_INTERVAL`: Seconds between polls

## See Also

- [Parent README](../README.md) — Module overview
- [HX README](../hx/README.md) — Content storage
- [Flows README](../flows/README.md) — Processing pipelines
