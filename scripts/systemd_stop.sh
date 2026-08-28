#!/usr/bin/env bash
# Full unit stop: devenv down for the shared login/systemd graph, then
# reap leftover compose daemons for this checkout, then free :50051.
# Does not run just teardown / gpu-deep-cleanup (sibling GPU leases).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:${HOME}/.nix-profile/bin:${PATH:-}"
# shellcheck source=lib/systemd-unit.sh
source "$ROOT/scripts/lib/systemd-unit.sh"

info "stop (shared devenv graph; XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-})"
lattice_down
reap_gaius_compose
reap_gaius_engines
stop_orphan_gaius_postgres

# Reap gaius MiNIFi sentinel pods (K8s stand-ins for gaius GPU/compute workloads)
# so a unit restart is a COMPLETE recycle: the fresh engine admits from a clean
# slate instead of racing a stale gaius-thinking sentinel. These are K8s objects,
# not GPU leases, so this does not touch sibling projects' GPU workloads. Best
# effort — on a full reboot k8s may already be down (pods die with the node).
KUBECONFIG="${KUBECONFIG:-$HOME/.config/kube/rke2.yaml}" \
  kubectl -n federation-signals delete pods \
    -l 'federation.project=gaius,app.kubernetes.io/component=minifi-sentinel' \
    --ignore-not-found --wait=false >/dev/null 2>&1 \
  && info "reaped gaius sentinel pods" \
  || info "sentinel reap skipped (kubectl/k8s unavailable)"

if [[ "$(listener_count)" -gt 0 ]]; then
  info "WARN :${GRPC_PORT} still listening after stop" >&2
  ss -ltnpH 2>/dev/null | grep -E ":${GRPC_PORT}[[:space:]]" >&2 || true
  exit 1
fi
info ":${GRPC_PORT} free; no Gaius compose leftovers"
