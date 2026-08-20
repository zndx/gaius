#!/usr/bin/env bash
# scripts/processes/gaius-ui.sh — Gaius board UI (Axum / Keiretsu)
# Launched by devenv process-compose; see devenv.nix processes.gaius-ui
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

check_disabled DISABLE_GAIUS_UI "Gaius UI"

banner "GAIUS UI - Board on 0.0.0.0:9890"

REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO"

export GAIUS_UI_BIND="${GAIUS_UI_BIND:-0.0.0.0:9890}"
export GAIUS_UI_STATE="${GAIUS_UI_STATE:-$REPO/build/gaius-ui}"
export GAIUS_BOARD_JSON="${GAIUS_BOARD_JSON:-$REPO/build/dev/.board.json}"
export GAIUS_ENGINE_TARGET="${GAIUS_ENGINE_TARGET:-127.0.0.1:50051}"
export GAIUS_THINKING_CAPABILITY="${GAIUS_THINKING_CAPABILITY:-thinking}"
if [[ -x "$HOME/.local/bin/grok" && -z "${GAIUS_GROK_BIN:-}" ]]; then
  export GAIUS_GROK_BIN="$HOME/.local/bin/grok"
fi
if ! command -v bwrap >/dev/null 2>&1 && [[ ! -x "$REPO/.devenv/profile/bin/bwrap" ]]; then
  echo "bubblewrap (bwrap) not found."
  echo "  Guru: #UI.00000002.NOBWRAP"
  echo "  devenv.nix includes pkgs.bubblewrap — re-enter the devenv shell."
  echo "  Or: apt install -y bubblewrap"
  exit 1
fi

PORT="${GAIUS_UI_BIND##*:}"
assert_tcp_port_free "$PORT" "gaius-ui"

wait_for_postgres "${PGUSER:-$USER}"

BIN="$REPO/components/gaius-ui/target/release/gaius-ui"
if [[ ! -x "$BIN" ]]; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "gaius-ui binary missing and cargo not on PATH."
    echo "  Try: cargo build --release -p gaius-ui --manifest-path components/gaius-ui/Cargo.toml"
    exit 1
  fi
  echo "Building gaius-ui (release)…"
  cargo build --release -p gaius-ui --manifest-path "$REPO/components/gaius-ui/Cargo.toml"
fi

echo "Starting gaius-ui on $GAIUS_UI_BIND"
echo "  board=$GAIUS_BOARD_JSON"
exec "$BIN"
