# Database Schema

PostgreSQL database `zndx_gaius` on port 5444.

## Connection

```bash
PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius
```

Connection URL: `postgres://gaius:gaius@localhost:5444/zndx_gaius?sslmode=disable`

**Important**: The database name is `zndx_gaius`, not `gaius`.

## Key Tables

### Cards & Content

| Table | Purpose |
|-------|---------|
| `cards` | Card entities with metadata |
| `card_enrichments` | Enrichment data for cards |
| `articles` | Source articles |
| `article_content` | Article text content |

### FMEA & Health

| Table | Purpose |
|-------|---------|
| `fmea_catalog` | Failure mode definitions (S/O/D scores) |
| `fmea_occurrences` | Failure occurrence history |
| `fmea_outcomes` | Remediation outcomes (for adaptive learning) |
| `fmea_approvals` | Pending Tier 2 approvals |
| `healing_events` | Self-healing audit trail |
| `health_observer_state` | Observer daemon state |

### Agents & Evolution

| Table | Purpose |
|-------|---------|
| `agent_versions` | Agent prompt versions with lineage |
| `agent_evaluations` | Evaluation results for evolution |

### Operations

| Table | Purpose |
|-------|---------|
| `activity_log` | System activity tracking |
| `x_bookmarks` | X bookmark sync data |
| `x_bookmark_folders` | X bookmark folder metadata |
| `x_sync_runs` | X sync run history |

## Accessing from Code

Always use the config helper:

```python
from gaius.core.config import get_database_url

url = get_database_url()
```

Never hardcode connection parameters.
