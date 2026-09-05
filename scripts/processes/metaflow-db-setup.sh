#!/usr/bin/env bash
# scripts/processes/metaflow-db-setup.sh — Metaflow Database Setup
# One-shot: creates metaflow user/database in PostgreSQL + MinIO bucket.
# Launched by devenv process-compose; see devenv.nix processes.metaflow-db-setup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

banner "METAFLOW DATABASE SETUP"

wait_for_postgres gaius

# Create metaflow user and database if they don't exist
# Use $USER (superuser) for initial setup since gaius doesn't have CREATEROLE
echo "Ensuring metaflow user and database exist..."
psql -h 127.0.0.1 -p "$PGPORT" -U "$USER" -d zndx_gaius -tc \
  "SELECT 1 FROM pg_roles WHERE rolname = 'metaflow'" | \
  grep -q 1 || \
  psql -h 127.0.0.1 -p "$PGPORT" -U "$USER" -d zndx_gaius -c "CREATE USER metaflow WITH PASSWORD 'metaflow'"

psql -h 127.0.0.1 -p "$PGPORT" -U "$USER" -d zndx_gaius -tc \
  "SELECT 1 FROM pg_database WHERE datname = 'metaflow'" | \
  grep -q 1 || \
  psql -h 127.0.0.1 -p "$PGPORT" -U "$USER" -d zndx_gaius -c "CREATE DATABASE metaflow OWNER metaflow"

# Grant permissions
psql -h 127.0.0.1 -p "$PGPORT" -U "$USER" -d metaflow -c "GRANT ALL PRIVILEGES ON DATABASE metaflow TO metaflow" 2>/dev/null || true
echo "  metaflow user and database ready"

# Ensure the metaflow-artifacts bucket exists on RustFS (Signals, :9010).
echo "Ensuring metaflow-artifacts bucket exists on RustFS..."
mc alias set rustfs "http://localhost:${RUSTFS_PORT:-9010}" "${RUSTFS_ACCESS_KEY:-rustfsadmin}" "${RUSTFS_SECRET_KEY:-rustfsadmin}" 2>/dev/null || true
mc mb --ignore-existing rustfs/metaflow-artifacts 2>/dev/null || true
echo "  RustFS bucket ready"

echo ""
echo "Metaflow database setup complete."
