#!/usr/bin/env bash
# Register Signals-built impala_fdw on Gaius zndx_gaius (:5444).
# Impala/Kudu/RustFS stay system (or Signals) services. This Postgres is a client.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIGNALS_ROOT="${SIGNALS_ROOT:-$HOME/local/src/wxs/signals}"
SO="${IMPALA_FDW_SO:-$SIGNALS_ROOT/.devenv/pg-ext/lib/impala_fdw.so}"
if [[ ! -f "$SO" ]]; then
  SO="$SIGNALS_ROOT/components/impala_fdw/impala_fdw.so"
fi
if [[ ! -f "$SO" ]]; then
  echo "impala_fdw.so not found. Set IMPALA_FDW_SO or SIGNALS_ROOT (built Signals FDW)."
  echo "  Guru: #EN.00000031.FDWINGEST"
  exit 1
fi
EXT_DIR="${GAIUS_PG_EXT_DIR:-$ROOT/.devenv/pg-ext}"
mkdir -p "$EXT_DIR/lib"
# Never cp -f over a mapped .so (postgres SIGBUS). Install via tmp+mv.
tmp="$EXT_DIR/lib/impala_fdw.so.new"
cp -f "$SO" "$tmp"
mv -f "$tmp" "$EXT_DIR/lib/impala_fdw.so"
FDW_SO="$EXT_DIR/lib/impala_fdw.so"

KEYTAB="${IMPALA_FDW_KEYTAB:-$SIGNALS_ROOT/.devenv/kdc/signals.keytab}"
if [[ ! -f "$KEYTAB" ]]; then
  echo "Kerberos keytab missing: $KEYTAB"
  echo "  Guru: #SL.00000028.HS2GSSAPI"
  exit 1
fi
HS2_HOST="${IMPALA_HS2_HOST:-tinybox.dev.vista.zndx.org}"
KUDU_MASTERS="${KUDU_MASTERS:-tinybox.dev.vista.zndx.org:7051}"
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5444}"
PGDATABASE="${PGDATABASE:-zndx_gaius}"

SQL="$ROOT/scripts/warehouse/gpu-metrics-fdw.sql"
sed \
  -e "s|__FDW_SO__|$FDW_SO|g" \
  -e "s|__KEYTAB__|$KEYTAB|g" \
  -e "s|__HS2_HOST__|$HS2_HOST|g" \
  -e "s|__KUDU_MASTERS__|$KUDU_MASTERS|g" \
  "$SQL" | psql -h "$PGHOST" -p "$PGPORT" -d "$PGDATABASE" -v ON_ERROR_STOP=1

# Warehouse-side settle function, invoked by Gaius pg_cron → engine, not Signals cron.
if [[ -f "$SIGNALS_ROOT/config/platform/gpu-metrics-settle.sql" ]]; then
  grep -v 'cron.schedule\|cron.unschedule' \
    "$SIGNALS_ROOT/config/platform/gpu-metrics-settle.sql" \
    | psql -h "$PGHOST" -p "$PGPORT" -d "$PGDATABASE" -v ON_ERROR_STOP=1
fi

psql -h "$PGHOST" -p "$PGPORT" -d "$PGDATABASE" -v ON_ERROR_STOP=1 \
  -c "GRANT EXECUTE ON FUNCTION public.gpu_metrics_settle() TO gaius;" 2>/dev/null || true
echo "impala_fdw on $PGDATABASE:$PGPORT → HS2 $HS2_HOST:21050 (Signals FDW left in place)"
echo "Smoke: psql -h $PGHOST -p $PGPORT -d $PGDATABASE -c 'SELECT count(*) FROM gpu_metrics_tier0'"
echo "Gaius postgres must have KRB5_CONFIG=$SIGNALS_ROOT/.devenv/kdc/krb5.conf (devenv.nix)."
