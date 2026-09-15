import pytest

from gaius.engine.services.theta_cycle import consume_pending


class _Conn:
    def __init__(self) -> None:
        self.pending: list[dict] = [
            {"job_id": 1, "slice_id": "2026-W26"},
            {"job_id": 2, "slice_id": "2026-W27"},
        ]
        self.started: list[int] = []
        self.completed: list[tuple] = []
        self.scheduled = False
        self._pending_reads = 0

    async def fetch(self, sql: str, *args: object) -> list[dict]:
        if "get_pending_theta_consolidations" in sql:
            self._pending_reads += 1
            if self._pending_reads == 1:
                return list(self.pending)
            return []
        return []

    async def fetchval(self, sql: str, *args: object):
        if "schedule_theta_consolidation" in sql:
            self.scheduled = True
            return None
        if "start_theta_consolidation" in sql:
            self.started.append(int(args[0]))
            return True
        if "complete_theta_consolidation" in sql:
            self.completed.append(args)
            return True
        return None


@pytest.mark.asyncio
async def test_consume_pending_starts_and_completes_each_job() -> None:
    conn = _Conn()

    async def consolidator(slice_id: str) -> dict:
        return {
            "success": True,
            "signal": {"urgency": 0.4, "drift": 0.1},
            "candidates_evaluated": 3,
            "candidates_selected": 1,
            "documents_augmented": 1,
        }

    out = await consume_pending(conn, consolidator=consolidator)
    assert [j["slice_id"] for j in out] == ["2026-W26", "2026-W27"]
    assert conn.started == [1, 2]
    assert all(j["success"] for j in out)
    assert conn.completed[0][3] == 3


@pytest.mark.asyncio
async def test_consume_pending_records_failure() -> None:
    conn = _Conn()
    conn.pending = [{"job_id": 9, "slice_id": "2026-W38"}]

    async def consolidator(slice_id: str) -> dict:
        return {"success": False, "error": "no centroid"}

    out = await consume_pending(conn, consolidator=consolidator, schedule_if_empty=False)
    assert out[0]["success"] is False
    assert conn.completed[0][6] == "no centroid"


def test_catalog_theta_cycle_is_monday_airflow_metaflow() -> None:
    from gaius.engine.services import workload_catalog as wc

    e = wc.entry_for("theta_cycle")
    assert e.enabled and e.runner == wc.RUNNER_METAFLOW
    assert e.source == "airflow"
    assert wc.airflow_dag_id(e) == "gaius_theta_cycle"
    assert e.cron == "0 6 * * 1"
    assert e.pg_cron_job == "theta-weekly-consolidation"
    assert not e.pg_cron_active


def test_flow_is_consolidation_not_janitor() -> None:
    from gaius.flows import FLOW_REGISTRY
    from gaius.flows.theta.cycle import ThetaCycleFlow

    assert "theta-cycle" in FLOW_REGISTRY
    assert not hasattr(ThetaCycleFlow, "maintain")
    assert not hasattr(ThetaCycleFlow, "settle")
    assert hasattr(ThetaCycleFlow, "consolidate")
