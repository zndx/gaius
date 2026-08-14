#!/usr/bin/env bash
# Shared helpers for scripts/systemd_{start,stop}.sh.
# Source after ROOT is set. Co-tenant-safe: only touch cwd == Gaius checkout.

: "${ROOT:?systemd-unit.sh: ROOT must be set}"

GRPC_PORT="${GAIUS_ENGINE_GRPC_PORT:-50051}"
PG_PORT="${GAIUS_PG_PORT:-5444}"
PGDATA_GAIUS="${GAIUS_PGDATA:-$ROOT/.devenv/state/postgres}"
UNIT_NAME="${GAIUS_SYSTEMD_UNIT:-gaius.service}"
# Dedicated compose instance for the systemd unit — never the interactive
# $XDG_RUNTIME_DIR/devenv-<hash> leftover from a login-shell `devenv up`.
GAIUS_DEVENV_RUNTIME="${GAIUS_DEVENV_RUNTIME:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/gaius-systemd}"

info() { echo "gaius.service: $*"; }

export_unit_runtime() {
  mkdir -p "$GAIUS_DEVENV_RUNTIME"
  export DEVENV_RUNTIME="$GAIUS_DEVENV_RUNTIME"
  if [[ -d "/run/user/$(id -u)" ]]; then
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  fi
}

lattice_up() {
  export_unit_runtime
  export PGPORT="$PG_PORT"
  export DATABASE_URL="postgres://localhost:${PG_PORT}/zndx_gaius?sslmode=disable"
  /bin/bash -lc "cd \"$ROOT\" && export PATH=\"/usr/local/bin:\$PATH\" && \
    export DEVENV_RUNTIME=\"$DEVENV_RUNTIME\" && \
    export XDG_RUNTIME_DIR=\"${XDG_RUNTIME_DIR:-}\" && \
    export PGPORT=\"$PG_PORT\" && \
    export DATABASE_URL=\"$DATABASE_URL\" && \
    (just up 2>/dev/null || devenv up -d)"
}

lattice_down() {
  export_unit_runtime
  /bin/bash -lc "cd \"$ROOT\" && export PATH=\"/usr/local/bin:\$PATH\" && \
    export DEVENV_RUNTIME=\"$DEVENV_RUNTIME\" && \
    export XDG_RUNTIME_DIR=\"${XDG_RUNTIME_DIR:-}\" && \
    (just down 2>/dev/null || devenv processes down || true)" || true
}

# PIDs of devenv process-compose daemons whose cwd is this checkout.
gaius_compose_pids() {
  local pid cwd args
  while read -r pid args; do
    [[ "$args" == *devenv-wrapped*daemon-processes* ]] || continue
    cwd=$(readlink "/proc/${pid}/cwd" 2>/dev/null || true)
    [[ "$cwd" == "$ROOT" ]] || continue
    printf '%s\n' "$pid"
  done < <(ps -eo pid=,args=)
}

listener_pids() {
  ss -ltnpH 2>/dev/null | awk -v p=":${GRPC_PORT}" '
    $4 ~ p"$" {
      if (match($0, /pid=[0-9]+/)) print substr($0, RSTART+4, RLENGTH-4)
    }' | sort -u
}

listener_count() {
  ss -ltnH 2>/dev/null | grep -cE ":${GRPC_PORT}[[:space:]]" || true
}

is_gaius_engine() {
  local cmd
  cmd=$(ps -p "$1" -o args= 2>/dev/null || true)
  [[ "$cmd" == *gaius.engine* ]]
}

# True if pid is in this unit's cgroup (system or user instance).
in_unit_cgroup() {
  local pid="$1" cg
  [[ -r "/proc/${pid}/cgroup" ]] || return 1
  cg=$(tr -d '\n' < "/proc/${pid}/cgroup")
  [[ "$cg" == *"${UNIT_NAME}"* ]]
}

status_ok() {
  local py="${ROOT}/.devenv/state/venv/bin/python"
  [[ -x "$py" ]] || py=python3
  GAIUS_ENGINE_GRPC_PORT="${GRPC_PORT}" "$py" "$ROOT/scripts/zndx_status_ok.py" >/dev/null 2>&1
}

# Contract port only — devenv's allocator must not silently move us to :5445.
postgres_ok() {
  pg_isready -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1
}

# Leftover session postmaster holding PGDATA (often on a shifted port).
# Do not touch Signals :5455 or sibling peer databases.
stop_orphan_gaius_postgres() {
  local pidfile="$PGDATA_GAIUS/postmaster.pid"
  local pid="" i envpg
  if [[ -f "$pidfile" ]]; then
    pid=$(head -1 "$pidfile" 2>/dev/null || true)
  fi
  if [[ -n "$pid" ]] && [[ -d "/proc/$pid" ]]; then
    envpg=$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | sed -n 's/^PGDATA=//p' || true)
    if [[ "$envpg" == "$PGDATA_GAIUS" ]] || \
       [[ "$(readlink "/proc/$pid/cwd" 2>/dev/null || true)" == "$PGDATA_GAIUS" ]]; then
      info "TERM leftover Gaius postmaster pid=$pid (PGDATA=$PGDATA_GAIUS)"
      kill -TERM "$pid" 2>/dev/null || true
      for i in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$pid" 2>/dev/null; then
        info "KILL leftover Gaius postmaster pid=$pid"
        kill -KILL "$pid" 2>/dev/null || true
      fi
    fi
  fi
  if [[ -f "$pidfile" ]] && ! kill -0 "$(head -1 "$pidfile" 2>/dev/null || echo 0)" 2>/dev/null; then
    info "removing stale $pidfile"
    rm -f "$pidfile"
  fi
}

# Skip-up only when the *unit* already owns the single ready listener.
unit_already_ready() {
  local n pid
  n=$(listener_count)
  [[ "${n:-0}" -eq 1 ]] || return 1
  postgres_ok || return 1
  status_ok || return 1
  pid=$(listener_pids | head -1)
  [[ -n "$pid" ]] || return 1
  in_unit_cgroup "$pid"
}

term_pid() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || return 0
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
}

kill_pid() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || return 0
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
}

# Reap leftover interactive /tmp compose daemons for THIS checkout only.
reap_gaius_compose() {
  local pid still i
  for pid in $(gaius_compose_pids); do
    info "TERM devenv compose pid=$pid (cwd=$ROOT)"
    term_pid "$pid"
  done
  for i in $(seq 1 20); do
    still=$(gaius_compose_pids || true)
    [[ -z "${still}" ]] && break
    sleep 1
  done
  for pid in $(gaius_compose_pids); do
    info "KILL devenv compose pid=$pid after grace"
    kill_pid "$pid"
  done
}

reap_gaius_engines() {
  local pid i
  for pid in $(listener_pids); do
    is_gaius_engine "$pid" || continue
    info "TERM engine pid=$pid"
    term_pid "$pid"
  done
  sleep 3
  for pid in $(listener_pids); do
    is_gaius_engine "$pid" || continue
    info "KILL engine pid=$pid after grace"
    kill_pid "$pid"
  done
  for i in $(seq 1 10); do
    [[ "$(listener_count)" -eq 0 ]] && break
    sleep 1
  done
}
