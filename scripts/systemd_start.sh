#!/usr/bin/env bash
# Oneshot start for gaius.service. Unit owns the devenv compose instance
# (DEVENV_RUNTIME=…/gaius-systemd). Skip-up only if *this unit* already has
# the single Engine/Status listener — leftover login-shell stacks do not count.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"
# shellcheck source=lib/systemd-unit.sh
source "$ROOT/scripts/lib/systemd-unit.sh"

POLL_ITERS="${GAIUS_SYSTEMD_POLL_ITERS:-180}"
POLL_SLEEP="${GAIUS_SYSTEMD_POLL_SLEEP:-5}"

if unit_already_ready; then
  info "already READY under ${UNIT_NAME} (Engine/Status :${GRPC_PORT}) — skip up"
  exit 0
fi

# Leftover session compose would win :50051 and leave the unit stack engineless.
if [[ -n "$(gaius_compose_pids || true)" ]] || [[ "$(listener_count)" -gt 0 ]] || ! postgres_ok; then
  info "reaping leftover Gaius compose / :${GRPC_PORT} / orphan postgres before unit up"
  lattice_down
  reap_gaius_compose
  reap_gaius_engines
  stop_orphan_gaius_postgres
fi

info "starting product stack (DEVENV_RUNTIME=${GAIUS_DEVENV_RUNTIME})"
if ! lattice_up; then
  info "up reported failure — will still poll (stack may already be live)"
fi

for i in $(seq 1 "$POLL_ITERS"); do
  if status_ok && postgres_ok && [[ "$(listener_count)" -eq 1 ]]; then
    pid=$(listener_pids | head -1)
    if in_unit_cgroup "$pid"; then
      info "ready :${GRPC_PORT} Status + :${PG_PORT} postgres under ${UNIT_NAME} (iter=$i pid=$pid)"
      exit 0
    fi
    info "Status OK but pid=$pid not in ${UNIT_NAME} — waiting for unit-owned listener"
  elif status_ok && ! postgres_ok; then
    info "Status up but postgres :${PG_PORT} not ready (iter=$i)"
  fi
  sleep "$POLL_SLEEP"
done

info "timed out waiting for unit-owned Engine/Status on :${GRPC_PORT}" >&2
info "  listeners: $(listener_count)  compose: $(gaius_compose_pids | tr '\n' ' ')" >&2
info "  Try: /health fix engine" >&2
exit 1
