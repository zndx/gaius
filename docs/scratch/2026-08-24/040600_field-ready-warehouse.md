# Field-ready warehouse: engine write/read, no wrappers

Pattern after `sudo systemctl restart signals.target`:

1. `signals.service` `just down` reaps wrapper Impala (`:21050` etc.) and the C++ sidecar ingest.
2. `just up` starts devenv Impala (FQDN Kudu, JAAS, `kudu.krb5ccname`, Impala keytab kinit) + Kudu + Postgres.
3. `signals-ready` requires Impala HS2 **and** `SELECT gpu_metrics` via `impala_fdw`.
4. `gaius.service` starts the engine; `warehouse_ingest` INSERT through FDW; HardwareDriver samples nvidia-smi (same source, no :9400 shim).
5. `signals-refresh` checks Engine/Status, UI :9890, and gpu_metrics freshness (<45s).

No `/tmp/start-impala-hs2.sh`. No sidecar `gpu_metrics_kudu_ingest.py` as the product writer.
