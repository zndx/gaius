#!/usr/bin/env bash
# Shared helpers for scripts/systemd_{start,stop}.sh.
# Source after ROOT is set. Co-tenant-safe: only touch cwd == Gaius checkout.

: "${ROOT:?systemd-unit.sh: ROOT must be set}"

GRPC_PORT="${GAIUS_ENGINE_GRPC_PORT:-50051}"
PGDATA_GAIUS="${GAIUS_PGDATA:-$ROOT/.devenv/state/postgres}"
UNIT_NAME="${GAIUS_SYSTEMD_UNIT:-gaius.service}"
UI_PORT="${GAIUS_UI_PORT:-9890}"

info() { echo "gaius.service: $*"; }

# Optional: only if the unit still exports GAIUS_DEVENV_RUNTIME (legacy).
# Default is devenv's own runtime so systemd and a login-shell `devenv up`
# share one process-compose graph.
export_unit_runtime() {
  if [[ -n "${GAIUS_DEVENV_RUNTIME:-}" ]]; then
    mkdir -p "$GAIUS_DEVENV_RUNTIME"
    export DEVENV_RUNTIME="$GAIUS_DEVENV_RUNTIME"
  fi
  if [[ -d "/run/user/$(id -u)" ]]; then
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  fi
}

# Same graph as a laptop `devenv up -d`. Do not pin PGPORT — devenv assigns
# it so projects and worktrees do not collide. secretspec is devenv's.
lattice_up() {
  export_unit_runtime
  /bin/bash -lc "cd \"$ROOT\" && export PATH=\"/usr/local/bin:\$PATH\" && \
    export XDG_RUNTIME_DIR=\"${XDG_RUNTIME_DIR:-}\" && \
    ${DEVENV_RUNTIME:+export DEVENV_RUNTIME=\"$DEVENV_RUNTIME\" &&} \
    devenv up -d"
}

lattice_down() {
  export_unit_runtime
  /bin/bash -lc "cd \"$ROOT\" && export PATH=\"/usr/local/bin:\$PATH\" && \
    export XDG_RUNTIME_DIR=\"${XDG_RUNTIME_DIR:-}\" && \
    ${DEVENV_RUNTIME:+export DEVENV_RUNTIME=\"$DEVENV_RUNTIME\" &&} \
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

ui_ok() {
  ss -ltnH 2>/dev/null | grep -qE ":${UI_PORT}[[:space:]]"
}

# True if pid is a descendant of this checkout's process-compose.
owned_by_compose() {
  local pid="$1" p cmd cwd i
  p="$pid"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    [[ -n "$p" && "$p" != 0 ]] || return 1
    cmd=$(ps -p "$p" -o args= 2>/dev/null || true)
    if [[ "$cmd" == *process-compose* || "$cmd" == *devenv-wrapped*daemon-processes* ]]; then
      cwd=$(readlink "/proc/${p}/cwd" 2>/dev/null || true)
      [[ -z "$cwd" || "$cwd" == "$ROOT" ]] && return 0
    fi
    p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' ')
  done
  return 1
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
  status_ok || return 1
  n=$(listener_count)
  [[ "${n:-0}" -eq 1 ]] || return 1
  pid=$(listener_pids | head -1)
  [[ -n "$pid" ]] || return 1
  owned_by_compose "$pid"
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
