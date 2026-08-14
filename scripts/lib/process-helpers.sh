#!/usr/bin/env bash
# scripts/lib/process-helpers.sh — Shared helpers for devenv process scripts
#
# Source this file from process scripts:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/../lib/process-helpers.sh"

# devenv's port allocator may shift postgres off the declared 5444 when
# stacks launch concurrently; it publishes the effective port as PGPORT.
# The dotenv DATABASE_URL is static and can't follow, so every process
# script gets the derived URL (this source-time export wins over dotenv).
export DATABASE_URL="postgres://localhost:${PGPORT:-5444}/zndx_gaius?sslmode=disable"

# Print a box banner
banner() {
  local title="$1"
  printf '╔══════════════════════════════════════════════════════════════╗\n'
  printf '║  %-59s ║\n' "$title"
  printf '╚══════════════════════════════════════════════════════════════╝\n'
  echo ""
}

# Check if process is disabled via env var, exit cleanly if so.
# Usage: check_disabled DISABLE_ENGINE "Gaius Engine"
#   - If the var is "true", prints a message and sleeps forever (keeps process-compose happy).
check_disabled() {
  local var_name="$1"
  local service_name="$2"
  if [ "${!var_name:-false}" == "true" ]; then
    echo "$service_name disabled ($var_name=true)"
    sleep infinity
  fi
}

# Like check_disabled but exits 0 instead of sleeping.
# Use for one-shot processes that shouldn't block.
check_disabled_exit() {
  local var_name="$1"
  local service_name="$2"
  if [ "${!var_name:-false}" == "true" ]; then
    echo "$service_name disabled ($var_name=true)"
    exit 0
  fi
}

# Wait for PostgreSQL to be ready (30s timeout)
# Usage: wait_for_postgres [user]
wait_for_postgres() {
  local user="${1:-postgres}"
  echo "Waiting for PostgreSQL..."
  for i in $(seq 1 30); do
    if pg_isready -h 127.0.0.1 -p "${PGPORT:-5444}" -U "$user" >/dev/null 2>&1; then
      echo "  PostgreSQL ready"
      return 0
    fi
    if [ "$i" -eq 30 ]; then
      echo "ERROR: PostgreSQL not ready after 30s"
      exit 1
    fi
    sleep 1
  done
}

# Fail if a TCP port is already listening. gRPC defaults to SO_REUSEPORT, so a
# second engine would otherwise dual-bind and kernel-lottery Status.
# Usage: assert_tcp_port_free 50051 "gaius-engine lattice"
assert_tcp_port_free() {
  local port="$1"
  local label="${2:-service}"
  if ss -ltnH 2>/dev/null | grep -qE ":${port}[[:space:]]"; then
    echo "#EN.00000014.DUALBIND ${label} :${port} already bound" >&2
    ss -ltnpH 2>/dev/null | grep -E ":${port}[[:space:]]" >&2 || true
    echo "  Try: /health fix engine" >&2
    echo "  Or:  stop the extra devenv daemon holding :${port} (not just 'devenv processes down')" >&2
    exit 1
  fi
}

# Wait for Aeron media driver (30s timeout)
# Usage: wait_for_aeron [aeron_dir]
wait_for_aeron() {
  local aeron_dir="${1:-/dev/shm/gaius-aeron}"
  echo "Waiting for Aeron media driver..."
  for i in $(seq 1 30); do
    if [ -f "$aeron_dir/cnc.dat" ]; then
      echo "  Aeron media driver ready"
      return 0
    fi
    if [ "$i" -eq 30 ]; then
      echo "ERROR: Aeron media driver not ready after 30s"
      exit 1
    fi
    sleep 1
  done
}
