# HS2 GSSAPI Thrift-over-SASL: FDW UNION reads

Postgres `impala_fdw` now speaks Impala HS2 over Kerberos GSSAPI. Iceberg
`gpu_metrics_tier1` and the Impala UNION view `gpu_metrics` are selectable
from devenv PG `:5455`. Closed Kudu hour ranges were **not** dropped.

## What was broken

OpenSession SIGSEGV'd after a successful SASL handshake and a 117-byte framed
flush. Two independent bugs:

1. **Thrift vtable mismatch.** Generated `TCLIService` stubs are 0.22 (they
   added `writeUUID_virt` before the read slots). A test binary linked
   `libthrift-0.16.0` built `TBinaryProtocol` without that slot, so
   `readMessageBegin` jumped one vtable entry and never entered the
   transport `read()`. Write slots sit before `writeUUID`, which is why
   flush succeeded. Guru: `#SL.00000028.HS2GSSAPI`.
2. **Unread SASL COMPLETE.** Cyrus returns `SASL_OK` before Impala
   `TSaslTransport` writes the final `05 00 00 00 00` frame. TFramedTransport
   then treated `0x05000000` as a length (`Received an oversized frame`).

## What works now (2026-08-24 05:57 UTC)

| Path | Access | Result |
|------|--------|--------|
| Standalone `/tmp/hs2_gssapi_test` | GSSAPI HS2 | `gpu_metrics_tier1` COUNT=75648 |
| FDW `gpu_metrics_tier1` | `impala_sql` | COUNT=75648 |
| FDW `gpu_metrics` | `impala_sql` UNION | COUNT=kudu+iceberg (double-count on closed hours) |
| FDW `gpu_metrics_tier0` | `kudu_scan` | INSERT + COUNT still green |

`EXPLAIN` on `gpu_metrics` shows `Impala AccessMethod: impala_sql` and remote
SQL against `signals_dataproducts.gpu_metrics`.

## Write vs read

- **Read hierarchy:** `gpu_metrics` → HS2 UNION (Kudu ∪ Iceberg).
- **Writes:** `INSERT INTO gpu_metrics_tier0` (`kudu_scan` / G11). The UNION
  view is not writable (SPEC N3). Engine ingest was pointed at tier0.

## Do not DROP yet

Hours 496537–496540 still live in both stores, so UNION ALL double-counts
them. Drop those Kudu ranges only after this FDW SELECT stays green on a
chosen hour.

## Build note

`impala_fdw.so` and the GSSAPI test must use **Thrift 0.22** headers and
`libthrift.so.0.22.0` (`pkgs.thrift` in signals devenv). Replace the `.so`
with `install`/`mv` (new inode); `cp -f` onto a mapped extension SIGSEGVs
idle backends.
