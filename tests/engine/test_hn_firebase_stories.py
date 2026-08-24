"""HN Firebase story parse — no network."""

from gaius.workers.fetchers.hackernews import HNFetcher
from gaius.workers.models import FeedSource, SourceType


def test_parse_firebase_story_link() -> None:
    src = FeedSource(id=0, name="hn", source_type=SourceType.HACKERNEWS, base_url="")
    fetcher = object.__new__(HNFetcher)
    item = fetcher._parse_firebase_story(
        {
            "id": 8863,
            "type": "story",
            "title": "My YC app: Dropbox",
            "url": "http://www.getdropbox.com/u/2/screencast.html",
            "score": 111,
            "descendants": 71,
            "by": "dhouston",
            "time": 1175714200,
        },
        src,
    )
    assert item is not None
    assert "Dropbox" in item.title
    assert "getdropbox" in (item.content or "")
    assert item.metadata["hn_id"] == "8863"


def test_parse_firebase_story_skips_deleted() -> None:
    src = FeedSource(id=0, name="hn", source_type=SourceType.HACKERNEWS, base_url="")
    fetcher = object.__new__(HNFetcher)
    assert fetcher._parse_firebase_story({"id": 1, "deleted": True, "title": "x"}, src) is None
