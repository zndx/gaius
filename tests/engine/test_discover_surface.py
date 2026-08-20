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


def test_next_cron_patterns() -> None:
    now = datetime(2026, 8, 18, 12, 44, tzinfo=timezone.utc)
    assert next_cron(now, "*/5", "*") == datetime(2026, 8, 18, 12, 45, tzinfo=timezone.utc)
    assert next_cron(now, "17", "*/4") == datetime(2026, 8, 18, 16, 17, tzinfo=timezone.utc)
