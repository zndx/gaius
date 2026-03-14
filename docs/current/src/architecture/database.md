# Database

Gaius uses PostgreSQL on port **5444** with database name **`zndx_gaius`** (not `gaius`).

## Connection

| Parameter | Value |
|-----------|-------|
| Host | `localhost` |
| Port | `5444` |
| Database | `zndx_gaius` |
| User | `gaius` |
| Password | `gaius` |
| URL | `postgres://gaius:gaius@localhost:5444/zndx_gaius?sslmode=disable` |

### Programmatic Access

Always use the centralized config function -- never hardcode connection parameters:

```python
from gaius.core.config import get_database_url

url = get_database_url()  # Single source of truth
```

Delegates exist in `storage/database.py`, `storage/grid_state.py`, `inference/routing_analytics.py`, and `storage/profile_ops.py` -- all call through to `gaius.core.config.get_database_url()`.

### CLI Access

```bash
PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius
```

## Connection Pooling

The `storage/database.py` module manages a global `asyncpg` connection pool (min 1, max 10 connections) via `get_pool()`:

```python
from gaius.storage.database import get_pool

pool = await get_pool()
async with pool.acquire() as conn:
    rows = await conn.fetch("SELECT ...")
```

## Schemas

The database uses four schemas to organize data. See [Schema Design](./schema.md) for details.

| Schema | Purpose |
|--------|---------|
| `public` | Core operational tables (cards, agents, evolution, health) |
| `meta` | Analytics views for [Metabase](./metabase.md) dashboards |
| `collections` | Curated content for the public landing page |
| `bases` | Feature store registry and Iceberg catalog |

## Extensions

| Extension | Purpose |
|-----------|---------|
| `pg_cron` | [Scheduled maintenance](./pgcron.md) |
| `age` (Apache AGE) | Graph queries for lineage |
| `citext` | Case-insensitive text columns |

## Migrations

Schema migrations live in `db/migrations/` and are ordered by timestamp prefix (e.g., `20251130000001_initial_schema.sql`). The full schema dump is at `db/schema.sql`.
