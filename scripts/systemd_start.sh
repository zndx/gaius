#!/usr/bin/env bash
# signals.target membership hook. devenv owns the process graph
# (`devenv up -d`), ports, and secretspec. Accept is Engine/Status at bind.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"
# shellcheck source=lib/systemd-unit.sh
source "$ROOT/scripts/lib/systemd-unit.sh"

POLL_ITERS="${GAIUS_SYSTEMD_POLL_ITERS:-180}"
POLL_SLEEP="${GAIUS_SYSTEMD_POLL_SLEEP:-5}"

if unit_already_ready; then
  info "already READY (compose-owned Engine/Status :${GRPC_PORT}) — skip up"
  exit 0
fi

if [[ "$(listener_count)" -gt 0 ]]; then
  info "reaping foreign :${GRPC_PORT} listeners before devenv up"
  reap_gaius_engines
fi

info "starting devenv graph (devenv up -d)"
if ! lattice_up; then
  info "up reported failure — will still poll (stack may already be live)"
fi

for i in $(seq 1 "$POLL_ITERS"); do
  if [[ "$(listener_count)" -gt 1 ]]; then
    info "WARN: $(listener_count) listeners on :${GRPC_PORT} (iter=$i)"
  elif unit_already_ready; then
    info "compose-owned Engine/Status ready on :${GRPC_PORT} (iter=$i)"
    exit 0
  fi
  if (( i % 6 == 0 )); then
    info "waiting… iter=$i status=$(status_ok && echo ok || echo no) listeners=$(listener_count)"
  fi
  sleep "$POLL_SLEEP"
done

info "timed out waiting for compose-owned Engine/Status on :${GRPC_PORT}" >&2
info "  devenv processes status   # gaius-engine should be running" >&2
info "  Try: /health fix engine" >&2
exit 1
