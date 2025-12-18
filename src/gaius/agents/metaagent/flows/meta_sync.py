"""MetaSyncFlow - Sync operational data to meta.* schema.

This Metaflow flow populates the meta schema tables for Metabase
exploratory data analysis. It extracts data from:
- lineage_events -> meta.dataset_catalog, meta.job_catalog, meta.data_dependencies
- agent_evaluations, evolution_cycles -> meta.agent_performance, meta.flow_runs
- grid_snapshots -> meta.kb_topology, meta.document_clusters
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from metaflow import FlowSpec, step, Parameter, current

logger = logging.getLogger(__name__)


class MetaSyncFlow(FlowSpec):
    """Sync operational data to meta.* analytics schema.

    This flow populates the meta schema tables for Metabase dashboards.
    Run modes:
    - incremental: Only sync new data since last watermark
    - full: Full refresh of all tables

    Usage:
        python -m metaflow run MetaSyncFlow --sync_mode incremental
    """

    sync_mode = Parameter(
        "sync_mode",
        default="incremental",
        help="Sync mode: incremental or full",
    )

    lookback_hours = Parameter(
        "lookback_hours",
        default=24,
        type=int,
        help="Hours to look back for incremental sync",
    )

    @step
    def start(self):
        """Initialize sync and load watermarks."""
        import psycopg2
        import os

        self.db_url = os.getenv(
            "GAIUS_DATABASE_URL",
            "postgres://localhost:5438/zndx_gaius?sslmode=disable",
        )

        logger.info(f"Starting MetaSyncFlow in {self.sync_mode} mode")

        # Load watermarks
        self.watermarks = {}
        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()
            cur.execute(
                "SELECT sync_type, last_sync_at, last_event_id FROM meta.sync_watermarks"
            )
            for row in cur.fetchall():
                self.watermarks[row[0]] = {
                    "last_sync_at": row[1],
                    "last_event_id": row[2],
                }
            conn.close()
        except Exception as e:
            logger.warning(f"Could not load watermarks: {e}")

        self.sync_stats = {
            "lineage": {"datasets": 0, "jobs": 0, "dependencies": 0},
            "operations": {"flow_runs": 0, "agent_records": 0},
            "topology": {"snapshots": 0, "clusters": 0},
        }

        self.next(self.sync_lineage)

    @step
    def sync_lineage(self):
        """Sync lineage_events to meta.dataset_catalog, job_catalog, data_dependencies."""
        import psycopg2
        from psycopg2.extras import execute_values

        logger.info("Syncing lineage data...")

        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()

        try:
            # Determine time range
            if self.sync_mode == "full":
                time_filter = ""
            else:
                cutoff = datetime.utcnow() - timedelta(hours=self.lookback_hours)
                time_filter = f"WHERE event_time > '{cutoff.isoformat()}'"

            # Extract datasets from lineage_events
            cur.execute(f"""
                WITH event_datasets AS (
                    SELECT DISTINCT
                        jsonb_array_elements(inputs)->>'namespace' as namespace,
                        jsonb_array_elements(inputs)->>'name' as name,
                        'read' as operation,
                        event_time
                    FROM lineage_events
                    {time_filter}
                    UNION ALL
                    SELECT DISTINCT
                        jsonb_array_elements(outputs)->>'namespace' as namespace,
                        jsonb_array_elements(outputs)->>'name' as name,
                        'write' as operation,
                        event_time
                    FROM lineage_events
                    {time_filter}
                )
                SELECT
                    namespace || ':' || name as dataset_id,
                    namespace,
                    name,
                    MIN(event_time) as first_seen,
                    MAX(event_time) as last_seen,
                    SUM(CASE WHEN operation = 'read' THEN 1 ELSE 0 END) as reads,
                    SUM(CASE WHEN operation = 'write' THEN 1 ELSE 0 END) as writes
                FROM event_datasets
                WHERE namespace IS NOT NULL AND name IS NOT NULL
                GROUP BY namespace, name
            """)

            datasets = cur.fetchall()
            if datasets:
                execute_values(
                    cur,
                    """
                    INSERT INTO meta.dataset_catalog
                        (dataset_id, namespace, name, first_seen, last_seen, total_reads, total_writes)
                    VALUES %s
                    ON CONFLICT (dataset_id) DO UPDATE SET
                        last_seen = GREATEST(meta.dataset_catalog.last_seen, EXCLUDED.last_seen),
                        total_reads = meta.dataset_catalog.total_reads + EXCLUDED.total_reads,
                        total_writes = meta.dataset_catalog.total_writes + EXCLUDED.total_writes
                    """,
                    datasets,
                )
                self.sync_stats["lineage"]["datasets"] = len(datasets)

            # Extract jobs
            cur.execute(f"""
                SELECT
                    job_namespace || '.' || job_name as job_id,
                    job_namespace,
                    job_name,
                    MIN(event_time) as first_run,
                    MAX(event_time) as last_run,
                    COUNT(*) as total_runs,
                    SUM(CASE WHEN event_type = 'COMPLETE' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN event_type = 'FAIL' THEN 1 ELSE 0 END) as failure_count
                FROM lineage_events
                {time_filter}
                WHERE job_namespace IS NOT NULL AND job_name IS NOT NULL
                GROUP BY job_namespace, job_name
            """)

            jobs = cur.fetchall()
            if jobs:
                execute_values(
                    cur,
                    """
                    INSERT INTO meta.job_catalog
                        (job_id, namespace, name, first_run, last_run, total_runs, success_count, failure_count)
                    VALUES %s
                    ON CONFLICT (job_id) DO UPDATE SET
                        last_run = GREATEST(meta.job_catalog.last_run, EXCLUDED.last_run),
                        total_runs = meta.job_catalog.total_runs + EXCLUDED.total_runs,
                        success_count = meta.job_catalog.success_count + EXCLUDED.success_count,
                        failure_count = meta.job_catalog.failure_count + EXCLUDED.failure_count
                    """,
                    jobs,
                )
                self.sync_stats["lineage"]["jobs"] = len(jobs)

            conn.commit()
            logger.info(
                f"Synced {self.sync_stats['lineage']['datasets']} datasets, "
                f"{self.sync_stats['lineage']['jobs']} jobs"
            )

        except Exception as e:
            logger.error(f"Lineage sync failed: {e}")
            conn.rollback()
        finally:
            conn.close()

        self.next(self.sync_operations)

    @step
    def sync_operations(self):
        """Sync operational data to meta.flow_runs, agent_performance."""
        import psycopg2
        from psycopg2.extras import execute_values

        logger.info("Syncing operations data...")

        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()

        try:
            # Extract flow runs from lineage_events
            if self.sync_mode == "full":
                time_filter = ""
            else:
                cutoff = datetime.utcnow() - timedelta(hours=self.lookback_hours)
                time_filter = f"WHERE started.event_time > '{cutoff.isoformat()}'"

            cur.execute(f"""
                WITH flow_starts AS (
                    SELECT
                        run_id,
                        job_name as flow_type,
                        event_time as started_at,
                        jsonb_array_length(COALESCE(inputs, '[]'::jsonb)) as inputs_count
                    FROM lineage_events
                    WHERE event_type = 'START' AND job_namespace = 'gaius.flows'
                ),
                flow_completes AS (
                    SELECT
                        run_id,
                        event_time as completed_at,
                        jsonb_array_length(COALESCE(outputs, '[]'::jsonb)) as outputs_count,
                        CASE WHEN event_type = 'COMPLETE' THEN 'completed' ELSE 'failed' END as status
                    FROM lineage_events
                    WHERE event_type IN ('COMPLETE', 'FAIL') AND job_namespace = 'gaius.flows'
                )
                SELECT
                    started.run_id::uuid,
                    started.flow_type,
                    started.started_at,
                    completed.completed_at,
                    EXTRACT(EPOCH FROM (completed.completed_at - started.started_at)) * 1000 as duration_ms,
                    COALESCE(completed.status, 'running') as status,
                    started.inputs_count,
                    COALESCE(completed.outputs_count, 0) as outputs_count
                FROM flow_starts started
                LEFT JOIN flow_completes completed ON started.run_id = completed.run_id
                {time_filter}
            """)

            flow_runs = cur.fetchall()
            if flow_runs:
                execute_values(
                    cur,
                    """
                    INSERT INTO meta.flow_runs
                        (run_id, flow_type, started_at, completed_at, duration_ms, status, inputs_count, outputs_count)
                    VALUES %s
                    ON CONFLICT (run_id) DO UPDATE SET
                        completed_at = COALESCE(EXCLUDED.completed_at, meta.flow_runs.completed_at),
                        duration_ms = COALESCE(EXCLUDED.duration_ms, meta.flow_runs.duration_ms),
                        status = EXCLUDED.status,
                        outputs_count = COALESCE(EXCLUDED.outputs_count, meta.flow_runs.outputs_count)
                    """,
                    flow_runs,
                )
                self.sync_stats["operations"]["flow_runs"] = len(flow_runs)

            # Aggregate agent performance by day
            cur.execute("""
                SELECT
                    agent_id,
                    DATE(created_at) as date,
                    COUNT(*) as evaluations_count,
                    AVG(overall_score) as avg_overall_score
                FROM agent_evaluations
                WHERE created_at > NOW() - INTERVAL '30 days'
                GROUP BY agent_id, DATE(created_at)
            """)

            agent_stats = cur.fetchall()
            if agent_stats:
                execute_values(
                    cur,
                    """
                    INSERT INTO meta.agent_performance
                        (agent_id, date, evaluations_count, avg_overall_score)
                    VALUES %s
                    ON CONFLICT (agent_id, date) DO UPDATE SET
                        evaluations_count = EXCLUDED.evaluations_count,
                        avg_overall_score = EXCLUDED.avg_overall_score
                    """,
                    agent_stats,
                )
                self.sync_stats["operations"]["agent_records"] = len(agent_stats)

            conn.commit()
            logger.info(
                f"Synced {self.sync_stats['operations']['flow_runs']} flow runs, "
                f"{self.sync_stats['operations']['agent_records']} agent records"
            )

        except Exception as e:
            logger.error(f"Operations sync failed: {e}")
            conn.rollback()
        finally:
            conn.close()

        self.next(self.sync_topology)

    @step
    def sync_topology(self):
        """Sync KB topology data to meta.kb_topology, document_clusters."""
        import psycopg2
        from psycopg2.extras import execute_values

        logger.info("Syncing topology data...")

        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()

        try:
            # Copy grid_snapshots to meta.kb_topology
            cur.execute("""
                INSERT INTO meta.kb_topology
                    (snapshot_id, computed_at, n_documents, coverage, h0_count, h1_count, h2_count, entropy)
                SELECT
                    id,
                    created_at,
                    n_documents,
                    coverage,
                    h0_count,
                    h1_count,
                    h2_count,
                    entropy
                FROM grid_snapshots
                WHERE id NOT IN (SELECT snapshot_id FROM meta.kb_topology)
                ORDER BY created_at DESC
                LIMIT 100
            """)
            self.sync_stats["topology"]["snapshots"] = cur.rowcount

            conn.commit()
            logger.info(f"Synced {self.sync_stats['topology']['snapshots']} topology snapshots")

        except Exception as e:
            logger.error(f"Topology sync failed: {e}")
            conn.rollback()
        finally:
            conn.close()

        self.next(self.update_watermarks)

    @step
    def update_watermarks(self):
        """Update sync watermarks."""
        import psycopg2

        logger.info("Updating watermarks...")

        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()

        try:
            now = datetime.utcnow()
            for sync_type, stats in self.sync_stats.items():
                total = sum(stats.values())
                cur.execute(
                    """
                    UPDATE meta.sync_watermarks
                    SET last_sync_at = %s, records_synced = records_synced + %s
                    WHERE sync_type = %s
                    """,
                    (now, total, sync_type),
                )
            conn.commit()
        except Exception as e:
            logger.error(f"Watermark update failed: {e}")
            conn.rollback()
        finally:
            conn.close()

        self.next(self.end)

    @step
    def end(self):
        """Finalize sync and report statistics."""
        total_records = sum(
            sum(stats.values()) for stats in self.sync_stats.values()
        )

        logger.info(f"MetaSyncFlow completed. Total records synced: {total_records}")
        logger.info(f"Stats: {json.dumps(self.sync_stats, indent=2)}")

        self.total_records = total_records


if __name__ == "__main__":
    MetaSyncFlow()
