"""Pure-function tests for Nautilus trigger evaluation.

Includes a replay of the pre-e0ae0be reconciliation kill loop (T2) —
detected from the efficacy ledger itself.
"""

from datetime import datetime, timedelta, timezone

from gaius.engine.services.nautilus_triggers import (
    T1_SERVING_DESYNC,
    T2_KILL_LOOP,
    T3_OBJECTIVE_STALE,
    T4_FROZEN_INCIDENT,
    T5_WATCHDOG_STORM,
    T6_DISCREDITED_PROBE,
    NautilusConfig,
    NautilusSnapshot,
    evaluate_triggers,
)

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
CFG = NautilusConfig()


def _fires(firings, trigger):
    return [f for f in firings if f.trigger == trigger]


class TestQuietSystem:
    def test_no_firings_when_green(self):
        snap = NautilusSnapshot(
            now=NOW,
            facade_dark_for_s=None,
            objectives={
                "site_freshness": ("pass", NOW - timedelta(hours=1), timedelta(hours=6))
            },
        )
        assert evaluate_triggers(snap, CFG) == []


class TestT1ServingDesync:
    def test_dark_facade_past_net_fires(self):
        snap = NautilusSnapshot(now=NOW, facade_dark_for_s=901.0)
        assert len(_fires(evaluate_triggers(snap, CFG), T1_SERVING_DESYNC)) == 1

    def test_dark_facade_within_net_holds(self):
        # progress doctrine: a load window is not an outage
        snap = NautilusSnapshot(now=NOW, facade_dark_for_s=600.0)
        assert _fires(evaluate_triggers(snap, CFG), T1_SERVING_DESYNC) == []


class TestT2KillLoop:
    def test_pre_e0ae0be_replay(self):
        # The 2026-09-01 04:20-04:30 pattern: 3 remediations in 10 min.
        snap = NautilusSnapshot(
            now=NOW,
            side_effect_forecasts=[
                ("thinking", NOW - timedelta(minutes=10), "remediate"),
                ("thinking", NOW - timedelta(minutes=5), "remediate"),
                ("thinking", NOW - timedelta(minutes=1), "remediate"),
            ],
        )
        firings = _fires(evaluate_triggers(snap, CFG), T2_KILL_LOOP)
        assert len(firings) == 1
        assert firings[0].scope == "endpoint:thinking"

    def test_two_remediations_hold(self):
        snap = NautilusSnapshot(
            now=NOW,
            side_effect_forecasts=[
                ("thinking", NOW - timedelta(minutes=10), "remediate"),
                ("thinking", NOW - timedelta(minutes=1), "remediate"),
            ],
        )
        assert _fires(evaluate_triggers(snap, CFG), T2_KILL_LOOP) == []

    def test_skip_remediation_flaps_do_not_count(self):
        snap = NautilusSnapshot(
            now=NOW,
            side_effect_forecasts=[
                ("thinking", NOW - timedelta(minutes=i), "skip_remediation")
                for i in range(1, 6)
            ],
        )
        assert _fires(evaluate_triggers(snap, CFG), T2_KILL_LOOP) == []

    def test_old_remediations_age_out(self):
        snap = NautilusSnapshot(
            now=NOW,
            side_effect_forecasts=[
                ("thinking", NOW - timedelta(hours=2), "remediate"),
                ("thinking", NOW - timedelta(minutes=5), "remediate"),
                ("thinking", NOW - timedelta(minutes=1), "remediate"),
            ],
        )
        assert _fires(evaluate_triggers(snap, CFG), T2_KILL_LOOP) == []


class TestT3ObjectiveStale:
    def test_failed_objective_fires(self):
        snap = NautilusSnapshot(
            now=NOW,
            objectives={"site_freshness": ("fail", NOW, timedelta(hours=6))},
        )
        assert len(_fires(evaluate_triggers(snap, CFG), T3_OBJECTIVE_STALE)) == 1

    def test_never_verified_fires(self):
        snap = NautilusSnapshot(
            now=NOW,
            objectives={"site_freshness": (None, None, timedelta(hours=6))},
        )
        assert len(_fires(evaluate_triggers(snap, CFG), T3_OBJECTIVE_STALE)) == 1

    def test_overdue_verification_fires(self):
        snap = NautilusSnapshot(
            now=NOW,
            objectives={
                "site_freshness": ("pass", NOW - timedelta(hours=13), timedelta(hours=6))
            },
        )
        assert len(_fires(evaluate_triggers(snap, CFG), T3_OBJECTIVE_STALE)) == 1

    def test_fresh_pass_holds(self):
        snap = NautilusSnapshot(
            now=NOW,
            objectives={
                "site_freshness": ("pass", NOW - timedelta(hours=5), timedelta(hours=6))
            },
        )
        assert _fires(evaluate_triggers(snap, CFG), T3_OBJECTIVE_STALE) == []


class TestT4FrozenIncident:
    def test_open_stale_sequence_fires(self):
        snap = NautilusSnapshot(
            now=NOW,
            healing_sequences=[("seq1", "thinking", NOW - timedelta(hours=3), True)],
        )
        assert len(_fires(evaluate_triggers(snap, CFG), T4_FROZEN_INCIDENT)) == 1

    def test_closed_sequence_holds(self):
        snap = NautilusSnapshot(
            now=NOW,
            healing_sequences=[("seq1", "thinking", NOW - timedelta(hours=3), False)],
        )
        assert _fires(evaluate_triggers(snap, CFG), T4_FROZEN_INCIDENT) == []


class TestT5WatchdogStorm:
    def test_repeated_resets_fire(self):
        snap = NautilusSnapshot(
            now=NOW,
            watchdog_resets=[
                ("publish_cards", NOW - timedelta(hours=10)),
                ("publish_cards", NOW - timedelta(hours=2)),
            ],
        )
        firings = _fires(evaluate_triggers(snap, CFG), T5_WATCHDOG_STORM)
        assert len(firings) == 1
        assert firings[0].scope == "task:publish_cards"

    def test_single_reset_holds(self):
        snap = NautilusSnapshot(
            now=NOW,
            watchdog_resets=[("publish_cards", NOW - timedelta(hours=2))],
        )
        assert _fires(evaluate_triggers(snap, CFG), T5_WATCHDOG_STORM) == []


class TestT6DiscreditedProbe:
    def test_bad_brier_with_support_fires(self):
        snap = NautilusSnapshot(
            now=NOW,
            ledger_report=[
                {
                    "observer": "probe:x",
                    "call_site": "y",
                    "momentum_bucket": "deep",
                    "brier": 0.4,
                    "resolved": 12,
                    "n": 15,
                }
            ],
        )
        assert len(_fires(evaluate_triggers(snap, CFG), T6_DISCREDITED_PROBE)) == 1

    def test_bad_brier_low_support_holds(self):
        snap = NautilusSnapshot(
            now=NOW,
            ledger_report=[
                {
                    "observer": "probe:x",
                    "call_site": "y",
                    "momentum_bucket": "deep",
                    "brier": 0.5,
                    "resolved": 3,
                    "n": 3,
                }
            ],
        )
        assert _fires(evaluate_triggers(snap, CFG), T6_DISCREDITED_PROBE) == []

    def test_uncalibrated_none_brier_holds(self):
        snap = NautilusSnapshot(
            now=NOW,
            ledger_report=[
                {
                    "observer": "probe:x",
                    "call_site": "y",
                    "momentum_bucket": "cold",
                    "brier": None,
                    "resolved": 0,
                    "n": 20,
                }
            ],
        )
        assert _fires(evaluate_triggers(snap, CFG), T6_DISCREDITED_PROBE) == []
