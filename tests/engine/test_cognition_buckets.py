"""Bucket policy, tiling, and folding for the scale-aware Cognition surface."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gaius.engine.services.cognition_buckets import (
    GURU_BADBUCKET,
    GURU_BADRANGE,
    GURU_BADWINDOWSTR,
    MAX_BUCKETS,
    BucketWindow,
    bucket_index,
    build_buckets,
    fold_rows,
    parse_window,
    resolve_bucket,
    resolve_range,
)

NOW = datetime(2026, 8, 30, 22, 30, tzinfo=timezone.utc)


class TestParseWindow:
    def test_grammar(self):
        assert parse_window("24h") == timedelta(hours=24)
        assert parse_window("7d") == timedelta(days=7)
        assert parse_window("365D") == timedelta(days=365)
        assert parse_window("all") is None

    def test_rejects(self):
        for bad in ("", "x", "7", "0h", "9999d", "-1d"):
            with pytest.raises(ValueError, match="COG.00000034"):
                parse_window(bad)
        assert "BADWINDOWSTR" in GURU_BADWINDOWSTR


class TestResolveRange:
    def test_precedence_from_to_wins(self):
        start, end = resolve_range(
            NOW,
            window_days=7,
            window="24h",
            from_ms=1_000_000,
            to_ms=2_000_000,
        )
        assert start == datetime.fromtimestamp(1000, tz=timezone.utc)
        assert end == datetime.fromtimestamp(2000, tz=timezone.utc)

    def test_from_to_requires_both_ordered(self):
        with pytest.raises(ValueError, match="COG.00000033"):
            resolve_range(NOW, from_ms=5, to_ms=0)
        with pytest.raises(ValueError, match="COG.00000033"):
            resolve_range(NOW, from_ms=9, to_ms=9)
        assert "BADRANGE" in GURU_BADRANGE

    def test_window_string(self):
        start, end = resolve_range(NOW, window="7d", window_days=365)
        assert end == NOW
        assert end - start == timedelta(days=7)

    def test_all_uses_oldest(self):
        oldest = NOW - timedelta(days=100)
        start, end = resolve_range(NOW, window="all", oldest=oldest)
        assert (start, end) == (oldest, NOW)

    def test_all_without_oldest_falls_back(self):
        start, end = resolve_range(NOW, window="all")
        assert end - start == timedelta(days=365)

    def test_legacy_window_days(self):
        start, end = resolve_range(NOW, window_days=30)
        assert end - start == timedelta(days=30)


class TestResolveBucket:
    def test_auto_policy_boundaries(self):
        def unit(hours: float) -> str:
            return resolve_bucket(NOW - timedelta(hours=hours), NOW)

        assert unit(24) == "hour"
        assert unit(48) == "hour"
        assert unit(49) == "6h"
        assert unit(14 * 24) == "6h"
        assert unit(15 * 24) == "day"
        assert unit(180 * 24) == "day"
        assert unit(181 * 24) == "week"
        assert unit(1100 * 24) == "week"
        assert unit(1101 * 24) == "month"

    def test_override_allowlist(self):
        assert resolve_bucket(NOW - timedelta(days=2), NOW, "day") == "day"
        with pytest.raises(ValueError, match="COG.00000032"):
            resolve_bucket(NOW - timedelta(days=2), NOW, "5m")
        assert "BADBUCKET" in GURU_BADBUCKET

    def test_degrades_instead_of_failing(self):
        # hour buckets over 3660 days would be ~87k — degrade coarser.
        unit = resolve_bucket(NOW - timedelta(days=3660), NOW, "hour")
        assert unit in ("day", "week", "month")
        start = NOW - timedelta(days=3660)
        assert len(build_buckets(start, NOW, unit)) <= MAX_BUCKETS


class TestBuildBuckets:
    def test_fixed_hour_clips_last(self):
        start = NOW - timedelta(hours=2, minutes=30)
        buckets = build_buckets(start, NOW, "hour")
        assert len(buckets) == 3
        assert buckets[0].start == start
        assert buckets[-1].end == NOW
        assert (buckets[-1].end - buckets[-1].start) == timedelta(minutes=30)

    def test_day_calendar_alignment_and_clipping(self):
        start = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)
        buckets = build_buckets(start, end, "day")
        assert [b.start.hour for b in buckets] == [15, 0, 0]  # first clipped up
        assert buckets[1].start == datetime(2026, 8, 29, tzinfo=timezone.utc)
        assert buckets[-1].end == end  # last clipped down

    def test_week_anchors_iso_monday(self):
        # 2026-08-30 is a Sunday; the containing ISO week starts Mon 08-24.
        start = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 8, tzinfo=timezone.utc)
        buckets = build_buckets(start, end, "week")
        assert buckets[0].start == start  # clipped to range
        assert buckets[1].start == datetime(2026, 8, 31, tzinfo=timezone.utc)  # Monday
        assert buckets[1].start.weekday() == 0

    def test_month_walk(self):
        start = datetime(2026, 1, 31, tzinfo=timezone.utc)
        end = datetime(2026, 4, 2, tzinfo=timezone.utc)
        buckets = build_buckets(start, end, "month")
        assert [b.start.month for b in buckets] == [1, 2, 3, 4]
        assert buckets[1].start == datetime(2026, 2, 1, tzinfo=timezone.utc)
        assert buckets[-1].end == end

    def test_empty_range(self):
        assert build_buckets(NOW, NOW, "day") == []


class TestFold:
    def test_bucket_index_half_open(self):
        buckets = build_buckets(NOW - timedelta(hours=3), NOW, "hour")
        assert bucket_index(buckets, NOW - timedelta(hours=3)) == 0
        assert bucket_index(buckets, NOW - timedelta(hours=2)) == 1
        assert bucket_index(buckets, NOW) == -1  # end is exclusive
        assert bucket_index(buckets, NOW - timedelta(hours=9)) == -1

    def test_fold_zero_fills_and_sums(self):
        buckets = build_buckets(NOW - timedelta(hours=3), NOW, "hour")
        rows = [
            (NOW - timedelta(hours=2, minutes=30), {"thoughts": 2, "salience_max": 0.4}),
            (NOW - timedelta(hours=2, minutes=10), {"thoughts": 1, "salience_max": 0.9}),
            (NOW + timedelta(hours=1), {"thoughts": 99}),  # outside → dropped
        ]
        folded = fold_rows(buckets, rows)
        assert len(folded) == 3
        assert folded[0] == {"thoughts": 3, "salience_max": 0.9}
        assert folded[1] == {}
        assert folded[2] == {}


class TestUpstreamParity:
    """Spot-checks mirroring wxs-agentsview query.go semantics (MIT port)."""

    def test_half_open_windows_tile_exactly(self):
        start = NOW - timedelta(days=10)
        buckets = build_buckets(start, NOW, "day")
        for prev, cur in zip(buckets, buckets[1:]):
            assert prev.end == cur.start
        assert buckets[0].start == start
        assert buckets[-1].end == NOW
