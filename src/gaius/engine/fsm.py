"""Gaius FSM: logical position derivation over existing ground truth.

The Gaius FSM is the scheduled-task classes + Metaflow workflows (the DAG
that produces core objectives) plus the endpoint/admission lifecycles that
serve them. This module makes that implicit FSM explicit as a DERIVED
position — a pure function over state that already exists (scheduled_tasks
timestamps, reconcile_state() endpoint vocabulary, YK admission phases) —
rather than a second runtime state machine that could drift from reality.

Every probe/timeout/heuristic verdict recorded in the efficacy ledger is
stamped with an ``FsmPosition`` by its CALLER at each call site: one probe
function may have many call sites, and each call site gets its own ledger
rows so scoring is truly (probe × call-site × FSM state)-aware.

Momentum is the state axis for Brier bucketing (the analog of Synth's
``items_depth``): a count of corroborating evidence in the current scope.
A FAIL verdict at momentum 40 (twenty minutes of green probes on a serving
endpoint) deserves a grain of salt; the same verdict at momentum 0 during
STARTING does not. Raw counts are stored; bucketing happens at scoring
time only (see ``momentum_bucket``).

Style precedent: ``gaius.engine.resources.reconciliation.reconcile_state``
— pure, table-driven, exhaustively unit-testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

# Task lifecycle vocabulary — derived from the three nullable timestamps
# plus `error` on scheduled_tasks. Works identically for BOTH claim
# implementations (SQL pick_up_task() and the processor's inline UPDATE)
# because it reads timestamps, never claim mechanics.
TASK_QUEUED = "QUEUED"
TASK_CLAIMED = "CLAIMED"
TASK_DONE_OK = "DONE_OK"
TASK_DONE_ERR = "DONE_ERR"
TASK_RESET_BY_WATCHDOG = "RESET_BY_WATCHDOG"

# YK admission phases (sentinel_claim vocabulary).
ADMIT_PENDING = "PENDING"
ADMIT_ADMITTED = "ADMITTED"
ADMIT_NOTADMITTED = "NOTADMITTED"
ADMIT_RETIRED = "RETIRED"


@dataclass(frozen=True)
class FsmPosition:
    """A logical position in the Gaius FSM. All axes nullable — callers
    fill only what they know at their call site."""

    task_class: str | None = None      # scheduled_tasks.task_type
    task_id: int | None = None
    task_lifecycle: str | None = None  # TASK_* vocabulary above
    flow_type: str | None = None       # Metaflow flow name (runs_v3)
    flow_run_id: str | None = None
    flow_step: str | None = None
    endpoint: str | None = None
    endpoint_state: str | None = None  # reconcile_state() vocabulary
    admission_phase: str | None = None # ADMIT_* vocabulary above
    momentum: int | None = None        # raw corroboration count

    def to_columns(self) -> dict[str, Any]:
        """Column dict for the probe_forecasts stamp (keys match schema)."""
        return asdict(self)


def task_lifecycle(
    scheduled_for: datetime | None,
    picked_up_at: datetime | None,
    completed_at: datetime | None,
    error: str | None,
) -> str:
    """Derive the task lifecycle state from scheduled_tasks columns.

    RESET_BY_WATCHDOG is the watchdog's signature: it nulls picked_up_at
    and writes an ``error`` beginning 'reset by watchdog:' on a row that
    never completed. DONE_ERR covers both handler failures (completed_at
    set, error set) and spawn failures recorded without completion.
    """
    if error and error.startswith("reset by watchdog:") and picked_up_at is None:
        return TASK_RESET_BY_WATCHDOG
    if completed_at is not None:
        return TASK_DONE_ERR if error else TASK_DONE_OK
    if error:
        return TASK_DONE_ERR
    if picked_up_at is not None:
        return TASK_CLAIMED
    return TASK_QUEUED


def position_for_task(row: dict[str, Any] | Any, momentum: int | None = None) -> FsmPosition:
    """Position for a scheduled_tasks row (dict or asyncpg Record)."""
    get = row.get if hasattr(row, "get") else lambda k, d=None: getattr(row, k, d)
    return FsmPosition(
        task_class=get("task_type"),
        task_id=get("id"),
        task_lifecycle=task_lifecycle(
            get("scheduled_for"),
            get("picked_up_at"),
            get("completed_at"),
            get("error"),
        ),
        momentum=momentum,
    )


def position_for_endpoint(
    endpoint: str,
    endpoint_state: str | None,
    momentum: int | None = None,
) -> FsmPosition:
    """Position for an endpoint-scope probe (reconciliation family)."""
    return FsmPosition(
        endpoint=endpoint,
        endpoint_state=endpoint_state,
        momentum=momentum,
    )


def position_for_admission(
    kind: str,
    admission_phase: str,
    momentum: int | None = None,
) -> FsmPosition:
    """Position for a YK admission-scope probe (sentinel_claim family)."""
    return FsmPosition(
        task_class=kind,
        admission_phase=admission_phase,
        momentum=momentum,
    )


def position_for_flow(
    flow_type: str,
    flow_run_id: str | None = None,
    flow_step: str | None = None,
    momentum: int | None = None,
) -> FsmPosition:
    """Position for a Metaflow-scope probe/objective."""
    return FsmPosition(
        flow_type=flow_type,
        flow_run_id=flow_run_id,
        flow_step=flow_step,
        momentum=momentum,
    )


def momentum_bucket(momentum: int | None) -> str:
    """Bucket raw momentum for scoring. Bucketing at read time only, so
    thresholds can be re-tuned without rewriting ledger history."""
    if momentum is None:
        return "unknown"
    if momentum <= 0:
        return "cold"
    if momentum <= 2:
        return "warming"
    if momentum <= 9:
        return "rolling"
    return "deep"
