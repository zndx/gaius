#!/usr/bin/env bash
# restart-clean.sh — Full cleanup and fresh restart of devenv services.
#
# Starts the stack as a background daemon (devenv up -d). The daemon persists
# independently of your terminal session. To inspect processes interactively:
#
#   devenv up            # opens process-compose TUI; quitting leaves daemon running
#
# IMPORTANT: This script must run OUTSIDE the devenv environment (not from
# `devenv shell` or after `eval "$(devenv print-dev-env)"`). The devenv
# environment sets vars (VIRTUAL_ENV, DEVENV_*, etc.) that cause devenv-tasks
# processes to deadlock on tasks.db when spawned by process-compose.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  CLEAN RESTART - Full cleanup and fresh start                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

START_TIME=$(date +%s)

# Step 1: Stop devenv processes
echo "Step 1/7: Stopping devenv processes..."
devenv processes down 2>/dev/null || true
sleep 2
echo "  ✓ devenv processes stopped"

# Step 2: Kill process-compose
echo "Step 2/7: Killing process-compose..."
pkill -9 -f process-compose 2>/dev/null || true
sleep 1
echo "  ✓ process-compose killed"

# Step 3: Kill stale service processes
echo "Step 3/7: Killing stale service processes..."
pkill -9 -f "devenv-tasks.*devenv:processes:" 2>/dev/null && echo "  - Killed stale devenv-tasks" || true
pkill -9 -f "minio server" 2>/dev/null && echo "  - Killed minio" || true
pkill -9 -f "qdrant" 2>/dev/null && echo "  - Killed qdrant" || true
pkill -9 -f "gaius.engine" 2>/dev/null && echo "  - Killed gaius.engine" || true
pkill -9 -f "optillm-gunicorn" 2>/dev/null && echo "  - Killed optillm-gunicorn" || true
pkill -9 -f "gaius.workers" 2>/dev/null && echo "  - Killed gaius.workers" || true
pkill -9 -f "aeronmd" 2>/dev/null && echo "  - Killed aeronmd" || true
pkill -9 -f "nifi" 2>/dev/null && echo "  - Killed nifi" || true
pkill -9 -f "prometheus" 2>/dev/null && echo "  - Killed prometheus" || true
pkill -9 -f "otelcol" 2>/dev/null && echo "  - Killed otelcol" || true
pkill -9 -f "metabase" 2>/dev/null && echo "  - Killed metabase" || true
pkill -9 -f ".postgres-wrapp" 2>/dev/null && echo "  - Killed postgres" || true
sleep 1
echo "  ✓ Stale services killed"

# Step 4: Free ports (in case processes didn't release them)
echo "Step 4/7: Freeing ports..."
# Helper: kill PIDs holding a port (uses ss, not fuser — works without psmisc)
kill_port() {
  local port=$1
  local pids
  pids=$(ss -tlnp 2>/dev/null | grep ":${port} " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u)
  if [ -n "$pids" ]; then
    for pid in $pids; do
      kill -9 "$pid" 2>/dev/null && echo "  - Killed PID $pid on port $port"
    done
    return 0
  fi
  return 1
}
# Kill any process holding these ports
for port in 5444 8000 9010 9011 6339 6340 50051 8450 3100 9090 4317 4318 8889; do
  kill_port "$port" || true
done
# Also kill postgres postmaster directly (the wrapper may have exited but postmaster lingers)
pkill -9 -x postgres 2>/dev/null && echo "  - Killed postgres postmaster" || true
sleep 1
# Gate: wait for critical ports to be fully released before proceeding
# Observable: each iteration prints state so we can diagnose hangs
CRITICAL_PORTS="5444 8000 50051"
for port in $CRITICAL_PORTS; do
  for i in $(seq 1 30); do
    if ! ss -tlnp 2>/dev/null | grep -q ":$port "; then
      [ "$i" -gt 1 ] && echo "  - Port $port freed after ${i}s"
      break
    fi
    [ "$i" -eq 1 ] && printf "  - Waiting for port %s..." "$port"
    [ "$((i % 5))" -eq 0 ] && printf " %ds" "$i"
    if [ "$i" -eq 30 ]; then
      echo " TIMEOUT (forcing)"
      kill_port "$port" || true
    fi
    sleep 1
  done
done
echo "  ✓ Ports freed"

# Step 5: Clean up stale sockets and runtime state
echo "Step 5/7: Cleaning stale sockets..."
rm -rf "/run/user/$(id -u)/devenv-"*/ 2>/dev/null || true
rm -rf /tmp/devenv-*/ 2>/dev/null || true  # fallback location if XDG_RUNTIME_DIR was unset
rm -rf /dev/shm/gaius-aeron 2>/dev/null || true
echo "  ✓ Stale sockets removed"

# Step 6: Remove stale postgres state
echo "Step 6/7: Cleaning stale postgres state..."
POSTGRES_PID_FILE=".devenv/state/postgres/postmaster.pid"
if [ -f "$POSTGRES_PID_FILE" ]; then
  rm -f "$POSTGRES_PID_FILE"
  echo "  - Postgres lock file removed"
fi
# Clean up shared memory segments left by SIGKILL'd postgres
for shmid in $(ipcs -m 2>/dev/null | awk -v user="$(whoami)" '$3 == user {print $2}'); do
  ipcrm -m "$shmid" 2>/dev/null && echo "  - Removed shared memory segment $shmid"
done
echo "  ✓ Postgres state cleaned"

# Step 7: Pre-warm devenv-tasks cache
# Without this, concurrent devenv-tasks processes deadlock on tasks.db
# when all try to run the same oneshot prerequisites simultaneously.
echo "Step 7/7: Warming tasks cache..."
rm -f .devenv/tasks.db .devenv/tasks.db-shm .devenv/tasks.db-wal
devenv tasks run devenv:enterShell 2>/dev/null || true
echo "  ✓ Tasks cache warm"

echo ""
echo "Starting devenv (background daemon)..."
devenv up -d
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Waiting for gRPC engine on port 50051...                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

MAX_CYCLES=60
CYCLE=0
while [ $CYCLE -lt $MAX_CYCLES ]; do
  CYCLE=$((CYCLE + 1))
  ELAPSED=$(($(date +%s) - START_TIME))

  if nc -zv localhost 50051 2>/dev/null; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  ✓ ENGINE READY (background daemon)                          ║"
    echo "╠══════════════════════════════════════════════════════════════╣"
    printf "║  Elapsed: %3ds | Cycles: %2d                                  ║\n" "$ELAPSED" "$CYCLE"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    # Phase 2: Wait for GPU endpoints to load models
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  Waiting for GPU endpoints to load...                        ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    uv run python scripts/lib/wait-for-endpoints.py --timeout 300 || {
        echo ""
        echo "  ⚠ Endpoints not fully loaded (check: uv run gaius-cli --cmd \"/gpu status\")"
    }

    echo ""
    TOTAL_ELAPSED=$(($(date +%s) - START_TIME))
    echo "╔══════════════════════════════════════════════════════════════╗"
    printf "║  Total time: %3ds                                            ║\n" "$TOTAL_ELAPSED"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  Inspect:  devenv up      (TUI — quit leaves daemon running) ║"
    echo "║  Logs:     tail -f .devenv/processes.log                     ║"
    echo "║  Stop:     devenv processes down                             ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    exit 0
  fi

  printf "\r  Waiting... [%3ds elapsed, cycle %2d/%d]" "$ELAPSED" "$CYCLE" "$MAX_CYCLES"
  sleep 2
done

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✗ ENGINE FAILED TO START                                    ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Check logs: tail -f .devenv/processes.log                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
exit 1
