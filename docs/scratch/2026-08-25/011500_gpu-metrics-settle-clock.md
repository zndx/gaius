# gpu_metrics settle is a clock, not a soak tick

Iceberg analog without Kudu `DROP RANGE` double-counts UNION. The soak
loop analoged hours and sometimes missed the drop because **no scheduler
owned the workflow**.

Clock is **Gaius pg_cron on zndx_gaius :5444** (`gpu-metrics-settle` at
`:05`). It inserts `scheduled_tasks.gpu_metrics_settle`. The engine
runs the walk / `SELECT gpu_metrics_settle()` on the warehouse DSN
(`:5455`). That database holds the foreign tables; it is not the clock.

Airflow DAG `gpu_metrics_settle` is the platform Metaflow clock.

Guru `#SL.00000026.SETTLE`.
