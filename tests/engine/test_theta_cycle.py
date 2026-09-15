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
    assert ThetaCycleFlow.gpu_tokens == 0
    from gaius.engine.sentinel_claim import COMPUTE, resource_class_for

    assert resource_class_for("theta-cycle") is COMPUTE
    assert hasattr(ThetaCycleFlow, "encode")
    assert hasattr(ThetaCycleFlow, "infer")
    assert hasattr(ThetaCycleFlow, "complete")
    assert hasattr(ThetaCycleFlow, "end")
    assert not hasattr(ThetaCycleFlow, "maintain")
    assert not hasattr(ThetaCycleFlow, "settle")
    # GaiusFlow.kb_root is a Path property; assigning it in start() raises.
    from gaius.flows.base import GaiusFlow

    assert "kb_root" not in vars(ThetaCycleFlow)
    assert isinstance(vars(GaiusFlow)["kb_root"], property)


def test_novel_pairs_drop_entailed_and_score_both_directions() -> None:
    from gaius.agents.theta.clt_incidence import GroundedItem, novel_directed_pairs

    a = "https://signals.zndx.org/sdg#A"
    b = "https://signals.zndx.org/sdg#B"
    d = "https://signals.zndx.org/sdg#D"
    entailed = frozenset({(a, b)})
    linked = [
        GroundedItem(1, ((a, 0.9),), 1.0),
        GroundedItem(2, ((b, 0.8), (d, 0.7)), 1.0),
    ]
    pairs = novel_directed_pairs({(0, 1): linked}, entailed, ranked_limit=10)
    assert (a, b) not in pairs
    assert (b, a) not in pairs
    assert (a, d) in pairs and (d, a) in pairs
    # B and D sit on the same item — not a cross-item CLT link.


def test_novel_pairs_rank_by_weight_not_lexicographic_iri() -> None:
    from gaius.agents.theta.clt_incidence import GroundedItem, novel_directed_pairs

    z = "https://signals.zndx.org/sdg#Zzz"
    a = "https://signals.zndx.org/sdg#Aaa"
    items = [
        GroundedItem(1, ((z, 1.0),), 10.0),
        GroundedItem(2, ((a, 1.0),), 10.0),
    ]
    pairs = novel_directed_pairs({(1, 1): items}, frozenset(), ranked_limit=2)
    assert pairs[0] in {(z, a), (a, z)}
    assert set(pairs) == {(z, a), (a, z)}


def test_tbox_closure_marks_ancestors_entailed(tmp_path) -> None:
    from gaius.agents.theta.tbox import tbox_relations

    owl = tmp_path / "t.owl"
    owl.write_text(
        """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/t"/>
  <owl:Class rdf:about="http://example.org/t#C">
    <rdfs:label>C</rdfs:label>
  </owl:Class>
  <owl:Class rdf:about="http://example.org/t#B">
    <rdfs:label>B</rdfs:label>
    <rdfs:subClassOf rdf:resource="http://example.org/t#C"/>
  </owl:Class>
  <owl:Class rdf:about="http://example.org/t#A">
    <rdfs:label>A</rdfs:label>
    <rdfs:subClassOf rdf:resource="http://example.org/t#B"/>
  </owl:Class>
</rdf:RDF>
""",
        encoding="utf-8",
    )
    records, entailed = tbox_relations(str(owl))
    iris = {r.iri for r in records}
    assert iris == {
        "http://example.org/t#A",
        "http://example.org/t#B",
        "http://example.org/t#C",
    }
    assert ("http://example.org/t#A", "http://example.org/t#B") in entailed
    assert ("http://example.org/t#A", "http://example.org/t#C") in entailed
    assert ("http://example.org/t#B", "http://example.org/t#A") not in entailed


def test_certified_tbox_is_sdg_ontology() -> None:
    from gaius.agents.theta.tbox import CERTIFIED_OWL, certified_ontology_path

    assert CERTIFIED_OWL.name == "sdg-ontology.owl"
    if CERTIFIED_OWL.is_file():
        assert certified_ontology_path() == CERTIFIED_OWL


def test_theta_cycle_objective_is_declared() -> None:
    from gaius.engine.services.objective_service import OBJECTIVES

    spec = OBJECTIVES["theta_cycle"]
    assert spec.verifier == "verify_theta_cycle"
    assert spec.dag == ("theta_cycle",)
    assert spec.params["horizon_hours"] == 5
    blob = spec.description.lower()
    assert "tbox" in blob
    assert "clt" in blob
    assert "novel" in blob or "entail" in blob
