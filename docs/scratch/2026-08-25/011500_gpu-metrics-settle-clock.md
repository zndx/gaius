# gpu_metrics settle is a clock, not a soak tick

Iceberg analog without Kudu `DROP RANGE` double-counts UNION. The soak
loop analoged hours and sometimes missed the drop because **no scheduler
owned the workflow**.

Clocks now:

1. **pg_cron on Signals :5455** — `public.gpu_metrics_settle()` at `:05`
   every hour. Iceberg verify, then `DROP RANGE VALUE = <closed hour>`.
   Fail-closed if analog is missing. Live hour stays on Kudu.
2. **pg_cron on Gaius :5444** — inserts `scheduled_tasks.gpu_metrics_settle`;
   engine STP spawns the same walk (`SIGNALS_ROOT`).
3. **Airflow DAG `gpu_metrics_settle`** — Metaflow work, analog if Iceberg
   is empty, then verify + drop.

Guru `#SL.00000026.SETTLE`.
