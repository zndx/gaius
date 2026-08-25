"""gpu_metrics_settle is a scheduled honesty clock, not a soak tick."""

from pathlib import Path


def test_migration_schedules_pg_cron() -> None:
    text = (
        Path(__file__).resolve().parents[2]
        / "db"
        / "migrations"
        / "20260825000001_gpu_metrics_settle_clock.sql"
    ).read_text(encoding="utf-8")
    assert "gpu_metrics_settle" in text
    assert "cron.schedule" in text
    assert "5 * * * *" in text


def test_stp_registers_gpu_metrics_settle() -> None:
    from gaius.engine.services.scheduled_task_processor import (
        SINGLETON_TASK_TYPES,
    )

    assert "gpu_metrics_settle" in SINGLETON_TASK_TYPES
    src = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "gaius"
        / "engine"
        / "services"
        / "scheduled_task_processor.py"
    ).read_text(encoding="utf-8")
    assert 'register_handler("gpu_metrics_settle"' in src


def test_settle_kind_is_compute() -> None:
    from gaius.engine.sentinel_claim import COMPUTE, resource_class_for

    assert resource_class_for("gpu-metrics-settle") is COMPUTE
