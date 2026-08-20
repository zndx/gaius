"""HTML must not reach CLT/MaxSim as tags or entities."""

from gaius.ingest.htmlplain import to_plain_text


def test_strips_tags_and_unescapes_entities() -> None:
    raw = "<p>Replay <strong>&apos;26</strong> &amp; friends</p>"
    got = to_plain_text(raw)
    assert "<" not in got
    assert "&apos;" not in got
    assert "&amp;" not in got
    assert "Replay" in got
    assert "'26" in got
    assert "&" in got


def test_markdown_entities_unescaped() -> None:
    md = "# Replay '26\n\nJap found himself at Replay &apos;26."
    got = to_plain_text(md)
    assert "&apos;" not in got
    assert "Replay '26" in got
