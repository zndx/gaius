# Unattended `gaius.prospects.corpus`

How the product stays current without a human or ACP agent.

## Clock

1. `pg_cron` `0 7 * * *` `prospects-daily-check` → `scheduled_tasks`.
2. `ScheduledTaskProcessor` LISTEN/NOTIFY runs `prospects_check`
   (YK `root.external.rate-metered`, ephemeral).
3. New filings → `prospects_update` (binds extract, Metaflow on
   Signals RustFS, `end` publishes History).
4. No new filings → `record_availability` (`kind=maintained`) so
   History shows the last snapshot is still the product.
5. No snapshot at all → enqueue a watchlist update (first pin).
6. Engine start catch-up re-arms step 2 if the 24h cooldown is due.

ACP Overwatch may still write `hx_reasoning` later. It is **not**
required for availability.

## Object plane

`metaflow_child_env(platform)` stamps HX onto
`s3://signals-dataproducts/gaius/hx/` with the same RustFS keys as
Metaflow. Filesystem fallback is refused on platform
(`#HX.00000001.NORUSTFS`).

## Yield / envelope

Update binds the standing extract Application and does **not** delete
it on completion. Only a minted `prospects-update-*` claim is torn
down.

## Not Airflow-as-SoR (yet)

`airflow create` wants `@kubernetes` on every step. Until that task
image exists, the peer clock is pg_cron under `gaius.service`.
Signals Airflow stays the platform clock for warehouse tier-upkeep.
