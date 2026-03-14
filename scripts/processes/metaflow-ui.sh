#!/usr/bin/env bash
# scripts/processes/metaflow-ui.sh — Metaflow UI (Interactive Tilt Dashboard)
# Launched by devenv process-compose; see devenv.nix processes.metaflow-ui
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

banner "METAFLOW UI - Interactive Tilt Dashboard"

# Always set from $HOME — env.KUBECONFIG can't be set in Nix daemon mode
export KUBECONFIG="$HOME/.config/kube/rke2.yaml"

echo "Starting Tilt for interactive Metaflow management..."
echo "  Tilt Dashboard:   http://localhost:10350"
echo "  Metaflow UI:      http://localhost:3000"
echo ""
cd infra/tilt
exec tilt up --stream
