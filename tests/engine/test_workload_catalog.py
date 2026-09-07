"""The WORKLOAD CATALOGUE is held to pg_cron: every scheduled_tasks-enqueuing
cron job in the migrations has a catalogue entry with the same task_type and
payload, and the catalogue's wire form (ScheduleHint) carries every field."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from gaius.engine.services import workload_catalog as wc

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "migrations"

# cron.schedule('<name>', '<cron>', <body>) — body is $$…$$ or '…' quoted.
_SCHEDULE = re.compile(
    r"cron\.schedule\(\s*'(?P<name>[^']+)'\s*,\s*'(?P<cron>[^']+)'\s*,\s*"
    r"(?:\$\$(?P<body_dq>.*?)\$\$|'(?P<body_sq>(?:[^']|'')*)')",
    re.S,
)
# INSERT INTO scheduled_tasks (...) VALUES|SELECT 'task_type', 'payload'
_INSERT = re.compile(
    r"INSERT\s+INTO\s+scheduled_tasks\s*\([^)]*\)\s*(?:VALUES\s*\(|SELECT)\s*'(?P<task>[a-z_]+)'\s*,\s*'(?P<payload>(?:[^']|'')*)'",
    re.S | re.I,
)
_UNSCHEDULE = re.compile(r"cron\.unschedule\(\s*'(?P<name>[^']+)'", re.S)


def _pg_cron_jobs_from_migrations() -> dict[str, dict]:
    """jobname → {cron, task_type, payload} — the LAST definition in migration order wins;
    an unschedule after the last definition retires the job."""
    jobs: dict[str, dict] = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        # dbmate: only the `-- migrate:up` half is what the database runs forward;
        # the `down` half unschedules (or, in a retire migration, re-schedules)
        # and must not be read as live policy.
        cut = text.find("-- migrate:down")
        if cut >= 0:
            text = text[:cut]
        events: list[tuple[int, str, dict | None]] = []
        for m in _SCHEDULE.finditer(text):
            body = m.group("body_dq") if m.group("body_dq") is not None else (m.group("body_sq") or "").replace("''", "'")
            ins = _INSERT.search(body)
            if ins is None:
                continue  # not a scheduled_tasks enqueuer (cleanup SQL, function calls)
            raw = ins.group("payload").replace("''", "'")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw
            events.append((m.start(), "schedule", {"name": m.group("name"), "cron": m.group("cron"), "task_type": ins.group("task"), "payload": payload, "file": path.name}))
        for m in _UNSCHEDULE.finditer(text):
            events.append((m.start(), "unschedule", {"name": m.group("name")}))
        for _, kind, ev in sorted(events, key=lambda t: t[0]):
            if kind == "schedule":
                jobs[ev["name"]] = ev
            else:
                jobs.pop(ev["name"], None)
    return jobs


@pytest.fixture(scope="module")
def migration_jobs() -> dict[str, dict]:
    jobs = _pg_cron_jobs_from_migrations()
    assert jobs, "no scheduled_tasks-enqueuing cron.schedule found in db/migrations"
    return jobs


def test_every_pg_cron_enqueuer_is_catalogued(migration_jobs):
    by_job = {e.pg_cron_job: e for e in wc.entries() if e.pg_cron_job}
    missing = sorted(name for name in migration_jobs if name not in by_job)
    assert not missing, f"pg_cron enqueuers without a catalogue entry: {missing}"


def test_catalogue_matches_pg_cron_task_type_and_payload(migration_jobs):
    by_job = {e.pg_cron_job: e for e in wc.entries() if e.pg_cron_job}
    mismatches = []
    for name, job in migration_jobs.items():
        e = by_job.get(name)
        if e is None:
            continue
        if e.task_type != job["task_type"]:
            mismatches.append(f"{name}: task_type {e.task_type} != {job['task_type']} ({job['file']})")
        if isinstance(job["payload"], dict) and e.payload != job["payload"]:
            mismatches.append(f"{name}: payload {e.payload} != {job['payload']} ({job['file']})")
    assert not mismatches, "\n".join(mismatches)


def test_catalogue_cron_matches_pg_cron(migration_jobs):
    """An entry whose pg_cron job is still ACTIVE carries that job's cron. An
    entry whose schedule moved to Airflow (enabled, pg_cron job inactive) carries
    the DAG's schedule — asserted per entry below — not the retired job's."""
    by_job = {e.pg_cron_job: e for e in wc.entries() if e.pg_cron_job}
    mismatches = [
        f"{name}: cron {by_job[name].cron!r} != {job['cron']!r} ({job['file']})"
        for name, job in migration_jobs.items()
        if name in by_job
        and not (by_job[name].enabled and not by_job[name].pg_cron_active)
        and by_job[name].cron != job["cron"]
    ]
    assert not mismatches, "\n".join(mismatches)
    # the retired-to-Airflow entry whose DAG schedule differs from its old job
    assert migration_jobs["agenda-brief"]["cron"] == "13 1,5,9,13,17,21 * * *"  # the inactive 4 h job
    assert by_job["agenda-brief"].cron == "5 0 * * *"  # the DAG's day rollover


def test_kinds_and_ids_are_unique_and_entry_for_resolves_both():
    kinds = [e.kind for e in wc.entries()]
    assert len(kinds) == len(set(kinds))
    for e in wc.entries():
        assert wc.entry_for(e.kind) is e
        assert wc.entry_for(e.id) is e
    assert wc.entry_for("nope") is None


AIRFLOW_ENABLED = {
    "article_curate",
    # the agenda producers (2026-09-07 evening) …
    "publish_cards_predawn", "publish_cards_morning", "publish_cards_afternoon", "publish_cards_evening",
    "prospects_check", "cognition_cycle", "weekly_signals_summary",
    # … and the digest Airflow initiates when any of them ends
    "agenda_brief",
}


def test_enabled_entries_are_curate_the_agenda_producers_and_the_brief():
    assert {e.kind for e in wc.enabled_entries()} == AIRFLOW_ENABLED
    e = wc.entry_for("article_curate")
    assert e.source == "airflow" and wc.airflow_dag_id(e) == "gaius_article_curate"
    assert e.gate_sql == "SELECT collections.should_run_curation()"
    assert e.payload == {"check_cooldown": True}
    for kind in AIRFLOW_ENABLED:
        en = wc.entry_for(kind)
        assert en.source == "airflow" and wc.airflow_dag_id(en) == f"gaius_{kind}"
    # producers coexist with their pg_cron jobs until Airflow has proven a run
    for kind in AIRFLOW_ENABLED - {"article_curate", "agenda_brief"}:
        assert wc.entry_for(kind).pg_cron_active, kind
    # every other class: catalogued, pg_cron-sourced, Signals assigns the DAG id
    for other in wc.entries():
        if other.kind not in AIRFLOW_ENABLED:
            assert other.source == "pg_cron"
            assert wc.airflow_dag_id(other) == f"gaius_{other.kind}"


def test_ordering_is_declared_for_label_after_admit():
    label = wc.entry_for("clt_skos_label")
    assert label.after == ("task.clt_skos_admit",)
    assert label.after_mode == wc.AFTER_ALL
    assert wc.entry_for("task.clt_skos_admit") is not None  # the target exists
    assert wc.wire_cron(label) == ""  # asset-scheduled only; cron stays the migration record


def test_agenda_brief_follows_any_producer_and_the_day_rollover(monkeypatch):
    brief = wc.entry_for("agenda_brief")
    assert brief.enabled and not brief.pg_cron_active and brief.pg_cron_job == "agenda-brief"
    assert brief.after == wc.AGENDA_PRODUCERS and brief.after_mode == wc.AFTER_ANY
    for pid in brief.after:
        target = wc.entry_for(pid)
        assert target is not None and target.enabled, f"{pid} must be Airflow-declared so its ended Asset fires"
    assert wc.wire_cron(brief) == "5 0 * * *"  # time OR assets
    # the rollover is the operator's midnight: the entry's zone follows the Agenda's
    monkeypatch.delenv("GAIUS_AGENDA_TZ", raising=False)
    assert wc.timezone_for(brief) in {"UTC", wc.timezone_for(brief)}
    monkeypatch.setenv("GAIUS_AGENDA_TZ", "America/Los_Angeles")
    assert wc.timezone_for(brief) == "America/Los_Angeles"
    h = wc.to_hint(brief)
    assert h.cron == "5 0 * * *" and h.after_mode == "any" and list(h.after) == list(wc.AGENDA_PRODUCERS)
    assert h.timezone == "America/Los_Angeles" and h.enabled and h.airflow_dag_id == "gaius_agenda_brief"
    d = wc.as_dict(brief)
    assert d["after_mode"] == "any" and d["wire_cron"] == "5 0 * * *" and d["timezone"] == "America/Los_Angeles"


def test_publish_slots_are_distinct_kinds_of_one_task_type():
    slots = [e for e in wc.entries() if e.task_type == "publish_cards"]
    assert len(slots) == 4
    assert len({e.kind for e in slots}) == 4
    assert {e.payload["slot"] for e in slots} == {"predawn", "morning", "afternoon", "evening"}


def test_claims_follow_declared_intents_and_resource_classes():
    # article-curate declares an extract floor in the supervision instance
    curate = wc.claims_for("article_curate")
    assert curate == [{"leaf": "root.internal.inference.extract", "gpu": 1}]
    # ambient synthesis: the shared embedding claim on light (declared phase intent)
    ambient = {c["leaf"]: c["gpu"] for c in wc.claims_for("ambient_synthesis")}
    assert ambient.get("root.internal.inference.light") == 1
    # zero-GPU classes carry no claims
    assert wc.claims_for("engine_audit") == []
    assert wc.claims_for("fmp_roll") == []
    # unknown kind → nothing (never an exception)
    assert wc.claims_for("no_such_kind") == []


def test_schedule_hints_serialise_every_field():
    hints = {h.id: h for h in wc.schedule_hints()}
    assert len(hints) == len(wc.entries())
    h = hints["task.article_curate"]
    assert h.kind == "article_curate" and h.source == "airflow" and h.enabled
    assert h.airflow_dag_id == "gaius_article_curate" and h.cron == "7 9 * * *"
    assert h.runner == "metaflow" and h.horizon_s == wc.H5 and h.timezone == "UTC"
    assert [(c.leaf, c.gpu) for c in h.claims] == [("root.internal.inference.extract", 1)]
    label = hints["task.clt_skos_label"]
    assert list(label.after) == ["task.clt_skos_admit"] and label.source == "pg_cron" and not label.enabled
    assert label.after_mode == "all" and label.cron == ""
    assert hints["task.fmp_roll"].airflow_dag_id == "gaius_fmp_roll"
    assert hints["task.fmp_roll"].after_mode == ""  # no `after` → no mode on the wire
    slot = hints["task.publish_cards_morning"]
    assert slot.enabled and slot.source == "airflow" and slot.cron == "0 17 * * *" and slot.after_mode == ""
    assert hints["task.metabase_sync"].description  # inactive job still catalogued, described


def test_as_dict_and_payload_json_roundtrip():
    e = wc.entry_for("evolution_cycle")
    d = wc.as_dict(e)
    assert d["id"] == "task.evolution_cycle" and d["runner"] == "task"
    assert json.loads(wc.payload_json(e)) == e.payload
