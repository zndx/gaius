#!/usr/bin/env bash
# scripts/lib/process-helpers.sh — Shared helpers for devenv process scripts
#
# Source this file from process scripts:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/../lib/process-helpers.sh"

# devenv assigns PGPORT so projects and worktrees do not collide.
# systemd may pin this checkout's postgresql.auto.conf to the lattice
# contract (5444). Prefer a *live* assignment; never invent a third port.
_gaius_pgdata() {
  if [[ -n "${PGDATA:-}" ]]; then
    printf '%s\n' "$PGDATA"
    return
  fi
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  printf '%s\n' "${here}/.devenv/state/postgres"
}

_gaius_conf_port() {
  local pgdata="$1" conf
  for conf in "$pgdata/postgresql.auto.conf" "$pgdata/postgresql.conf"; do
    [[ -f "$conf" ]] || continue
    sed -n 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$conf" | tail -1
    return 0
  done
  return 1
}

gaius_effective_pg_port() {
  local assigned="${PGPORT:-}"
  local configured
  configured="$(_gaius_conf_port "$(_gaius_pgdata)" || true)"
  if [[ -n "$assigned" ]] && pg_isready -h 127.0.0.1 -p "$assigned" >/dev/null 2>&1; then
    printf '%s\n' "$assigned"
    return 0
  fi
  if [[ -n "$configured" ]] && pg_isready -h 127.0.0.1 -p "$configured" >/dev/null 2>&1; then
    printf '%s\n' "$configured"
    return 0
  fi
  printf '%s\n' "${assigned:-${configured:-5444}}"
}

# dotenv DATABASE_URL is static. Follow the port we will actually wait on.
export DATABASE_URL="postgres://localhost:$(gaius_effective_pg_port)/zndx_gaius?sslmode=disable"

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
  local assigned="${PGPORT:-unset}"
  local port
  echo "Waiting for PostgreSQL (devenv assigned ${assigned})..."
  for i in $(seq 1 30); do
    port="$(gaius_effective_pg_port)"
    if pg_isready -h 127.0.0.1 -p "$port" -U "$user" >/dev/null 2>&1; then
      export PGPORT="$port"
      export DATABASE_URL="postgres://localhost:${port}/zndx_gaius?sslmode=disable"
      echo "  PostgreSQL ready on :${port}"
      return 0
    fi
    if [ "$i" -eq 30 ]; then
      echo "ERROR: PostgreSQL not ready after 30s (devenv assigned ${assigned})"
      echo "  Try: /health fix postgres"
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

# Wait until nothing is rewriting the shared venv. devenv's
# languages.python.uv.sync re-syncs .devenv/state/venv on every environment
# entry, and an entry that coincides with process startup rewrites torch under
# a launching vLLM (2026-09-03 18:26: `_C_stable_libtorch.abi3.so: undefined
# symbol: torch_from_blob`, thinking FAILED, recovered only on retry). Wait
# for (a) no live `uv sync` / `uv pip install|uninstall` / syncing `uv run`,
# and (b) site-packages untouched for a few seconds. Outer net only — a
# dead-looking sync must not hold the boot forever (fail-open with a warning).
# Usage: wait_for_venv_quiescent [net_seconds]
# Is uv mutating the venv right now? uv holds an flock on <venv>/.lock for
# the whole of a sync / pip install ("Failed to acquire environment lock"
# is its own error text), so a non-blocking flock probe is the precise
# signal. Process heuristics are NOT: `uv run` supervises its child for
# the child's lifetime (the signals engine has been `uv run python -m
# signals.engine` for days), so a live `uv run` says nothing about syncing.
_uv_venv_mutation() {
  local venv="$1"
  [[ -f "$venv/.lock" ]] || return 1
  if ! flock -n "$venv/.lock" true 2>/dev/null; then
    echo "uv environment lock held (${venv}/.lock)"
    return 0
  fi
  return 1
}

wait_for_venv_quiescent() {
  local net="${1:-300}"
  local here venv sp waited=0 busy newest
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  venv="${here}/.devenv/state/venv"
  sp="${venv}/lib/python3.12/site-packages"
  echo "Waiting for venv quiescence (${venv})..."
  while :; do
    busy="$(_uv_venv_mutation "$venv" || true)"
    if [[ -z "$busy" && -d "$sp" ]]; then
      newest="$(find "$sp" -maxdepth 1 -newermt '-5 seconds' -print -quit 2>/dev/null || true)"
      [[ -n "$newest" ]] && busy="site-packages changed <5s ago"
    fi
    if [[ -z "$busy" ]]; then
      echo "  venv quiescent (waited ${waited}s)"
      return 0
    fi
    if (( waited >= net )); then
      echo "WARNING: venv still busy after ${net}s (${busy}) — proceeding (fail-open)"
      return 0
    fi
    (( waited % 15 == 0 )) && echo "  ${busy} — waiting (${waited}s)"
    sleep 3
    waited=$(( waited + 3 ))
  done
}

# Converge the venv to uv.lock BEFORE the engine imports from it, so every
# later sync (devenv re-evaluates ~120 s into `devenv up` when its daemon
# start times out — 2026-09-03 18:26 and 22:20 — and on every shell entry)
# is a write-free audit instead of a rewrite under a launching vLLM.
# --frozen: never touch the lock. --inexact: keep the hand-installed
# extras (impyla, kerberos, h5py, pyluxcore, signals…) a strict sync would
# prune. Fail-open with a loud warning: a sync that cannot run (network,
# cache) must not hold the boot when the venv may already be fine — the
# engine's own imports fail fast if it is not.
# Usage: converge_venv [net_seconds]
converge_venv() {
  local net="${1:-600}" here rc out
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  if ! command -v uv >/dev/null 2>&1; then
    echo "WARNING: uv not on PATH — venv not converged (#EN.00000019.VENVSYNC)"
    return 0
  fi
  echo "Converging venv to uv.lock (frozen, inexact)..."
  out="$(cd "$here" && timeout "$net" uv sync --inexact --frozen 2>&1)"; rc=$?
  if (( rc == 0 )); then
    echo "  $(printf '%s\n' "$out" | grep -E 'Audited|Installed|Uninstalled|Resolved' | tr '\n' ' ')"
  else
    echo "WARNING: uv sync --inexact --frozen exited $rc — proceeding (#EN.00000019.VENVSYNC)"
    printf '%s\n' "$out" | tail -5
  fi
  return 0
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
