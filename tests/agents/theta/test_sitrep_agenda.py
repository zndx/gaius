"""Sitrep still offers /agenda init; aggregator writes current/agenda.md."""

from pathlib import Path

from gaius.agents.theta.agenda import AgendaAggregator, parse_agenda_md
from gaius.agents.theta.horizons import Horizon
from gaius.agents.theta.sitrep import PriorityItem, SituationReport
from gaius.agents.theta.agent import ThetaAgent


def test_empty_priorities_offer_agenda_init():
    report = SituationReport(horizon=Horizon.DAY)
    ascii_out = report.to_ascii()
    assert "/agenda init to create" in ascii_out
    assert "not yet available in this deployment" not in ascii_out


def test_overflow_priorities_offer_agenda_list():
    report = SituationReport(
        horizon=Horizon.DAY,
        priorities=[
            PriorityItem(description=f"item-{i}", priority="P2") for i in range(6)
        ],
    )
    ascii_out = report.to_ascii()
    assert "/agenda for full list" in ascii_out


def test_quick_actions_offer_agenda_init():
    agent = object.__new__(ThetaAgent)
    actions = ThetaAgent._generate_quick_actions(
        agent, has_priorities=False, has_thoughts=True, health_ok=True
    )
    cmds = [a.command for a in actions]
    assert "/agenda init" in cmds


def test_init_creates_day_agenda(tmp_path: Path):
    kb = tmp_path / "kb"
    proj = kb / "current" / "projects" / "gaius"
    proj.mkdir(parents=True)
    (proj / "agenda.md").write_text(
        "# Gaius\n\n- [ ] P0: Ship sitrep @today\n- [ ] P2: Backlog item\n",
        encoding="utf-8",
    )
    agg = AgendaAggregator(kb_root=kb)
    first = agg.init_day_agenda(Horizon.DAY)
    assert first["created"] is True
    assert first["path"] == "current/agenda.md"
    assert (kb / "current" / "agenda.md").is_file()
    texts = [t.description for t in first["items"]]
    assert any("Ship sitrep" in t for t in texts)

    second = agg.init_day_agenda(Horizon.DAY)
    assert second["created"] is False
    # P2 backlog is not seeded; day file still parses
    assert parse_agenda_md(kb / "current" / "agenda.md", "today")


def test_day_agenda_included_in_aggregate(tmp_path: Path):
    kb = tmp_path / "kb"
    day = kb / "current"
    day.mkdir(parents=True)
    (day / "agenda.md").write_text(
        "- [ ] P1: Morning standup @today\n",
        encoding="utf-8",
    )
    agg = AgendaAggregator(kb_root=kb)
    tasks = agg.aggregate(Horizon.DAY)
    assert len(tasks) == 1
    assert tasks[0].project == "today"
    assert "standup" in tasks[0].description
