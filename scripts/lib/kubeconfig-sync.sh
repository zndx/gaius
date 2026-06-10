#!/usr/bin/env bash
# Sync RKE2 kubeconfig to user-readable location.
# Called by systemd drop-in after rke2-server starts, and by just recipe.
#
# Source:      /etc/rancher/rke2/rke2.yaml  (root:root 0600)
# Destination: /home/rch/.config/kube/rke2.yaml (rch:rch 0600)
#
# This ensures kubectl works for the gaius user without sudo,
# and survives K8s restarts/cert rotations automatically.

set -euo pipefail

SRC="/etc/rancher/rke2/rke2.yaml"
DEST_DIR="/home/rch/.config/kube"
DEST="$DEST_DIR/rke2.yaml"
OWNER="rch:rch"

if [ ! -f "$SRC" ]; then
    echo "ERROR: RKE2 kubeconfig not found at $SRC"
    exit 1
fi

mkdir -p "$DEST_DIR"
cp "$SRC" "$DEST"
chown "$OWNER" "$DEST"
chmod 600 "$DEST"

echo "Synced $SRC -> $DEST"
