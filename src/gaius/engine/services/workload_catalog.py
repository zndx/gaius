"""The gaius WORKLOAD CATALOGUE — every scheduled class this engine runs, with
the cadence, the way it is enqueued, its YuniKorn queue configuration and its
ordering, in one place.

Doctrine (user, 2026-09-07): "With workloads being synced from every project
soon, we need reliable ordering with associated YK configurations Signals (the
engine) can pick up and apply to YK for the duration of the scheduled active
workflow, be it Metaflow or otherwise, including the interactive workflow
defined today for agent-rtc from Hermes."

Three consumers read this catalogue:

- ``ServerQuery kind=SCHEDULES`` publishes it on this engine's own face
  (``schedule_hints()`` → ``zndx.engine.v1.ScheduleHint`` per entry).
- ``services.workload_sync`` SUBMITS it to Signals
  (``Scheduler/SyncWorkloads``, replace = the whole truth) so Signals
  materialises one Airflow DAG per enabled entry whose runs are Activities
  asserting ``claims`` for exactly the run's duration.
- ``services.coordination`` starts ANY catalogued kind when it sees this
  engine's own Activity of that kind in force — ``task_type``, ``payload`` and
  ``gate_sql`` are pg_cron's enqueue VERBATIM, so an Airflow-declared run and a
  cron-declared run are the same workload to the processor.

The entries mirror ``cron.job`` (the live enqueuers) — ``tests/engine/
test_workload_catalog.py`` holds them to the migrations. Claims come from the
declared intents in ``config/supervision/gaius.textproto`` (the same
precedence ``queue_share.share_for_class`` uses at admission), else from the
kind's resource class occupancy.

Only ``article_curate`` is ``enabled`` today: it is the class whose schedule
has moved to the Signals Airflow. Every other entry is catalogued so the whole
procession is visible in Airflow (materialised PAUSED) before each class
migrates by flipping ``enabled`` — one class at a time, pg_cron retired once
the Airflow path has proven a run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PEER = "gaius"
TIMEZONE = "UTC"

# Fibonacci-hour outer bounds for ONE run (the Airflow sensor's timeout base).
H1 = 1 * 3600
H2 = 2 * 3600
H3 = 3 * 3600
H5 = 5 * 3600

RUNNER_METAFLOW = "metaflow"
RUNNER_TASK = "task"


@dataclass(frozen=True)
class WorkloadEntry:
    """One scheduled class as pg_cron enqueues it, plus its Airflow shape."""

    kind: str                       # activity kind (unique in the catalogue)
    task_type: str                  # scheduled_tasks.task_type the processor runs
    payload: dict[str, Any]         # pg_cron payload VERBATIM
    cron: str                       # pg_cron schedule (UTC)
    description: str
    gate_sql: str | None = None     # pg_cron WHERE predicate, as a SELECT (None = unconditional)
    singleton: bool = False         # pg_cron guards with NOT EXISTS (one live row per class)
    runner: str = RUNNER_TASK
    horizon_s: int = H2
    after: tuple[str, ...] = ()     # catalogue ids this workload follows (Asset-scheduled)
    enabled: bool = False           # True = its schedule lives in the Signals Airflow
    airflow_dag_id: str = ""        # "" → Signals assigns <peer>_<kind>
    pg_cron_job: str = ""           # the enqueuer's jobname (retired once Airflow proves a run)
    pg_cron_active: bool = True
    precludes: tuple[str, ...] = ()
    postures: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"task.{self.kind}"

    @property
    def source(self) -> str:
        return "airflow" if self.enabled else "pg_cron"


WORKLOAD_CATALOG: tuple[WorkloadEntry, ...] = (
    WorkloadEntry(
        kind="article_curate", task_type="article_curate",
        payload={"check_cooldown": True}, cron="7 9 * * *",
        gate_sql="SELECT collections.should_run_curation()",
        runner=RUNNER_METAFLOW, horizon_s=H5,
        description="daily article curation (Brave + arXiv, goggle) — extract floor while docling runs",
        enabled=True, airflow_dag_id="gaius_article_curate", pg_cron_job="article-curate-daily",
        pg_cron_active=False,  # retired 2026-09-07 03:16 after the first full Airflow-ordered run
    ),
    WorkloadEntry(
        kind="ambient_synthesis", task_type="ambient_synthesis", payload={}, cron="*/20 * * * *",
        singleton=True, runner=RUNNER_METAFLOW, horizon_s=H1,
        description="ambient synthesis (HN fetch → compact → synthesize on thinking; shared embedding claim)",
        pg_cron_job="ambient-synthesis",
    ),
    WorkloadEntry(
        kind="fmp_roll", task_type="fmp_roll", payload={}, cron="7,37 * * * *",
        singleton=True, runner=RUNNER_METAFLOW, horizon_s=H3,
        description="FMP market buffer roll (rate-metered API; compaction on thinking)",
        pg_cron_job="fmp-roll",
    ),
    WorkloadEntry(
        kind="clt_skos_admit", task_type="clt_skos_admit", payload={}, cron="*/15 * * * *",
        gate_sql="SELECT public.should_run_clt_skos('admit')", runner=RUNNER_METAFLOW, horizon_s=H1,
        description="CLT/SKOS admit tick (light leaf probe)", pg_cron_job="clt-skos-admit",
    ),
    WorkloadEntry(
        kind="clt_skos_label", task_type="clt_skos_label", payload={}, cron="*/15 * * * *",
        gate_sql="SELECT public.should_run_clt_skos('label')", runner=RUNNER_METAFLOW, horizon_s=H1,
        after=("task.clt_skos_admit",),
        description="CLT/SKOS label tick — follows the admit tick", pg_cron_job="clt-skos-label",
    ),
    WorkloadEntry(
        kind="feature_probe", task_type="feature_probe", payload={"gpu_index": 4}, cron="*/5 * * * *",
        singleton=True, horizon_s=H1,
        description="CLT feature probe (gates the CLT worker's light admission)", pg_cron_job="feature-probe",
    ),
    WorkloadEntry(
        kind="board_reindex", task_type="board_reindex", payload={}, cron="* * * * *",
        gate_sql="SELECT meta.should_run_board_reindex()", singleton=True, horizon_s=H1,
        description="board reindex (per-minute, gated)", pg_cron_job="board-reindex",
    ),
    WorkloadEntry(
        kind="tier_settle", task_type="tier_settle", payload={"product": "signal"}, cron="20 * * * *",
        singleton=True, horizon_s=H1,
        description="hourly THS settle of the signal product (Kudu → HDF5 → RustFS → Iceberg)",
        pg_cron_job="tier-settle-signal",
    ),
    WorkloadEntry(
        kind="engine_audit", task_type="engine_audit", payload={}, cron="30 * * * *", horizon_s=H1,
        description="hourly engine audit", pg_cron_job="engine-audit-hourly",
    ),
    WorkloadEntry(
        kind="heuristic_triage", task_type="heuristic_triage", payload={"limit": 100}, cron="5 * * * *",
        horizon_s=H1, description="hourly heuristic triage", pg_cron_job="heuristic-triage-hourly",
    ),
    WorkloadEntry(
        kind="llm_triage", task_type="llm_triage", payload={"limit": 50}, cron="35 0,4,8,12,16,20 * * *",
        horizon_s=H2, description="LLM triage (4 h anchors, on thinking)", pg_cron_job="llm-triage-periodic",
    ),
    WorkloadEntry(
        kind="content_processing", task_type="content_processing", payload={"limit": 30}, cron="45 */2 * * *",
        horizon_s=H2, description="content processing (2 h cadence)", pg_cron_job="content-processing",
    ),
    WorkloadEntry(
        kind="cognition_cycle", task_type="cognition_cycle", payload={"trigger": "scheduled"},
        cron="43 0,4,8,12,16,20 * * *", horizon_s=H2,
        description="cognition cycle (4 h anchors; pg_cron jitters up to 45 min)", pg_cron_job="cognition-periodic",
    ),
    WorkloadEntry(
        kind="feed_check", task_type="feed_check", payload={}, cron="17 */4 * * *", horizon_s=H2,
        description="feed check (pg_cron jitters up to 30 min)", pg_cron_job="check-due-fetches",
    ),
    WorkloadEntry(
        kind="objective_verify", task_type="objective_verify", payload={}, cron="38 1,7,13,19 * * *",
        horizon_s=H5, description="objective verification (6 h; judged verdicts run long)",
        pg_cron_job="objective-verify",
    ),
    WorkloadEntry(
        kind="publish_cards_predawn", task_type="publish_cards", payload={"count": 3, "slot": "predawn"},
        cron="0 12 * * *", horizon_s=H5, description="publish slot predawn (3 cards)",
        pg_cron_job="publish-cards-predawn",
    ),
    WorkloadEntry(
        kind="publish_cards_morning", task_type="publish_cards", payload={"count": 1, "slot": "morning"},
        cron="0 17 * * *", horizon_s=H5, description="publish slot morning", pg_cron_job="publish-cards-morning",
    ),
    WorkloadEntry(
        kind="publish_cards_afternoon", task_type="publish_cards", payload={"count": 1, "slot": "afternoon"},
        cron="0 21 * * *", horizon_s=H5, description="publish slot afternoon", pg_cron_job="publish-cards-afternoon",
    ),
    WorkloadEntry(
        kind="publish_cards_evening", task_type="publish_cards", payload={"count": 1, "slot": "evening"},
        cron="0 2 * * *", horizon_s=H5, description="publish slot evening", pg_cron_job="publish-cards-evening",
    ),
    WorkloadEntry(
        kind="prospects_check", task_type="prospects_check", payload={}, cron="0 7 * * *",
        gate_sql="SELECT meta.should_run_prospects_check()", runner=RUNNER_METAFLOW, horizon_s=H3,
        description="daily prospects check (decides the update; rate-metered FMP)", pg_cron_job="prospects-daily-check",
    ),
    WorkloadEntry(
        kind="content_diversity_check", task_type="content_diversity_check", payload={}, cron="0 6,18 * * *",
        horizon_s=H2, description="content diversity check", pg_cron_job="content-diversity-check",
    ),
    WorkloadEntry(
        kind="content_summarization", task_type="content_summarization", payload={"batch_size": 20},
        cron="0 5 * * 1,4", horizon_s=H3, description="content summarization (Mon/Thu)",
        pg_cron_job="content-summarization-biweekly",
    ),
    WorkloadEntry(
        kind="weekly_summary", task_type="weekly_summary", payload={"use_llm": True, "write_to_kb": True},
        cron="0 20 * * 0", runner=RUNNER_METAFLOW, horizon_s=H3, description="weekly summary flow",
        pg_cron_job="weekly-summary",
    ),
    WorkloadEntry(
        kind="weekly_signals_summary", task_type="weekly_signals_summary", payload={"previous": True},
        cron="0 15 * * 1", gate_sql="SELECT meta.should_run_weekly_signals_summary()", singleton=True,
        horizon_s=H3, description="weekly Signals summary (Monday)", pg_cron_job="weekly-signals-summary",
    ),
    WorkloadEntry(
        kind="evolution_cycle", task_type="evolution_cycle",
        payload={"agents": ["leader", "risk", "critic", "opportunity", "domain"], "num_items": 10, "source": "weekly_scheduled"},
        cron="0 3 * * 0", horizon_s=H5, description="weekly evolution cycle", pg_cron_job="evolution-weekly",
    ),
    WorkloadEntry(
        kind="research_processing", task_type="research_processing", payload={}, cron="30 4 * * 0",
        horizon_s=H3, description="weekly research processing", pg_cron_job="research-processing-weekly",
    ),
    WorkloadEntry(
        kind="tda_computation", task_type="tda_computation", payload={}, cron="0 6 * * 1,4",
        horizon_s=H3, description="TDA computation (Mon/Thu)", pg_cron_job="tda-biweekly",
    ),
    WorkloadEntry(
        kind="metaagent_audit", task_type="metaagent_audit", payload={"scope": "full", "use_remote_llm": True},
        cron="0 5 * * 1", horizon_s=H3, description="weekly metaagent audit", pg_cron_job="metaagent-weekly-audit",
    ),
    WorkloadEntry(
        kind="metabase_sync", task_type="metabase_sync", payload={"full_refresh": False}, cron="0 * * * *",
        horizon_s=H1, description="hourly Metabase sync (pg_cron job inactive)",
        pg_cron_job="metabase-hourly-sync", pg_cron_active=False,
    ),
    WorkloadEntry(
        kind="task_ideation", task_type="task_ideation", payload={"max_concepts": 5, "novelty_threshold": 0.4},
        cron="0 2 1 * *", horizon_s=H3, description="monthly task ideation", pg_cron_job="task-ideation-monthly",
    ),
    WorkloadEntry(
        kind="held_out_refresh", task_type="held_out_refresh", payload={"sample_size": 100}, cron="0 3 1 1,4,7,10 *",
        horizon_s=H3, description="quarterly held-out refresh", pg_cron_job="held-out-refresh-quarterly",
    ),
    WorkloadEntry(
        kind="model_merge", task_type="model_merge", payload={"agents": None}, cron="0 4 1 1,4,7,10 *",
        horizon_s=H5, description="quarterly model merge", pg_cron_job="model-merge-quarterly",
    ),
)

_BY_KIND: dict[str, WorkloadEntry] = {e.kind: e for e in WORKLOAD_CATALOG}
_BY_ID: dict[str, WorkloadEntry] = {e.id: e for e in WORKLOAD_CATALOG}


def entry_for(kind: str) -> WorkloadEntry | None:
    """The catalogue entry for an activity kind (or a catalogue id)."""
    k = str(kind or "")
    return _BY_KIND.get(k) or _BY_ID.get(k)


def entries() -> tuple[WorkloadEntry, ...]:
    return WORKLOAD_CATALOG


def enabled_entries() -> list[WorkloadEntry]:
    return [e for e in WORKLOAD_CATALOG if e.enabled]


def airflow_dag_id(entry: WorkloadEntry) -> str:
    return entry.airflow_dag_id or f"{PEER}_{entry.kind}"


# ── claims: the workload's YuniKorn queue configuration ──────────────────────
def claims_for(kind: str) -> list[dict[str, Any]]:
    """[{leaf, gpu}] this class occupies while it runs — the same precedence
    admission uses: the declared intents in the supervision instance for this
    owner kind (max floor per leaf/workload), else the kind's resource-class
    occupancy. Zero-GPU classes carry no claims."""
    entry = entry_for(kind)
    if entry is None:
        return []
    owner = entry.task_type.replace("_", "-")
    out: dict[str, int] = {}
    try:
        from gaius.engine.supervision_spec import load_spec

        spec = load_spec()
    except Exception:  # noqa: BLE001 — the instance's problems are logged by the loader
        spec = None
    if spec is not None:
        by_owner = getattr(spec, "_by_owner", {}) or {}
        for workload, intents in (by_owner.get(owner) or {}).items():
            best = max(intents, key=lambda i: (int(i.floor), int(i.priority)))
            leaf = str(best.leaf)
            out[leaf] = max(out.get(leaf, 0), int(best.floor))
    if not out:
        try:
            from gaius.engine.sentinel_claim import resource_class_for

            rc = resource_class_for(entry.task_type)
            if int(rc.gpu_tokens) > 0:
                out[str(rc.queue)] = int(rc.gpu_tokens)
        except Exception:  # noqa: BLE001 — no resource class ⇒ no GPU occupancy
            pass
    return [{"leaf": leaf, "gpu": gpu} for leaf, gpu in sorted(out.items())]


# ── wire ─────────────────────────────────────────────────────────────────────
def to_hint(entry: WorkloadEntry) -> Any:
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    # An `after` entry is ASSET-scheduled in Airflow (it runs when the workload it
    # follows ends); its pg_cron cadence stays on the entry as the migration
    # record but is not the DAG's schedule — Signals refuses cron+after together.
    hint = zpb.ScheduleHint(
        id=entry.id,
        cron="" if entry.after else entry.cron,
        airflow_dag_id=airflow_dag_id(entry),
        source=entry.source,
        enabled=bool(entry.enabled),
        kind=entry.kind,
        precludes=list(entry.precludes),
        horizon_s=int(entry.horizon_s),
        after=list(entry.after),
        timezone=TIMEZONE,
        description=entry.description,
        runner=entry.runner,
    )
    for c in claims_for(entry.kind):
        hint.claims.add(leaf=str(c["leaf"]), gpu=int(c["gpu"]))
    for k, v in entry.postures.items():
        hint.postures[str(k)] = str(v)
    return hint


def schedule_hints() -> list[Any]:
    """ServerQuery kind=SCHEDULES: the whole catalogue, every field filled."""
    return [to_hint(e) for e in WORKLOAD_CATALOG]


def as_dict(entry: WorkloadEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "task_type": entry.task_type,
        "payload": dict(entry.payload),
        "gate_sql": entry.gate_sql,
        "cron": entry.cron,
        "timezone": TIMEZONE,
        "runner": entry.runner,
        "horizon_s": int(entry.horizon_s),
        "after": list(entry.after),
        "claims": claims_for(entry.kind),
        "enabled": bool(entry.enabled),
        "source": entry.source,
        "airflow_dag_id": airflow_dag_id(entry),
        "pg_cron_job": entry.pg_cron_job,
        "pg_cron_active": bool(entry.pg_cron_active),
        "description": entry.description,
    }


def payload_json(entry: WorkloadEntry) -> str:
    return json.dumps(entry.payload, sort_keys=True)
