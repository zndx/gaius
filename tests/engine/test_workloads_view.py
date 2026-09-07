"""/workloads — Engine-First view of the catalogue + last sync, and its rendering."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from gaius.cli_render.workloads import render_workloads
from gaius.engine.generated import WorkloadsViewRequest
from gaius.engine.services import workload_catalog as wc
from gaius.engine.services import workload_sync as ws


def _servicer():
    from gaius.engine.grpc.servicers.gaius_servicer import GaiusServicer

    svc = GaiusServicer.__new__(GaiusServicer)
    return svc


def test_workloads_view_lists_the_catalogue_with_sync_state(monkeypatch):
    sync = ws.WorkloadSync("signals:1")
    sync.last_sync_ms = 1_788_745_000_000
    sync.syncs = 2
    sync.last_records = [
        {"id": "task.article_curate", "kind": "article_curate", "dag_id": "gaius_article_curate", "state": "materialized", "error": ""},
        {"id": "task.fmp_roll", "kind": "fmp_roll", "dag_id": "gaius_fmp_roll", "state": "paused", "error": ""},
    ]
    monkeypatch.setattr(ws, "_SYNC", sync)
    svc = _servicer()
    resp = asyncio.run(svc.Workloads(WorkloadsViewRequest(), MagicMock()))
    assert not resp.error
    assert len(resp.rows) == len(wc.entries())
    assert resp.signals_target == "signals:1" and resp.syncs == 2 and resp.last_sync_at.startswith("2026-")
    by_id = {r.id: r for r in resp.rows}
    cur = by_id["task.article_curate"]
    assert cur.enabled and cur.source == "airflow" and cur.sync_state == "materialized"
    assert list(cur.claims) == ["root.internal.inference.extract:1"]
    assert cur.gate_sql == "SELECT collections.should_run_curation()" and cur.runner == "metaflow"
    roll = by_id["task.fmp_roll"]
    assert not roll.enabled and roll.source == "pg_cron" and roll.sync_state == "paused"
    assert by_id["task.engine_audit"].sync_state == ""  # never reported by Signals
    # filters
    only = asyncio.run(svc.Workloads(WorkloadsViewRequest(enabled_only=True), MagicMock()))
    assert [r.kind for r in only.rows] == [e.kind for e in wc.enabled_entries()]
    assert "article_curate" in [r.kind for r in only.rows] and "agenda_brief" in [r.kind for r in only.rows]
    one = asyncio.run(svc.Workloads(WorkloadsViewRequest(kind="clt_skos_label"), MagicMock()))
    assert len(one.rows) == 1 and list(one.rows[0].after) == ["task.clt_skos_admit"]


def test_workloads_view_without_sync_is_honest(monkeypatch):
    monkeypatch.setattr(ws, "_SYNC", None)
    resp = asyncio.run(_servicer().Workloads(WorkloadsViewRequest(), MagicMock()))
    assert not resp.error and resp.last_sync_at == "" and resp.syncs == 0
    assert all(r.sync_state == "" for r in resp.rows)


def test_render_workloads():
    rows = [
        {"id": "task.article_curate", "kind": "article_curate", "source": "airflow", "cron": "7 9 * * *", "runner": "metaflow",
         "claims": ["root.internal.inference.extract:1"], "enabled": True, "airflow_dag_id": "gaius_article_curate",
         "pg_cron_job": "article-curate-daily", "pg_cron_active": True, "horizon_s": 18000, "after": [],
         "gate_sql": "SELECT collections.should_run_curation()", "sync_state": "materialized"},
        {"id": "task.clt_skos_label", "kind": "clt_skos_label", "source": "pg_cron", "cron": "*/15 * * * *", "runner": "metaflow",
         "claims": [], "enabled": False, "airflow_dag_id": "gaius_clt_skos_label", "pg_cron_job": "clt-skos-label",
         "pg_cron_active": True, "horizon_s": 3600, "after": ["task.clt_skos_admit"], "sync_state": "paused"},
    ]
    out = render_workloads(rows, signals_target="127.0.0.1:50551", last_sync_at="2026-09-07T03:00:00+00:00")
    assert "submitted to 127.0.0.1:50551" in out
    assert "2 classes · 1 scheduled in Airflow · 1 on pg_cron" in out
    assert "▶ article_curate" in out and "materialized" in out
    assert "after task.clt_skos_admit" in out and "paused" in out
    assert "gate SELECT collections.should_run_curation()" in out
    empty = render_workloads([], signals_target="x")
    assert "NOT yet submitted" in empty and "(empty)" in empty
