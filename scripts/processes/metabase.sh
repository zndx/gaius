#!/usr/bin/env bash
# scripts/processes/metabase.sh — Metabase Business Intelligence Dashboard
# Launched by devenv process-compose; see devenv.nix processes.metabase
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

check_disabled DISABLE_METABASE "Metabase"

banner "METABASE - Business Intelligence Dashboard"

wait_for_postgres

# Metabase data directory — DEVENV_ROOT is set by the exec block in devenv.nix
METABASE_DATA_DIR="${DEVENV_ROOT:-.}/.devenv/state/metabase"
mkdir -p "$METABASE_DATA_DIR"

echo ""
echo "Starting Metabase on port 3100..."
echo "  URL:        http://0.0.0.0:3100"
echo "  External:   http://tinybox.dev.vista.zndx.org:3100"
echo "  Data dir:   $METABASE_DATA_DIR"
echo ""

# Metabase configuration via environment variables
export MB_JETTY_HOST="0.0.0.0"
export MB_JETTY_PORT="3100"

# Use PostgreSQL for Metabase application database (not H2)
export MB_DB_TYPE="postgres"
export MB_DB_HOST="127.0.0.1"
export MB_DB_PORT="$PGPORT"
export MB_DB_DBNAME="zndx_gaius"
export MB_DB_USER="$USER"
export MB_DB_PASS=""

# Metabase stores its own metadata in 'metabase_*' tables
# This is separate from our 'meta' schema for analytics

# METABASE_PACKAGE is set by the exec block in devenv.nix (points to Nix store path)
exec "${METABASE_PACKAGE}/bin/metabase"
