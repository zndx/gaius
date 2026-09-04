#!/usr/bin/env bash
# scripts/processes/nautilus.sh — the resident Nautilus supervisor (Rust, external/nautilus)
# Launched by devenv process-compose; see devenv.nix processes.nautilus
#
# Nautilus DIALS the engine's EngineSupervision stream on :50051 and hosts
# service Nautilus on loopback :50061. It deliberately does NOT wait for the
# engine: an observer that blocks on its subject cannot record its absence —
# a dark engine is `unknown` slots in the Backlog, not a startup failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

check_disabled DISABLE_NAUTILUS "Nautilus"

REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO"

export NAUTILUS_INSTANCE="${NAUTILUS_INSTANCE:-$REPO/config/supervision/gaius.textproto}"
export NAUTILUS_ENGINE="${NAUTILUS_ENGINE:-127.0.0.1:50051}"
export NAUTILUS_BIND="${NAUTILUS_BIND:-127.0.0.1:50061}"
# observe | reclaim | reclaim,consult — promotion is a deliberate act (Stage 4).
export NAUTILUS_DIRECTIVES="${NAUTILUS_DIRECTIVES:-observe}"
# The Postgres TRANSPORT to Kudu (impala_fdw foreign tables); derived from PGPORT.
export NAUTILUS_PG_DSN="${NAUTILUS_PG_DSN:-${DATABASE_URL:-postgresql://gaius:gaius@127.0.0.1:${PGPORT:-5444}/zndx_gaius}}"
# Write-ahead journal: nisshi on RustFS (S3). One bucket for every project's
# Nautilus; the key layout is namespaced by cluster_id = project.
export NAUTILUS_RUSTFS_URL="${NAUTILUS_RUSTFS_URL:-s3://signals-nautilus/}"
export NAUTILUS_RUSTFS_ENDPOINT="${NAUTILUS_RUSTFS_ENDPOINT:-http://127.0.0.1:9010}"
# RustFS is Signals' object store (rustfsadmin) — NOT gaius's MinIO, whose
# minioadmin rides this shell's AWS_ACCESS_KEY_ID. Never inherit AWS_* here.
export SIGNALS_RUSTFS_KEY="${SIGNALS_RUSTFS_KEY:-rustfsadmin}"
export SIGNALS_RUSTFS_SECRET="${SIGNALS_RUSTFS_SECRET:-rustfsadmin}"
export RUST_LOG="${RUST_LOG:-info}"

banner "NAUTILUS - resident supervisor on $NAUTILUS_BIND (engine $NAUTILUS_ENGINE, directives $NAUTILUS_DIRECTIVES)"

PORT="${NAUTILUS_BIND##*:}"
assert_tcp_port_free "$PORT" "nautilus"

wait_for_postgres "${PGUSER:-$USER}"

CRATE="$REPO/external/nautilus"
BIN="$CRATE/target/release/nautilus"
if [[ ! -f "$CRATE/Cargo.toml" ]]; then
  echo "external/nautilus submodule is not checked out."
  echo "  Guru: #NT.00000001.NOINSTANCE"
  echo "  Try: git submodule update --init external/nautilus"
  exit 1
fi
# Rebuild when the binary is missing or older than the crate sources / the protocol.
if [[ ! -x "$BIN" ]] || [[ -n "$(find "$CRATE/src" "$CRATE/Cargo.toml" "$CRATE/build.rs" "$REPO/external/signals-protocol/proto/zndx/supervision/v1" -newer "$BIN" -print -quit 2>/dev/null)" ]]; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "nautilus binary missing/stale and cargo not on PATH."
    echo "  Try: just nautilus-build"
    exit 1
  fi
  echo "Building nautilus (release)…"
  cargo build --release --manifest-path "$CRATE/Cargo.toml"
fi

# The instance must validate before we supervise against it (rejected whole).
"$BIN" validate "$NAUTILUS_INSTANCE" --quiet | tail -1

echo "Starting nautilus"
echo "  instance=$NAUTILUS_INSTANCE"
echo "  journal=$NAUTILUS_RUSTFS_URL via $NAUTILUS_RUSTFS_ENDPOINT"
exec "$BIN" serve --instance "$NAUTILUS_INSTANCE"
