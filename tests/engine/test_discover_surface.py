"""Discover query / window parse — no database."""

from datetime import datetime, timedelta, timezone

import pytest

from gaius.engine.services.discover_surface import (
    DiscoverError,
    auto_interval,
    next_cron,
    parse_query,
    parse_window,
    rolling_ma,
    _window_token,
)


def test_parse_window() -> None:
    assert parse_window("36h") == timedelta(hours=36)
    assert parse_window("7d") == timedelta(days=7)
    assert parse_window("15m") == timedelta(minutes=15)
    with pytest.raises(DiscoverError, match="DI.00000002"):
        parse_window("nope")


def test_parse_query_collects_all_feature_pins() -> None:
    q = parse_query("feature:0:3235 feature:11:8224")
    assert q.features == [(0, 3235), (11, 8224)]


def test_parse_query_kv_and_text() -> None:
    q = parse_query("stream:inflow source:arxiv_cs_dc barrier", ["12:4412"])
    assert q.stream == "inflow"
    assert q.source == "arxiv_cs_dc"
    assert q.features == [(12, 4412)]
    assert q.text == "barrier"


def test_bad_feature_pin() -> None:
    with pytest.raises(DiscoverError, match="DI.00000005"):
        parse_query("feature:nope")


def test_auto_interval() -> None:
    assert auto_interval(timedelta(hours=1)) == "minute"
    assert auto_interval(timedelta(hours=36)) == "hour"
    assert auto_interval(timedelta(days=14)) == "day"


def test_rolling_ma_trailing() -> None:
    assert rolling_ma([2, 4, 6, 8], 2) == [2.0, 3.0, 5.0, 7.0]


def test_window_tokens() -> None:
    assert _window_token("") == "36h"
    assert _window_token("salience") == "36h"
    assert _window_token("24h") == "24h"
    assert _window_token("36h") == "36h"
    assert parse_window("24h") == timedelta(hours=24)


def test_landing_strip_waiting_hhmmss() -> None:
    from datetime import datetime, timezone, timedelta
    from gaius.engine.services.discover_landing import landing_strip, next_waiting_at

    now = datetime(2026, 8, 20, 12, 0, 1, tzinfo=timezone.utc)
    nxt = next_waiting_at(now)
    assert nxt > now
    assert nxt - now < timedelta(minutes=6)
    strip = landing_strip()
    assert strip.waiting_at
    assert strip.updating is False
    assert strip.workflows >= 0


def test_remember_and_peek_landing() -> None:
    from gaius.engine.services.discover_landing import (
        peek_landing,
        remember_landing,
        surface_from_landing_rows,
    )

    rows = [
        {
            "kind": "meta",
            "key": "snapshot",
            "payload": {
                "start_ts": "2026-08-18T12:00:00+00:00",
                "end_ts": "2026-08-20T00:00:00+00:00",
                "last_salience_at": "2026-08-20T00:00:00+00:00",
                "total": 1,
                "refreshed_at": "2026-08-20T00:01:00+00:00",
                "interval": "hour",
                "window": "36h",
            },
        },
        {
            "kind": "doc",
            "key": "1",
            "payload": {
                "id": 1,
                "title": "T",
                "body": "b",
                "fetched_at": "2026-08-19T12:00:00+00:00",
                "url": "",
                "source": "arxiv",
            },
        },
    ]
    snap = surface_from_landing_rows(rows, limit=50, gpu_rows=[], episode=None)
    remember_landing(snap)
    got = peek_landing()
    assert got is not None
    assert got.total == 1
    assert got.docs[0].title == "T"


def test_uses_landing_mv_default_only() -> None:
    from gaius.engine.services.discover_landing import uses_landing_mv
    from gaius.engine.services.discover_surface import parse_query

    empty = parse_query("")
    assert uses_landing_mv("36h", empty) is True
    assert uses_landing_mv("", empty) is True
    assert uses_landing_mv("salience", empty) is True
    assert uses_landing_mv("1h", empty) is False
    assert uses_landing_mv("7d", empty) is False
    assert uses_landing_mv("36h", parse_query("feature:11:8224")) is False
    assert uses_landing_mv("36h", parse_query("source:arxiv_cs_dc")) is False
    assert uses_landing_mv("36h", parse_query("barrier")) is False
    assert uses_landing_mv("36h", empty, from_ts="2026-01-01T00:00:00+00:00", to_ts="2026-01-02T00:00:00+00:00") is False
    assert uses_landing_mv("36h", parse_query("stream:inflow")) is True
    assert uses_landing_mv("36h", parse_query("stream:other")) is False


def test_surface_from_landing_rows_json_string_payload() -> None:
    from gaius.engine.services.discover_landing import surface_from_landing_rows
    from gaius.engine.services.discover_surface import DiscoverEpisode

    rows = [
        {
            "kind": "meta",
            "key": "snapshot",
            "payload": (
                '{"start_ts":"2026-08-18T12:00:00+00:00",'
                '"end_ts":"2026-08-20T00:00:00+00:00",'
                '"last_salience_at":"2026-08-20T00:00:00+00:00",'
                '"total":1,"refreshed_at":"2026-08-20T00:01:00+00:00",'
                '"interval":"hour","window":"36h"}'
            ),
        },
        {
            "kind": "doc",
            "key": "1",
            "payload": '{"id":1,"title":"T","body":"b","fetched_at":"2026-08-19T12:00:00+00:00","url":"","source":"arxiv"}',
        },
    ]
    ep = DiscoverEpisode(kind="feed_check", at="x", eta_s=1, label="Feed")
    snap = surface_from_landing_rows(rows, limit=50, gpu_rows=[], episode=ep)
    assert snap.total == 1
    assert snap.docs[0].title == "T"


def test_surface_from_landing_rows() -> None:
    from gaius.engine.services.discover_landing import surface_from_landing_rows
    from gaius.engine.services.discover_surface import DiscoverEpisode

    rows = [
        {
            "kind": "meta",
            "key": "snapshot",
            "payload": {
                "start_ts": "2026-08-18T12:00:00+00:00",
                "end_ts": "2026-08-20T00:00:00+00:00",
                "last_salience_at": "2026-08-20T00:00:00+00:00",
                "total": 2,
                "refreshed_at": "2026-08-20T00:01:00+00:00",
                "interval": "hour",
                "window": "36h",
            },
        },
        {
            "kind": "doc",
            "key": "9",
            "payload": {
                "id": 9,
                "title": "Later",
                "body": "b2",
                "fetched_at": "2026-08-19T12:00:00+00:00",
                "url": "https://example.test/2",
                "source": "arxiv_cs_dc",
            },
        },
        {
            "kind": "doc",
            "key": "8",
            "payload": {
                "id": 8,
                "title": "Earlier",
                "body": "b1",
                "fetched_at": "2026-08-19T01:00:00+00:00",
                "url": "",
                "source": "arxiv_cs_dc",
            },
        },
        {"kind": "src", "key": "arxiv_cs_dc", "payload": {"n": 2}},
        {
            "kind": "bucket",
            "key": "2026-08-19T12:00:00+00:00",
            "payload": {"t": "2026-08-19T12:00:00+00:00", "n": 2, "sal": 1.5},
        },
    ]
    ep = DiscoverEpisode(kind="feed_check", at="2026-08-20T00:17:00+00:00", eta_s=16, label="Feed")
    snap = surface_from_landing_rows(rows, limit=50, gpu_rows=[], episode=ep)
    assert snap.window == "36h"
    assert snap.total == 2
    assert snap.clock == "salience"
    assert snap.scraped_at == "2026-08-20T00:01:00+00:00"
    assert [d.title for d in snap.docs] == ["Later", "Earlier"]
    assert snap.docs[0].id == "inflow:9"
    assert any(f.kind == "source" and f.key == "arxiv_cs_dc" and f.count == 2 for f in snap.facets)
    assert snap.interval == "hour"
    assert len(snap.buckets) > 0


def test_surface_from_landing_rows_requires_meta() -> None:
    from gaius.engine.services.discover_landing import surface_from_landing_rows
    from gaius.engine.services.discover_surface import DiscoverError

    with pytest.raises(DiscoverError, match="DI.00000007"):
        surface_from_landing_rows([], limit=50, gpu_rows=[], episode=None)


def test_next_cron_patterns() -> None:
    now = datetime(2026, 8, 18, 12, 44, tzinfo=timezone.utc)
    assert next_cron(now, "*/5", "*") == datetime(2026, 8, 18, 12, 45, tzinfo=timezone.utc)
    assert next_cron(now, "17", "*/4") == datetime(2026, 8, 18, 16, 17, tzinfo=timezone.utc)
