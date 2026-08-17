# signals.target recycle + ProspectsUpdateFlow e2e

## Recycle

`sudo systemctl restart signals.target` at 01:35:58, active again 01:39:23.
All `PartOf` units active. Gaius listener `2993112` in `system.slice/gaius.service`.
thinking first failed (`torch_from_blob` on early retries), then
`PROCESS_STATUS_HEALTHY` at 01:43:06 (Qwen3.8-27B TP=4, `:8081`).

`just kinit` from this Gaius session hits `DEVENV_ROOT` — use
`signals_krb_kinit /home/rch/local/src/wxs/signals`.

## Flow

`/prospects update` via CLI is not the run path: the servicer used to
always emit `COMPLETED` after the iterator. Fixed: no extra COMPLETED
after `FAILED`. Scheduler-style CLI is the real execute:

```
GAIUS_METAFLOW_MODE=platform SIGNALS_ROOT=~/local/src/wxs/signals \
  uv run python -m gaius.flows.prospects.update_flow run \
  --symbols CHTR --filings_per_symbol 1 --force True
```

| Run | Metaflow | RustFS snapshot | History JSONL | Filings/thinking |
|-----|----------|-----------------|---------------|------------------|
| 26 | `ProspectsUpdateFlow/26` | `s3://metaflow/metaflow/ProspectsUpdateFlow/26/` (83 objects) | recorded | HX `zndx-gaius` ACCESS_DENIED |
| 27 | `ProspectsUpdateFlow/27` | same prefix `/27/` | recorded at `end` | HX still `zndx-gaius` (env override did not reach step config) |

YK: bound live `article-curate-1786767299` on
`root.internal.inference.extract` (envelope: one GPU app).

Product object: `s3://signals-dataproducts/gaius/prospects/26/run.json`
(bucket created this session).

## Surfaces

- Applications: extract claim Running.
- Queues: JS lineup over the same YK leaves.
- History `/history`: inventory `gaius.prospects.corpus` + update rows.
  UI reads JSONL (`SIGNALS_DATA_PRODUCT_HISTORY`). Impala
  `signals_dataproducts` is not applied (`CREATE TABLE` fails Kudu
  Kerberos from Impala). `review-product` still errors; JSONL is what
  the page shows.

## Gaps (not this recycle)

- HX still defaults to bucket `zndx-gaius` + `minioadmin`. That bucket
  is not on RustFS. EDGAR sync `#EDGAR.00000005.SYNCFAIL` — no compact.
- Impala warehouse schema + Impala→Kudu GSSAPI.
- CLI `ProspectsUpdate` Runner path still needs a recycle to pick up
  the false-COMPLETED fix.
