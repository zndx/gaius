import pytest

from gaius.engine.services.theta_cycle import STALE, consume_pending, supersede_stale


class _Conn:
    def __init__(self) -> None:
        self.pending: list[dict] = [
            {"job_id": 1, "slice_id": "2026-W26"},
            {"job_id": 2, "slice_id": "2026-W38"},
        ]
        self.started: list[int] = []
        self.completed: list[tuple] = []
        self.supersede_slice: str | None = None
        self.scheduled: str | None = None

    async def fetch(self, sql: str, *args: object) -> list[dict]:
        if "get_pending_theta_consolidations" in sql:
            return [r for r in self.pending if r["slice_id"] == "2026-W38"]
        return []

    async def fetchval(self, sql: str, *args: object):
        if "WITH u AS" in sql or "slice_id <>" in sql:
            self.supersede_slice = args[0]
            return 12
        if "schedule_theta_consolidation" in sql:
            self.scheduled = args[0] if args else None
            return None
        if "start_theta_consolidation" in sql:
            self.started.append(int(args[0]))
            return True
        if "complete_theta_consolidation" in sql:
            self.completed.append(args)
            return True
        return 0


@pytest.mark.asyncio
async def test_consume_pending_only_current_slice() -> None:
    conn = _Conn()

    async def consolidator(slice_id: str) -> dict:
        assert slice_id == "2026-W38"
        return {
            "success": True,
            "signal": {"urgency": 0.4, "drift": 0.1},
            "candidates_evaluated": 3,
            "candidates_selected": 1,
            "documents_augmented": 1,
        }

    out = await consume_pending(
        conn, consolidator=consolidator, current_slice="2026-W38"
    )
    assert conn.supersede_slice == "2026-W38"
    slices = [j["slice_id"] for j in out if j.get("job_id")]
    assert slices == ["2026-W38"]
    assert conn.started == [2]


@pytest.mark.asyncio
async def test_consume_pending_records_stage_named_failure() -> None:
    conn = _Conn()
    conn.pending = [{"job_id": 9, "slice_id": "2026-W38"}]

    async def consolidator(slice_id: str) -> dict:
        return {
            "success": False,
            "error": "#THETA.00000009.NOTHOUGHTS none",
            "guru_code": "#THETA.00000009.NOTHOUGHTS",
        }

    out = await consume_pending(
        conn, consolidator=consolidator, current_slice="2026-W38"
    )
    job = next(j for j in out if j.get("job_id"))
    assert job["success"] is False
    assert job["error"].startswith("#THETA.00000009")


def test_catalog_theta_cycle_is_monday_airflow_metaflow() -> None:
    from gaius.engine.services import workload_catalog as wc

    e = wc.entry_for("theta_cycle")
    assert e.enabled and e.runner == wc.RUNNER_METAFLOW
    assert e.source == "airflow"
    assert wc.airflow_dag_id(e) == "gaius_theta_cycle"
    assert e.cron == "0 6 * * 1"
    assert not e.pg_cron_active


def test_flow_is_platform_vessel() -> None:
    from gaius.flows import FLOW_REGISTRY
    from gaius.flows.theta.cycle import ThetaCycleFlow

    assert "theta-cycle" in FLOW_REGISTRY
    assert ThetaCycleFlow.gpu_tokens == 1
    assert hasattr(ThetaCycleFlow, "encode")
    assert hasattr(ThetaCycleFlow, "infer")
    assert hasattr(ThetaCycleFlow, "complete")
    assert not hasattr(ThetaCycleFlow, "maintain")
    assert not hasattr(ThetaCycleFlow, "settle")


def test_pairs_from_thoughts_skip_title_first_word() -> None:
    from gaius.agents.theta.agent import _pairs_from_thoughts

    docs = [
        {
            "title": "In Search of Long Data",
            "content": "See [[energy-systems]] and sdg_7 in the note.",
            "domains": ["ENERGY"],
            "kb_paths": ["current/topics/kudu-spill.md"],
        }
    ]
    pairs = _pairs_from_thoughts(docs, limit=20)
    flat = {a for p in pairs for a in p}
    assert "In" not in flat
    assert "Can" not in flat
    assert "ENERGY" in flat
    assert "energy-systems" in flat or "kudu-spill" in flat
    assert any("sdg_7" in (a, b) for a, b in pairs) or "sdg_7" in flat


def test_theta_cycle_objective_is_declared() -> None:
    from gaius.engine.services.objective_service import OBJECTIVES

    spec = OBJECTIVES["theta_cycle"]
    assert spec.verifier == "verify_theta_cycle"
    assert spec.dag == ("theta_cycle",)
    assert spec.params["horizon_hours"] == 5
