#!/usr/bin/env bash
# scripts/processes/metaflow-port-forwards.sh — Metaflow Port Forwards
# Creates port-forwards bound to 0.0.0.0 for external access from laptops.
# Tilt's port-forwards only bind to localhost.
# Launched by devenv process-compose; see devenv.nix processes.metaflow-port-forwards
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

check_disabled DISABLE_METAFLOW "Metaflow"

banner "METAFLOW PORT FORWARDS - External Access"

# Always set from $HOME — env.KUBECONFIG can't be set in Nix daemon mode
export KUBECONFIG="$HOME/.config/kube/rke2.yaml"

# Wait for K8s cluster and metaflow-service pod to be ready
# Self-sufficient: works whether bootstrap ran or pods were already up
echo "Waiting for Metaflow pods to be ready..."
MAX_WAIT=300
WAITED=0
while true; do
  if kubectl get pods -l app.kubernetes.io/name=metaflow-service \
       --no-headers 2>/dev/null | grep -q Running; then
    break
  fi
  WAITED=$((WAITED + 5))
  if [ $WAITED -ge $MAX_WAIT ]; then
    echo "ERROR: Metaflow pods not running after ${MAX_WAIT}s"
    echo "  Check: kubectl get pods"
    exit 1
  fi
  echo "  Waiting for metaflow-service pod... (${WAITED}s)"
  sleep 5
done
echo "  metaflow-service pod running"

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=metaflow-ui-static --timeout=120s 2>/dev/null || true
echo "  All pods ready"

# Kill any existing port-forwards on these ports
pkill -f "kubectl.*port-forward.*3000:3000" 2>/dev/null || true
pkill -f "kubectl.*port-forward.*8083:8083" 2>/dev/null || true
sleep 1

# Expose metaflow-service via NodePort (no port-forward needed)
echo "Patching metaflow-service to NodePort (30180/30182)..."
kubectl patch svc metaflow-service -p \
  '{"spec": {"type": "NodePort", "ports": [{"name": "metadata", "port": 8080, "targetPort": 8080, "nodePort": 30180}, {"name": "upgrades", "port": 8082, "targetPort": 8082, "nodePort": 30182}]}}' \
  2>/dev/null || true
echo "  Metaflow Service:   http://localhost:30180 (NodePort)"

echo ""
echo "Starting UI port-forwards on 0.0.0.0 for browser access..."
echo "  Metaflow UI:        http://0.0.0.0:3000"
echo "  Metaflow UI API:    http://0.0.0.0:8083"
echo ""

# Run UI port-forwards in parallel, restarting on failure
while true; do
  kubectl port-forward --address 0.0.0.0 svc/metaflow-ui-static 3000:3000 &
  PF1=$!
  kubectl port-forward --address 0.0.0.0 svc/metaflow-ui 8083:8083 &
  PF2=$!

  # Wait for any to exit
  wait -n $PF1 $PF2 2>/dev/null || true
  echo "UI port-forward exited, restarting in 5s..."
  kill $PF1 $PF2 2>/dev/null || true
  sleep 5
done
