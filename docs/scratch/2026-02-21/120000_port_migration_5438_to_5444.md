# PostgreSQL Port Migration: 5438 → 5444

## Motivation

Another devenv project was shadowing port 5438, preventing `devenv up` from working. The automatic port allocation feature in devenv hasn't been released yet (on `main`, expected in v1.12). Changing the port is the pragmatic fix.

## What Changed

### Phase 1: Centralized `get_database_url()`

- **`gaius.core.config.get_database_url()`** is now the single source of truth
- **`config/base.conf`** default updated to 5444
- **`DatabaseConfig.url`** default updated to 5444
- Legacy `get_database_url()` functions in `storage/database.py`, `storage/grid_state.py`, `inference/routing_analytics.py`, and `storage/profile_ops.py` now delegate to `core.config`

### Phase 2: Fixed ~65 hardcoded DB URLs in source

Replaced every `os.environ.get("DATABASE_URL", "postgres://...5438/...")` with `from gaius.core.config import get_database_url`. Also fixed ~15 files that had wrong port (5432) and/or wrong database name ("gaius" instead of "zndx_gaius"):

- Engine services (12 files)
- Health module (2 files)
- Flows module (5 files)
- TUI/CLI/MCP (3 files, ~20 instances)
- Other modules (6 files)

### Phase 3: Infrastructure

- `devenv.nix`: `port = 5444;`, shell scripts use `$PGPORT`
- `.env`: `DATABASE_URL=postgres://localhost:5444/...`
- `bin/gaius-mcp`: uses `${PGPORT:-5444}`
- K8s, Tilt, Ansible, CI: all updated to 5444

### Phase 4: Documentation

- `CLAUDE.md`, `README.md`, agent configs, test READMEs
- All scratch docs updated

## Not Changed

- `infra/playbooks/endpoint_lifecycle.yml:105` — HTTP API URL, not postgres

## Verification

```bash
# No hardcoded 5438 in source (should return zero results)
grep -rn "5438" src/gaius/ --include='*.py'

# No wrong-port bugs
grep -rn "localhost:5432/gaius" src/gaius/

# Delegate functions exist
grep -rn "def get_database_url" src/gaius/

# After devenv re-entry:
PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius -c "SELECT 1"
```

## Post-Migration Steps

1. Exit and re-enter devenv shell (`exit` then `cd /path/to/gaius`)
2. Run `devenv up` — postgres will start on port 5444
3. Verify: `pg_isready -p 5444`
