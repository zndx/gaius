import pytest

from gaius.engine.services.theta_cycle import enqueue_theta_cycle


class _EnqueueConn:
    def __init__(self, pending_id: int | None = None, pending_slice: str = "") -> None:
        self.pending_id = pending_id
        self.pending_slice = pending_slice
        self.inserted: list[tuple] = []

    async def fetchval(self, sql: str, *args: object):
        if "completed_at IS NULL" in sql:
            if args and args[0] != self.pending_slice:
                return None
            return self.pending_id
        if "INSERT INTO scheduled_tasks" in sql:
            self.inserted.append(args)
            return 99
        return None


@pytest.mark.asyncio
async def test_enqueue_theta_cycle_inserts_metaflow_task() -> None:
    conn = _EnqueueConn()
    tid, fresh = await enqueue_theta_cycle(conn, slice_id="2026-W37", source="operator")
    assert fresh is True and tid == 99
    assert conn.inserted[0][1] == "operator"
    assert "2026-W37" in str(conn.inserted[0][0])


@pytest.mark.asyncio
async def test_enqueue_theta_cycle_reuses_pending() -> None:
    conn = _EnqueueConn(pending_id=7)
    tid, fresh = await enqueue_theta_cycle(conn, source="operator")
    assert tid == 7 and fresh is False
    assert conn.inserted == []


@pytest.mark.asyncio
async def test_enqueue_theta_cycle_reuses_same_slice_only() -> None:
    conn = _EnqueueConn(pending_id=7, pending_slice="2026-W37")
    tid, fresh = await enqueue_theta_cycle(conn, slice_id="2026-W37", source="operator")
    assert tid == 7 and fresh is False
    tid, fresh = await enqueue_theta_cycle(conn, slice_id="2026-W36", source="airflow")
    assert fresh is True and tid == 99
    assert "2026-W36" in str(conn.inserted[0][0])


@pytest.mark.asyncio
async def test_start_current_job_adopts_running_slice() -> None:
    from gaius.engine.services.theta_cycle import start_current_job

    class _Conn:
        async def fetchval(self, sql: str, *args: object):
            if "supersede" in sql.lower() or "RETURNING id" in sql:
                return 0
            if "schedule_theta_consolidation" in sql:
                return None
            return None

        async def fetch(self, sql: str, *args: object):
            return []

        async def fetchrow(self, sql: str, *args: object):
            if "status = 'running'" in sql:
                return {"id": 42, "metadata": {"windows": ["2026-09-14"]}}
            return None

    job_id, superseded, meta = await start_current_job(_Conn(), "2026-W38")
    assert job_id == 42
    assert superseded == 0
    assert meta["windows"] == ["2026-09-14"]


@pytest.mark.asyncio
async def test_load_thoughts_does_not_encode_a_consolidation() -> None:
    """A backfill's landing week must not pick the consolidation up as an input."""
    from gaius.engine.services.theta_cycle import load_thoughts

    seen: list[str] = []

    class _Conn:
        async def fetch(self, sql: str, *args: object):
            seen.append(" ".join(sql.split()))
            assert args[0] == "2026-W40"
            return [{"id": "1", "thought_type": "pattern", "title": "kept"}]

    rows = await load_thoughts(_Conn(), "2026-W40", window_date="2026-09-29")
    assert rows[0]["title"] == "kept"
    assert "thought_type IS DISTINCT FROM 'consolidation'" in seen[0]
    assert "2026-09-29" not in seen[0]


def test_as_meta_dict_does_not_call_dict_on_a_string() -> None:
    from gaius.engine.services.theta_cycle import as_meta_dict

    assert as_meta_dict(None) == {}
    assert as_meta_dict("") == {}
    assert as_meta_dict({"windows": ["2026-09-14"]})["windows"] == ["2026-09-14"]
    assert as_meta_dict('{"windows":["2026-09-14"]}')["windows"] == ["2026-09-14"]
    assert as_meta_dict("not-json") == {}


def test_slice_id_for_monday_logical_date_is_previous_iso_week() -> None:
    from datetime import datetime, timezone

    from gaius.engine.services.theta_cycle import (
        slice_id_for_logical_date,
        slice_id_from_activity,
    )

    monday = datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc)
    assert slice_id_for_logical_date(monday) == "2026-W37"
    assert slice_id_for_logical_date("2026-09-14T06:00:00+00:00") == "2026-W37"
    assert slice_id_from_activity(
        {"postures": {"zndx.logical_date": "2026-09-21T06:00:00+00:00"}}
    ) == "2026-W38"
    assert slice_id_from_activity({}) == ""


def test_blank_week_is_a_failure_not_a_completion() -> None:
    from gaius.engine.services.theta_cycle import BLANK_RESULT, completion_status

    status, err = completion_status(
        success=True,
        windows_done=True,
        has_window=False,
        total_evaluated=0,
        total_augmented=0,
        err=None,
    )
    assert status == "failed"
    assert err == BLANK_RESULT
    status, err = completion_status(
        success=True,
        windows_done=True,
        has_window=True,
        total_evaluated=64,
        total_augmented=0,
        err=None,
    )
    assert status == "failed"
    assert err is not None and "NOUNDERSTANDING" in err
    status, err = completion_status(
        success=True,
        windows_done=False,
        has_window=True,
        total_evaluated=0,
        total_augmented=0,
        err=None,
    )
    assert status == "scheduled" and err is None
    status, err = completion_status(
        success=True,
        windows_done=True,
        has_window=False,
        total_evaluated=0,
        total_augmented=0,
        err=None,
        has_understanding=True,
    )
    assert status == "completed" and err is None


def test_only_the_closing_run_owes_an_understanding() -> None:
    from gaius.engine.services.theta_cycle import iso_week_days, run_closes_week

    days = iso_week_days("2026-W39")
    assert days[0] == "2026-09-21" and days[-1] == "2026-09-27"
    assert run_closes_week("", [], "2026-W39") is True
    assert run_closes_week("2026-09-21", ["2026-09-21"], "2026-W39") is False
    assert run_closes_week("2026-09-27", days[:-1], "2026-W39") is True
    assert run_closes_week("", [], "") is False


def test_daily_window_refines_containing_week_artifact() -> None:
    from gaius.engine.services.theta_cycle import (
        iso_week_days,
        merge_centroid,
        slice_id_from_activity,
        week_is_complete,
        window_date_from_activity,
    )

    act = {
        "postures": {
            "zndx.logical_date": "2026-09-14T06:00:00+00:00",
            "zndx.window_date": "2026-09-14",
        }
    }
    assert window_date_from_activity(act) == "2026-09-14"
    assert slice_id_from_activity(act) == "2026-W38"
    days = iso_week_days("2026-W38")
    assert days[0] == "2026-09-14" and days[-1] == "2026-09-20" and len(days) == 7
    assert not week_is_complete(["2026-09-14", "2026-09-15"], "2026-W38")
    assert week_is_complete(days, "2026-W38")
    merged, n = merge_centroid(None, 0, [[2.0, 0.0], [0.0, 2.0]])
    assert n == 2 and merged == [1.0, 1.0]
    merged, n = merge_centroid(merged, n, [[1.0, 1.0]])
    assert n == 3 and merged[0] == pytest.approx(1.0)


def test_theta_service_has_no_in_engine_consolidator() -> None:
    from gaius.engine.services.theta_service import ThetaService

    assert not hasattr(ThetaService, "run_consolidation")
    assert hasattr(ThetaService, "enqueue_consolidation")


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
    assert ThetaCycleFlow.model == "lightonai/ColBERT-Zero"
    from gaius.engine.sentinel_claim import LIGHT, resource_class_for

    assert resource_class_for("theta-cycle") is LIGHT
    assert hasattr(ThetaCycleFlow, "extract")
    assert hasattr(ThetaCycleFlow, "encode")
    assert hasattr(ThetaCycleFlow, "infer")
    assert hasattr(ThetaCycleFlow, "complete")
    assert hasattr(ThetaCycleFlow, "end")
    assert not hasattr(ThetaCycleFlow, "maintain")
    assert not hasattr(ThetaCycleFlow, "settle")
    from gaius.flows.base import GaiusFlow

    assert "kb_root" not in vars(ThetaCycleFlow)
    assert isinstance(vars(GaiusFlow)["kb_root"], property)


def test_cco_catalog_maps_trailing_slash_import() -> None:
    from pathlib import Path

    catalog = (
        Path(__file__).resolve().parents[2]
        / "external/sdg-corpora/ontology/catalog-v001.xml"
    )
    text = catalog.read_text(encoding="utf-8")
    assert "https://signals.zndx.org/sdg/imports/cco-module/" in text
    assert "imports/cco-module.ttl" in text


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


def test_empty_tbox_collection_is_not_an_index() -> None:
    from types import SimpleNamespace

    from gaius.agents.theta.tbox_maxsim import tbox_index_ready

    class Client:
        def __init__(self, exists: bool, count: int) -> None:
            self._exists = exists
            self._count = count

        def collection_exists(self, _name: str) -> bool:
            return self._exists

        def count(self, _name: str) -> SimpleNamespace:
            return SimpleNamespace(count=self._count)

    assert tbox_index_ready(Client(True, 0), 905) is False
    assert tbox_index_ready(Client(True, 904), 905) is False
    assert tbox_index_ready(Client(True, 905), 905) is True
    assert tbox_index_ready(Client(False, 905), 905) is False


def test_tbox_upsert_stays_under_qdrant_body_limit() -> None:
    from gaius.agents.theta.tbox_maxsim import UPSERT_BATCH, upsert_in_batches

    class Client:
        def __init__(self) -> None:
            self.chunks: list[int] = []

        def upsert(self, *, collection_name: str, points: list[object]) -> None:
            assert collection_name == "sdg_tbox"
            self.chunks.append(len(points))

    points = list(range(UPSERT_BATCH * 2 + 3))
    client = Client()
    sent = upsert_in_batches(client, points)
    assert sent == len(points)
    assert client.chunks == [UPSERT_BATCH, UPSERT_BATCH, 3]
    assert max(client.chunks) <= UPSERT_BATCH


def test_owlapi_import_is_the_local_cco_file(tmp_path) -> None:
    from rdflib import Graph, Namespace

    from gaius.agents.theta.tbox import CCO_IRI, ontology_for_owlapi

    onto = tmp_path / "tiny.owl"
    onto.write_text(
        """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/tiny">
    <owl:imports rdf:resource="https://signals.zndx.org/sdg/imports/cco-module"/>
  </owl:Ontology>
</rdf:RDF>
""",
        encoding="utf-8",
    )
    imports = tmp_path / "imports"
    imports.mkdir()
    (imports / "cco-module.ttl").write_text(
        """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
<http://example.org/cco> a owl:Ontology .
""",
        encoding="utf-8",
    )
    ready = ontology_for_owlapi(onto)
    graph = Graph()
    graph.parse(ready, format="xml")
    OWL = Namespace("http://www.w3.org/2002/07/owl#")
    imported = {str(o) for o in graph.objects(None, OWL.imports)}
    assert imported
    assert all(not iri.startswith("https://signals.zndx.org/") for iri in imported)
    assert all(iri.startswith("file:") for iri in imported)
    assert CCO_IRI not in imported
    local = next(iter(imported)).removeprefix("file://")
    assert local.endswith("cco-module.rdf")


def test_deeponto_training_kwargs_match_transformers_5() -> None:
    from gaius.agents.theta.subsumption import translate_deeponto_training_kwargs

    # The names TrainingArguments still accepts in transformers 5.15.
    parameters = {
        "self",
        "output_dir",
        "warmup_steps",
        "eval_strategy",
        "weight_decay",
        "logging_steps",
    }
    got = translate_deeponto_training_kwargs(
        {
            "output_dir": "/tmp/bertsubs",
            "warmup_ratio": 0.1,
            "evaluation_strategy": "steps",
            "logging_dir": "/tmp/bertsubs/tb",
            "weight_decay": 0.01,
        },
        parameters,
    )
    assert got["warmup_steps"] == 0.1
    assert "warmup_ratio" not in got
    assert got["eval_strategy"] == "steps"
    assert "evaluation_strategy" not in got
    assert "logging_dir" not in got
    assert got["weight_decay"] == 0.01


def test_deeponto_trainer_tokenizer_is_processing_class() -> None:
    from gaius.agents.theta.subsumption import translate_deeponto_trainer_kwargs

    parameters = {
        "self",
        "model",
        "args",
        "train_dataset",
        "eval_dataset",
        "processing_class",
        "compute_metrics",
    }
    tok = object()
    got = translate_deeponto_trainer_kwargs(
        {"model": "bert", "tokenizer": tok, "compute_metrics": None},
        parameters,
    )
    assert got["processing_class"] is tok
    assert "tokenizer" not in got
    assert got["model"] == "bert"


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
