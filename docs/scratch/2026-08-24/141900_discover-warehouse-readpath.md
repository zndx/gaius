# Discover and waterfall read Kudu ∪ Iceberg

Engine persists DCGM `:9400` (power, util, FB used, temp) through Postgres
`gpu_metrics_tier0`. Discover histograms and the cognition waterfall read
`gpu_metrics` (Postgres view: Kudu hours ∪ Iceberg hours not still in Kudu).
No Prometheus and no in-memory `kumo_minutes` on that read path.

Kudu hour 496549 was analoged then `DROP RANGE PARTITION VALUE = 496549`.
UNION no longer double-counts.
