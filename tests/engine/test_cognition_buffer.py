"""Cognition buffer agenda parse — no live Thinking."""

from gaius.engine.services.cognition_buffer import parse_agenda_payload, synthesis_body


def test_parse_agenda_payload_from_tagged_completion() -> None:
    text = """SYNTHESIS:
HN is covering GPU power; two cards landed on the site.

AGENDA:
{"briefs":[{"title":"GPU power narrative","body":"Keep analog honest"}],"reminders":[{"title":"DROP 496550","body":"after Iceberg verify","due_at":null}],"sessions":[{"title":"Agenda agent","body":"wire provenance"}]}
"""
    data = parse_agenda_payload(text)
    assert data["briefs"][0]["title"] == "GPU power narrative"
    assert data["reminders"][0]["title"] == "DROP 496550"
    assert data["sessions"][0]["title"] == "Agenda agent"
    assert "HN is covering" in synthesis_body(text)


def test_parse_agenda_payload_bare_json() -> None:
    data = parse_agenda_payload(
        '{"briefs":[{"title":"A","body":"b"}],"reminders":[],"sessions":[]}'
    )
    assert data["briefs"][0]["title"] == "A"
