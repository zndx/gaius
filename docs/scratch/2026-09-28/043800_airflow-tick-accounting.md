# Airflow ticks outlive the scheduled_tasks tail

Sunday `cleanup-scheduled-tasks` keeps the newest 1000 `scheduled_tasks` rows. Per-minute jobs fill that in hours, so a Friday `weekly_signals_summary` success and a Monday Theta success disappear. The hub then reports a miss on Engine/Status even though the Airflow DAG succeeded.

`meta.airflow_workload_ticks` is one row per workload. The coordination pass reads it beside the task table, refreshes it from Airflow's successful DAG runs, and writes it again when a workload completes. The cleanup also keeps the newest successful task row of each class.
