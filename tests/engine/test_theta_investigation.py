"""An investigation is provoked by inklings. It is not a shorter list of them."""

from __future__ import annotations

import pytest


def _week() -> list[dict]:
    rows = []
    for _ in range(6):
        rows.append(
            {
                "title": "What must agents preserve?",
                "summary": "preserve the same question",
                "thought_type": "pattern",
                "salience": 0.99,
            }
        )
    for i in range(8):
        rows.append(
            {
                "title": f"Temporal control plane {i}",
                "summary": "temporal ordering hypothesis",
                "thought_type": "connection",
                "salience": 0.7,
            }
        )
    for i in range(5):
        rows.append(
            {
                "title": f"Billing regression sensor {i}",
                "summary": "billing sees regressions",
                "thought_type": "curiosity",
                "salience": 0.6,
            }
        )
    rows.append(
        {
            "title": "Already written",
            "summary": "prior well",
            "content": "cloudera suggests a connection",
            "thought_type": "consolidation",
            "salience": 0.9,
        }
    )
    rows.append(
        {
            "title": "KV cache becomes physical",
            "summary": "replicated cache correctness",
            "thought_type": "pattern",
            "salience": 0.98,
        }
    )
    for row in rows:
        row["content"] = "cloudera suggests a connection in every body"
    return rows


def _clouds() -> list[dict]:
    from gaius.engine.services.theta_investigation import notice_inklings

    return [item for item in notice_inklings(_week()) if item["kind"] == "cloud"]


def test_a_paraphrase_cloud_outranks_a_repeated_sentence() -> None:
    from gaius.engine.services.theta_investigation import notice_inklings

    inklings = notice_inklings(_week())
    clouds = [item for item in inklings if item["kind"] == "cloud"]
    temporal = next(item for item in clouds if item["name"] == "temporal")
    preserve = next(item for item in clouds if item["name"] == "preserve")
    assert temporal["n"] > preserve["n"]
    assert temporal["titles"] > 1
    assert preserve["titles"] == 1
    assert all(item["name"] not in {"Already written", "cloudera", "suggest"} for item in inklings)
    singles = [item for item in inklings if item["kind"] == "inkling"]
    assert any("KV cache" in item["name"] for item in singles)


def test_iso_week_window_is_monday_to_monday() -> None:
    from datetime import datetime, timezone

    from gaius.engine.services.theta_investigation import slice_window

    start, end = slice_window("2026-W38")
    assert start == datetime(2026, 9, 14, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 21, tzinfo=timezone.utc)
    assert slice_window("not-a-week") is None


def test_prompt_treats_thoughts_as_provocation_and_classes_as_not_roles() -> None:
    from gaius.engine.services.theta_investigation import investigation_prompt
    from gaius.engine.services.theta_understanding import SYSTEM_PROMPT

    prompt = investigation_prompt(
        "2026-W38",
        _clouds(),
        [("DataInput", 59)],
        [{"slice_id": "2026-W37", "title": "Prior", "carry": "KNOWN: earlier", "well": "prior well"}],
        [{"seed": "billing", "title": "Billable Actions", "summary": "usage-based billing"}],
    )
    assert "do not mint" in SYSTEM_PROMPT.lower()
    assert "subclass" in SYSTEM_PROMPT.lower()
    assert "not an outline" in prompt or "Do not shorten" in prompt
    assert "not a role to assign" in prompt
    assert "2026-W37" in prompt
    assert "Billable Actions" in prompt
    assert "DataInput (59)" in prompt
    assert "APERTURE:" not in prompt
    assert "temporal" in prompt


def test_a_single_cloud_essay_does_not_hold_and_a_distinction_does() -> None:
    from gaius.engine.services.theta_investigation import investigation_holds

    inklings = _clouds()
    well = "temporal and billing are not one mechanism. " + ("distinction " * 80)
    carry = (
        "KNOWN: Temporal ordering and billing telemetry were separate reaches.\n"
        "STOP: Do not treat the repeated preserve sentence as the week's subject.\n"
        "OPEN: Whether temporal ordering is a control plane is unresolved."
    )
    held = {
        "title": "Two reaches",
        "content": well,
        "summary": carry,
        "known": "Temporal ordering and billing telemetry were separate reaches.",
        "stop": "Do not treat the repeated preserve sentence as the week's subject.",
        "open": "Whether temporal ordering is a control plane is unresolved.",
    }
    assert investigation_holds(held, inklings) is True

    one_cloud = dict(held)
    one_cloud["content"] = "Only the temporal hypothesis, restated. " + ("temporal " * 80)
    assert investigation_holds(one_cloud, inklings) is False

    plural = dict(held)
    plural["content"] = "temporals and billings are not one mechanism. " + ("distinction " * 80)
    assert investigation_holds(plural, inklings) is True

    claimed = dict(held)
    claimed["content"] = well + " Billing is a subclass of temporal ordering."
    assert investigation_holds(claimed, inklings) is False

    denied = dict(held)
    denied["content"] = well + " These associations do not assert subclass or subsumption."
    assert investigation_holds(denied, inklings) is True

    huge = dict(held)
    huge["summary"] = carry + (" more" * 400)
    huge["known"] = huge["summary"]
    assert investigation_holds(huge, inklings) is False


@pytest.mark.asyncio
async def test_distill_reads_the_well_not_the_thought_list() -> None:
    from gaius.engine.services.theta_investigation import investigate_week

    class _Client:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def call(self, *, service, action, params):
            self.prompts.append(params["prompt"])
            if "standing implication" in params["prompt"]:
                return {
                    "text": (
                        "KNOWN: Temporal ordering and billing telemetry were separate reaches.\n"
                        "STOP: Do not treat a repeated preserve sentence as the subject.\n"
                        "OPEN: Whether temporal ordering is a control plane is unresolved.\n"
                    ),
                    "tokens_used": 4,
                    "model": "m",
                }
            well = "temporal and billing are different reaches. " + ("distinction " * 90)
            return {"text": f"TITLE: Two reaches\nWELL: {well}", "tokens_used": 11, "model": "m"}

    client = _Client()
    record, _raw, tokens, model = await investigate_week(
        client, "2026-W38", _clouds(), [("DataInput", 59)], [], []
    )
    assert record is not None
    assert record["summary"].startswith("KNOWN:")
    assert "STOP:" in record["summary"]
    assert tokens == 15
    assert model == "m"
    assert len(client.prompts) == 2
    assert "What must agents preserve?" in client.prompts[0]
    assert "What must agents preserve?" not in client.prompts[1]
    assert "temporal and billing are different reaches" in client.prompts[1]


@pytest.mark.asyncio
async def test_a_bad_carry_is_redistilled_without_a_second_investigation() -> None:
    from gaius.engine.services.theta_investigation import investigate_week

    class _Client:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def call(self, *, service, action, params):
            self.prompts.append(params["prompt"])
            if "standing implication" not in params["prompt"]:
                well = "temporal and billing are different reaches. " + ("distinction " * 90)
                return {"text": f"TITLE: Two reaches\nWELL: {well}", "tokens_used": 11, "model": "m"}
            if self.prompts.count(params["prompt"]) == 1 and sum(
                "standing implication" in item for item in self.prompts
            ) == 1:
                return {
                    "text": "KNOWN: short.\nSTOP: short.\nOPEN: short.\n",
                    "tokens_used": 2,
                    "model": "m",
                }
            return {
                "text": (
                    "KNOWN: Temporal ordering and billing telemetry were separate reaches.\n"
                    "STOP: Do not treat a repeated preserve sentence as the subject.\n"
                    "OPEN: Whether temporal ordering is a control plane is unresolved.\n"
                ),
                "tokens_used": 4,
                "model": "m",
            }

    client = _Client()
    record, raw, tokens, model = await investigate_week(
        client, "2026-W38", _clouds(), [], [], []
    )
    assert record is not None
    assert record["summary"].startswith("KNOWN: Temporal")
    assert tokens == 17
    assert model == "m"
    assert "TITLE: Two reaches" in raw
    investigations = [item for item in client.prompts if "standing implication" not in item]
    distillations = [item for item in client.prompts if "standing implication" in item]
    assert len(investigations) == 1
    assert len(distillations) == 2
    assert "What must agents preserve?" in investigations[0]
    assert all("What must agents preserve?" not in item for item in distillations)


@pytest.mark.asyncio
async def test_prior_wells_are_earlier_iso_weeks_only() -> None:
    from gaius.engine.services.theta_investigation import load_prior_wells

    class _Conn:
        async def fetch(self, sql, *args):
            assert "consolidation" in sql
            return [
                {"title": "later", "summary": "KNOWN: w39", "content": "w39 well", "slice_id": "2026-W39"},
                {"title": "this", "summary": "KNOWN: w38", "content": "w38 well", "slice_id": "2026-W38"},
                {"title": "earlier", "summary": "KNOWN: w37", "content": "w37 well " * 20, "slice_id": "2026-W37"},
            ]

    prior = await load_prior_wells(_Conn(), "2026-W38")
    assert [item["slice_id"] for item in prior] == ["2026-W37"]


@pytest.mark.asyncio
async def test_external_sources_are_looked_up_inside_the_week() -> None:
    from datetime import datetime, timezone

    from gaius.engine.services.theta_investigation import load_external_sources, notice_inklings

    class _Conn:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        async def fetch(self, sql, *args):
            self.calls.append(args)
            assert "fetched_at" in sql
            seed = args[2]
            assert seed.startswith("%") and seed.endswith("%")
            assert " " not in seed
            return [{"title": f"source {seed}", "summary": "abstract"}]

    conn = _Conn()
    sources = await load_external_sources(conn, "2026-W38", notice_inklings(_week()))
    assert sources
    start = conn.calls[0][0]
    assert start == datetime(2026, 9, 14, tzinfo=timezone.utc)
    assert all("%" in call[2] and " " not in call[2].strip("%") for call in conn.calls)
