#!/usr/bin/env bash
# scripts/processes/metaflow-bootstrap.sh — Metaflow K8s Bootstrap (one-shot)
# Deploys Metaflow service + UI to RKE2 Kubernetes using tilt ci.
# Idempotent: skips deploy if pods already running.
# Launched by devenv process-compose; see devenv.nix processes.metaflow-bootstrap
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

check_disabled_exit DISABLE_METAFLOW "Metaflow"

banner "METAFLOW BOOTSTRAP - K8s Deployment"

# When Signals Engine/Status supplies scheduler (and :30180 answers),
# platform Metaflow is SoR. Do not tilt-deploy a competing service.
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROBE_PY="$ROOT/.devenv/state/venv/bin/python"
if [[ ! -x "$PROBE_PY" ]]; then
  PROBE_PY="python3"
fi
if MODE_OUT="$("$PROBE_PY" -c 'from gaius.flows.platform_metaflow import resolve_metaflow_mode; print(resolve_metaflow_mode().mode)' 2>/tmp/gaius-mf-probe.err)"; then
  if [[ "$MODE_OUT" == "platform" ]]; then
    echo "Signals platform Metaflow is SoR (Engine/Status + :30180) — skip Gaius Tilt"
    exit 0
  fi
else
  if grep -q '#MF.0000000[56]' /tmp/gaius-mf-probe.err 2>/dev/null; then
    cat /tmp/gaius-mf-probe.err >&2
    exit 1
  fi
  echo "  platform probe unavailable — continuing with Gaius-local bootstrap"
  cat /tmp/gaius-mf-probe.err >&2 || true
fi

# Always set from $HOME — env.KUBECONFIG can't be set in Nix daemon mode
export KUBECONFIG="$HOME/.config/kube/rke2.yaml"

# 1. Verify K8s connectivity
echo "Checking Kubernetes connectivity..."
if ! kubectl cluster-info &>/dev/null; then
  echo "ERROR: Cannot reach K8s cluster."
  echo "  Run: sudo systemctl start rke2-server"
  exit 1
fi
echo "  Kubernetes cluster accessible"

# 2. Apply NodePort services (bridge K8s -> host)
echo "Applying NodePort services..."
kubectl apply -f infra/k8s/devenv-services.yaml
echo "  NodePort services applied"

# 2b. Align host-side Endpoints with devenv's EFFECTIVE ports. The devenv
# daemon's port allocator may shift Postgres off its declared port when stacks
# launch concurrently (PGPORT carries the truth). The manifest keeps the
# declared lattice — in-cluster consumers dial devenv-postgres:5444 and
# devenv-rustfs:9010 (Signals' RustFS; strict ports, never shifted) — and only
# the host side of the bridge follows the allocator. Runs before the
# skip-if-running gate so existing pods heal without a redeploy.
kubectl patch endpoints devenv-postgres --type=json -p="[
  {\"op\":\"replace\",\"path\":\"/subsets/0/ports/0/port\",\"value\":${PGPORT:-5444}}]"
echo "  Endpoints aligned to effective ports (pg:${PGPORT:-5444}; rustfs fixed at 9010/9011)"

# 3. Skip if already healthy
if kubectl get pods -l app.kubernetes.io/name=metaflow-service \
     --no-headers 2>/dev/null | grep -q Running; then
  echo "  Metaflow already running -- skipping deploy"
  exit 0
fi

# 4. Deploy via tilt ci (one-shot, exits when healthy)
echo ""
echo "Deploying Metaflow to K8s via tilt ci..."
cd infra/tilt
tilt ci --timeout 300s -- --argo=false
echo ""
echo "  Metaflow deployed successfully"
