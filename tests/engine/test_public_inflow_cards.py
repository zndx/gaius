"""Public landing cards come from feed URLs, never KB paths."""

from gaius.engine.services.collection_service import (
    OPTIONAL_CARD_SUMMARIES,
    REQUIRED_CARD_SUMMARY,
    public_card_source_type,
)


def test_public_card_source_type_arxiv() -> None:
    assert public_card_source_type("arxiv") == "arxiv"
    assert public_card_source_type("biorxiv") == "arxiv"
    assert public_card_source_type("rss") == "web"
    assert public_card_source_type("docs") == "web"


def test_card_page_requires_local_open_weights() -> None:
    """LuxCore + local OW are mandatory; Brave/Cerebras vary with API/budget."""
    assert REQUIRED_CARD_SUMMARY == "open_weights"
    assert OPTIONAL_CARD_SUMMARIES == ("frontier", "cerebras")
    assert REQUIRED_CARD_SUMMARY not in OPTIONAL_CARD_SUMMARIES
