# Warehouse Kudu flush, 2026-09-28

`#EN.00000031.FDWINGEST` every two seconds was the ingest loop retrying a
write the tablet could not accept. Two stacked causes:

1. Impala's Kudu client TGT in `/tmp/krb5cc_impala` was past its renew window.
   Status queries shared that Impala and started missing their deadline.
2. After the ticket was renewed, `signal_tier0` still had no range for
   2026-09-28 (`497376 <= VALUES < 497400`). Inserts for the current hour
   failed in `KuduSession::Flush`, and the FDW reported only
   `GetPendingErrors()` — the row error (no covering range) was dropped.
   A row in the previous day's range succeeded.

The ingest loop treated a failed `ADD RANGE PARTITION` as done for the hour,
so it did not try again until the next hour. It now leaves the hour latch
unset until SHOW says the range is present, and it waits 60s on a Kerberos
failure and 15s on a flush failure instead of 2s.

The running engine was not recycled; it is still the process that recovered
once the range existed. The backoff is in the tree for the next start.
