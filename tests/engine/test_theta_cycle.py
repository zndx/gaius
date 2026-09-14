from gaius.engine.services.theta_cycle import (
    GURU,
    plan_closed_hours,
    partition_delete_sql,
    refuse_drop,
)
import pytest


def test_refuse_drop_when_iceberg_short() -> None:
    with pytest.raises(RuntimeError, match="refuse DROP"):
        refuse_drop(10, ice_n=3, kudu_n=10)
    refuse_drop(10, ice_n=10, kudu_n=10)
    refuse_drop(10, ice_n=12, kudu_n=10)


def test_plan_skips_live_hour() -> None:
    plans = plan_closed_hours(
        kudu={100: 4, 101: 2},
        ice={100: 4},
        now_hour=101,
        kudu_table="signals_dataproducts.theta_scratch_vertex_tier0",
    )
    assert [p.hour for p in plans] == [100]
    assert not plans[0].needs_analog
    assert "DROP RANGE PARTITION VALUE = 100" in plans[0].drop_sql


def test_plan_needs_analog_when_ice_missing() -> None:
    plans = plan_closed_hours(
        kudu={50: 2},
        ice={},
        now_hour=51,
        kudu_table="t",
    )
    assert plans[0].needs_analog


def test_partition_expire_is_equality_not_row_predicate() -> None:
    sql = partition_delete_sql(496800)
    assert sql == "epoch_hour = 496800"
    assert "<" not in sql
    assert "DELETE FROM" not in sql


def test_catalog_theta_cycle_is_airflow_metaflow() -> None:
    from gaius.engine.services import workload_catalog as wc

    e = wc.entry_for("theta_cycle")
    assert e is not None
    assert e.enabled and e.runner == wc.RUNNER_METAFLOW
    assert e.source == "airflow"
    assert wc.airflow_dag_id(e) == "gaius_theta_cycle"
    assert not e.pg_cron_active
    assert e.cron == "25 * * * *"


def test_flow_is_registered() -> None:
    from gaius.flows import FLOW_REGISTRY

    assert "theta-cycle" in FLOW_REGISTRY
    assert FLOW_REGISTRY["theta-cycle"].__name__ == "ThetaCycleFlow"
