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
