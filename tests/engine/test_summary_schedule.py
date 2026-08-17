"""Schedule catalog parses real INSERT scheduled_tasks commands."""

from gaius.engine.services.summary_schedule import classify_cadence, parse_task_type


def test_parse_select_and_values() -> None:
    assert (
        parse_task_type(
            "INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)\n"
            "      SELECT 'board_reindex', '{}'::jsonb, 'pg_cron', NOW()"
        )
        == "board_reindex"
    )
    assert (
        parse_task_type(
            "INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)\n"
            "      VALUES ('publish_cards', '{\"count\": 1}', 'pg_cron', NOW())"
        )
        == "publish_cards"
    )
    assert parse_task_type("SELECT archive_stale_content()") == ""


def test_classify_cadence_buckets() -> None:
    assert classify_cadence("* * * * *") == "hourly"
    assert classify_cadence("17 */4 * * *") == "hourly"
    assert classify_cadence("0 * * * *") == "hourly"
    assert classify_cadence("43 0,4,8,12,16,20 * * *") == "hourly"
    assert classify_cadence("0 9 * * *") == "daily"
    assert classify_cadence("0 6,18 * * *") == "daily"
    assert classify_cadence("0 15 * * 1") == "weekly"
    assert classify_cadence("0 3 * * 0") == "weekly"
    assert classify_cadence("0 5 * * 1,4") == "extended"
    assert classify_cadence("0 5 1 1,4,7,10 *") == "extended"
    assert classify_cadence("0 2 1 * *") == "extended"
