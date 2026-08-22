#!/usr/bin/env bash
# signals.target membership hook. devenv owns the process graph
# (`devenv up -d`). systemd and a login-shell `devenv processes` are
# the same surface. Accept is Engine/Status at bind from that compose.
# setsid / PPID-1 python is test-only while devenv is down.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"
# shellcheck source=lib/systemd-unit.sh
source "$ROOT/scripts/lib/systemd-unit.sh"

POLL_ITERS="${GAIUS_SYSTEMD_POLL_ITERS:-180}"
POLL_SLEEP="${GAIUS_SYSTEMD_POLL_SLEEP:-5}"
FORCED_ENGINE_RESTART=0

export_unit_runtime

# Skip only when Engine/Status is up AND a login-shell `devenv processes`
# sees the same compose. A setsid leftover is not enough.
if unit_already_ready && compose_visible; then
  info "already READY (login-visible compose, Engine/Status :${GRPC_PORT}) — skip up"
  exit 0
fi

if ! compose_visible; then
  info "login-shell devenv cannot see this checkout's compose — reaping leftover daemons"
  reap_gaius_compose
fi

if [[ "$(listener_count)" -gt 0 ]]; then
  info "reaping foreign :${GRPC_PORT} listeners (not process-compose) before devenv up"
  reap_foreign_engines
fi

if ! compose_visible; then
  info "starting devenv graph (devenv up -d; gaius-engine :${GRPC_PORT})"
  if ! lattice_up; then
    info "up reported failure — will still poll (stack may already be live)"
  fi
fi

for i in $(seq 1 "$POLL_ITERS"); do
  n=$(listener_count)
  if [[ "${n:-0}" -gt 1 ]]; then
    info "Guru: #EN.00000014.DUALBIND ${n} listeners on :${GRPC_PORT}" >&2
    ss -ltnpH 2>/dev/null | grep -E ":${GRPC_PORT}[[:space:]]" >&2 || true
    info "  Try: sudo systemctl restart gaius.service" >&2
    info "   or: devenv processes restart gaius-engine" >&2
    exit 1
  fi
  if unit_already_ready && compose_visible; then
    info "compose-owned Engine/Status ready on :${GRPC_PORT} (iter=$i)"
    exit 0
  fi
  if [[ "$FORCED_ENGINE_RESTART" -eq 0 && "$i" -ge 12 ]]; then
    FORCED_ENGINE_RESTART=1
    lattice_restart_engine || info "gaius-engine restart returned $?"
  fi
  if (( i % 6 == 0 )); then
    info "waiting… iter=$i status=$(status_ok && echo ok || echo no) listeners=${n:-0} compose=$(compose_visible && echo yes || echo no)"
  fi
  sleep "$POLL_SLEEP"
done

info "timed out waiting for compose-owned Engine/Status on :${GRPC_PORT}" >&2
info "  Guru: #EN.00000016.NOTUNIT" >&2
info "  Try: sudo systemctl restart gaius.service" >&2
info "   or: devenv processes restart gaius-engine" >&2
exit 1
