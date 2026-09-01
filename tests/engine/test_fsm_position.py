"""Pure-function tests for the Gaius FSM position derivation.

Style precedent: tests/engine/test_reconciliation_fsm.py — table-driven,
no I/O, no mocks of the world.
"""

from datetime import datetime, timezone

from gaius.engine.fsm import (
    ADMIT_NOTADMITTED,
    TASK_CLAIMED,
    TASK_DONE_ERR,
    TASK_DONE_OK,
    TASK_QUEUED,
    TASK_RESET_BY_WATCHDOG,
    FsmPosition,
    momentum_bucket,
    position_for_admission,
    position_for_endpoint,
    position_for_task,
    task_lifecycle,
)

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestTaskLifecycle:
    """The lifecycle is derived from timestamps + error, never claim
    mechanics — identical for both claim implementations."""

    def test_queued(self):
        assert task_lifecycle(NOW, None, None, None) == TASK_QUEUED

    def test_claimed(self):
        assert task_lifecycle(NOW, NOW, None, None) == TASK_CLAIMED

    def test_done_ok(self):
        assert task_lifecycle(NOW, NOW, NOW, None) == TASK_DONE_OK

    def test_done_err_completed(self):
        assert task_lifecycle(NOW, NOW, NOW, "boom") == TASK_DONE_ERR

    def test_done_err_uncompleted_spawn_failure(self):
        # Spawn failures record error without completion
        assert task_lifecycle(NOW, NOW, None, "#YK.00000002.NOTADMITTED x") == TASK_DONE_ERR

    def test_watchdog_reset_signature(self):
        # Watchdog nulls picked_up_at and writes its marker error
        assert (
            task_lifecycle(NOW, None, None, "reset by watchdog: stuck running")
            == TASK_RESET_BY_WATCHDOG
        )

    def test_watchdog_marker_with_claim_is_not_reset(self):
        # Re-claimed after a reset: picked_up_at set again — CLAIMED wins;
        # the historical marker no longer describes the current state.
        assert (
            task_lifecycle(NOW, NOW, None, "reset by watchdog: stuck running")
            == TASK_DONE_ERR
        )


class TestPositionBuilders:
    def test_position_for_task_dict(self):
        pos = position_for_task(
            {
                "task_type": "publish_cards",
                "id": 42,
                "scheduled_for": NOW,
                "picked_up_at": NOW,
                "completed_at": None,
                "error": None,
            },
            momentum=3,
        )
        assert pos.task_class == "publish_cards"
        assert pos.task_id == 42
        assert pos.task_lifecycle == TASK_CLAIMED
        assert pos.momentum == 3
        assert pos.endpoint is None

    def test_position_for_endpoint(self):
        pos = position_for_endpoint("thinking", "UNHEALTHY", momentum=40)
        assert pos.endpoint == "thinking"
        assert pos.endpoint_state == "UNHEALTHY"
        assert pos.momentum == 40
        assert pos.task_class is None

    def test_position_for_admission(self):
        pos = position_for_admission("clt-skos-admit", ADMIT_NOTADMITTED)
        assert pos.task_class == "clt-skos-admit"
        assert pos.admission_phase == ADMIT_NOTADMITTED

    def test_to_columns_keys_match_schema(self):
        cols = FsmPosition().to_columns()
        assert set(cols) == {
            "task_class",
            "task_id",
            "task_lifecycle",
            "flow_type",
            "flow_run_id",
            "flow_step",
            "endpoint",
            "endpoint_state",
            "admission_phase",
            "momentum",
        }


class TestMomentumBucket:
    """Raw counts stored; bucketing at read time only."""

    def test_table(self):
        cases = [
            (None, "unknown"),
            (0, "cold"),
            (1, "warming"),
            (2, "warming"),
            (3, "rolling"),
            (9, "rolling"),
            (10, "deep"),
            (100, "deep"),
        ]
        for momentum, expected in cases:
            assert momentum_bucket(momentum) == expected, momentum
