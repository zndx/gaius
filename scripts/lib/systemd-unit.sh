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
# share one process-compose graph. A dedicated runtime splits
# `systemctl restart gaius` from `devenv processes restart gaius-engine`.
export_unit_runtime() {
  if [[ -n "${GAIUS_DEVENV_RUNTIME:-}" ]]; then
    info "WARN GAIUS_DEVENV_RUNTIME=$GAIUS_DEVENV_RUNTIME splits systemd from devenv; unset it"
    mkdir -p "$GAIUS_DEVENV_RUNTIME"
    export DEVENV_RUNTIME="$GAIUS_DEVENV_RUNTIME"
  fi
  if [[ -d "/run/user/$(id -u)" ]]; then
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  fi
}

_devenv_lc() {
  export_unit_runtime
  /bin/bash -lc "cd \"$ROOT\" && export PATH=\"/usr/local/bin:\$PATH\" && \
    export XDG_RUNTIME_DIR=\"${XDG_RUNTIME_DIR:-}\" && \
    ${DEVENV_RUNTIME:+export DEVENV_RUNTIME=\"$DEVENV_RUNTIME\" &&} \
    $*"
}

# Same graph as a laptop `devenv up -d`. Do not pin PGPORT or a dedicated
# DEVENV_RUNTIME. secretspec is devenv's.
lattice_up() {
  _devenv_lc "devenv up -d"
}

lattice_down() {
  _devenv_lc "just down 2>/dev/null || devenv processes down || true" || true
}

# devenv 2.1 can start daemon-processes + native.sock then time out the
# 120s waiter before writing native-manager.pid. Login `devenv processes`
# then says "No process manager" — a second graph. Repair the pid file
# so systemd and devenv are the same surface.
repair_native_manager_pid() {
  local pid cmd dir have
  pid=$(gaius_compose_pids | head -1 || true)
  [[ -n "$pid" ]] || return 1
  cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
  dir="${cmd##* }"
  dir="${dir%/daemon-config.json}"
  [[ -d "$dir" && -S "$dir/native.sock" ]] || return 1
  have=$(cat "$dir/native-manager.pid" 2>/dev/null || true)
  if [[ "$have" == "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  info "repair native-manager.pid=$pid in $dir"
  printf '%s\n' "$pid" > "$dir/native-manager.pid"
}

# Login-shell `devenv processes` can see this checkout's compose.
compose_visible() {
  repair_native_manager_pid || true
  if _devenv_lc "devenv processes list" >/dev/null 2>&1; then
    return 0
  fi
  [[ -n "$(gaius_compose_pids | head -1)" ]]
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

# Walk to the devenv/process-compose ancestor. Prints "pid<TAB>args" or fails.
compose_ancestor() {
  local pid="$1" p cmd i
  p="$pid"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    [[ -n "$p" && "$p" != 0 ]] || return 1
    cmd=$(ps -p "$p" -o args= 2>/dev/null || true)
    if [[ "$cmd" == *process-compose* || "$cmd" == *devenv-wrapped*daemon-processes* ]]; then
      printf '%s\t%s\n' "$p" "$cmd"
      return 0
    fi
    p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' ')
  done
  return 1
}

# True if pid is a descendant of this checkout's process-compose.
owned_by_compose() {
  local pid="$1" anc compose_pid cmd cwd
  anc=$(compose_ancestor "$pid") || return 1
  compose_pid="${anc%%	*}"
  cmd="${anc#*	}"
  cwd=$(readlink "/proc/${compose_pid}/cwd" 2>/dev/null || true)
  [[ -z "$cwd" || "$cwd" == "$ROOT" ]] || return 1
  [[ -n "$cmd" ]]
}

# Alias: systemd and devenv are one surface (checkout process-compose).
owned_by_unit_compose() {
  owned_by_compose "$1"
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

# Skip-up when checkout process-compose already answers Engine/Status.
# systemd and `devenv up` are the same graph. Detached engine is not
# membership (ok only while devenv is down, for tests).
unit_already_ready() {
  local n pid
  status_ok || return 1
  n=$(listener_count)
  [[ "${n:-0}" -eq 1 ]] || return 1
  pid=$(listener_pids | head -1)
  [[ -n "$pid" ]] || return 1
  is_gaius_engine "$pid" || return 1
  owned_by_unit_compose "$pid"
}

# Same surface as `devenv processes restart gaius-engine` from a login shell.
lattice_restart_engine() {
  info "devenv processes restart gaius-engine"
  _devenv_lc "devenv processes restart gaius-engine"
}

# TERM gaius.engine listeners that process-compose does not own (setsid test
# leftovers). Do not kill a checkout compose child — that is the surface.
reap_foreign_engines() {
  local pid
  for pid in $(listener_pids); do
    is_gaius_engine "$pid" || continue
    if owned_by_compose "$pid"; then
      continue
    fi
    info "TERM foreign gaius.engine pid=$pid (not process-compose) #EN.00000016.NOTUNIT"
    kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 2
  for pid in $(listener_pids); do
    is_gaius_engine "$pid" || continue
    if owned_by_compose "$pid"; then
      continue
    fi
    info "KILL foreign gaius.engine pid=$pid after grace"
    kill -KILL "$pid" 2>/dev/null || true
  done
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
