"""PhilEvents fetcher.

Fetches philosophy events and calls for papers from PhilEvents.org.
Uses their RSS export endpoints for topic-based queries.

Usage in feed_sources config:
    {
        "topics": [577, 578, 576],  # Metaphysics, Mind, Epistemology
        "max_results": 50
    }

Topic IDs (subset):
    576 - Epistemology
    577 - Metaphysics
    578 - Philosophy of Mind
    574 - Philosophy of Language
    575 - Philosophy of Religion
    591 - Philosophy of Mathematics
    634 - Logic and Philosophy of Logic
    599 - Philosophy of Cognitive Science
    590 - Continental Philosophy
    613 - Social and Political Philosophy
"""

import hashlib
from datetime import datetime
from time import mktime

import feedparser

from gaius.workers.base import BaseFetcher, register_fetcher
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType


# Topic ID to name mapping
TOPIC_NAMES = {
    572: "Philosophy of Action",
    573: "Metaphysics and Epistemology",
    574: "Philosophy of Language",
    575: "Philosophy of Religion",
    576: "Epistemology",
    577: "Metaphysics",
    578: "Philosophy of Mind",
    581: "Asian Philosophy",
    583: "Medieval and Renaissance Philosophy",
    584: "African/Africana Philosophy",
    586: "Ancient Greek and Roman Philosophy",
    590: "Continental Philosophy",
    591: "Philosophy of Mathematics",
    595: "Philosophy of Social Science",
    596: "Philosophy of Biology",
    599: "Philosophy of Cognitive Science",
    600: "Philosophy of Law",
    601: "Value Theory",
    602: "Normative Ethics",
    604: "Aesthetics",
    606: "Meta-Ethics",
    608: "Applied Ethics",
    613: "Social and Political Philosophy",
    622: "Philosophical Traditions",
    626: "History of Western Philosophy",
    627: "20th Century Philosophy",
    629: "17th/18th Century Philosophy",
    630: "19th Century Philosophy",
    631: "Science, Logic, and Mathematics",
    633: "Philosophy of Physical Science",
    634: "Logic and Philosophy of Logic",
    635: "Philosophy of Computing and Information",
    636: "Philosophy of Probability",
    637: "General Philosophy of Science",
    638: "Metaphilosophy",
    640: "Philosophy of Gender, Race, and Sexuality",
    641: "Value Theory, Miscellaneous",
}


@register_fetcher(SourceType.PHILEVENTS)
class PhilEventsFetcher(BaseFetcher):
    """Fetcher for PhilEvents.org philosophy events."""

    BASE_URL = "https://philevents.org"

    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch events from PhilEvents topic RSS feeds.

        Source config options:
            topics: list[int] - Topic IDs to fetch (default: core philosophy topics)
            max_results: int - Maximum total items (default: 50)
        """
        config = source.config
        # Default to core philosophy topics if none specified
        topics = config.get("topics", [577, 578, 576, 574])  # Meta, Mind, Epist, Lang
        max_results = config.get("max_results", 50)

        try:
            items = await self._fetch_topics(topics, max_results, source)
            return FetchResult(
                items=items,
                metadata={
                    "topics": topics,
                    "topic_names": [TOPIC_NAMES.get(t, f"Topic {t}") for t in topics],
                    "max_results": max_results,
                    "actual_count": len(items),
                },
            )
        except Exception as e:
            return FetchResult(
                error=str(e),
                metadata={"topics": topics},
            )

    async def _fetch_topics(
        self,
        topics: list[int],
        max_results: int,
        source: FeedSource,
    ) -> list[ContentItem]:
        """Fetch and aggregate events from multiple topic feeds."""
        all_items = []
        seen_urls = set()

        # Distribute max_results across topics
        per_topic = max(10, max_results // len(topics))

        for topic_id in topics:
            feed_url = f"{self.BASE_URL}/search/topic/{topic_id}?format=rss"
            try:
                response = await self.fetch_url(feed_url)
                feed = feedparser.parse(response.text)

                topic_name = TOPIC_NAMES.get(topic_id, f"Topic {topic_id}")

                for entry in feed.entries[:per_topic]:
                    item = self._parse_entry(entry, source, topic_id, topic_name)
                    if item and item.url not in seen_urls:
                        seen_urls.add(item.url)
                        all_items.append(item)

                    if len(all_items) >= max_results:
                        break

            except Exception as e:
                # Log but continue with other topics
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to fetch PhilEvents topic {topic_id}: {e}"
                )

            if len(all_items) >= max_results:
                break

        # Sort by published date (newest first)
        all_items.sort(
            key=lambda x: x.published_at or datetime.min,
            reverse=True,
        )

        return all_items[:max_results]

    def _parse_entry(
        self,
        entry: dict,
        source: FeedSource,
        topic_id: int,
        topic_name: str,
    ) -> ContentItem | None:
        """Parse a feedparser entry into a ContentItem."""
        try:
            url = entry.get("link", entry.get("id", ""))
            if not url:
                return None

            external_id = hashlib.sha256(url.encode()).hexdigest()[:16]

            title = entry.get("title", "").strip()
            if not title:
                return None

            # Get description/summary
            summary = None
            if "summary" in entry:
                summary = self._clean_html(entry["summary"])
            elif "description" in entry:
                summary = self._clean_html(entry["description"])

            # Parse published date
            published_at = None
            for date_field in ["published_parsed", "updated_parsed"]:
                if date_field in entry and entry[date_field]:
                    try:
                        published_at = datetime.fromtimestamp(
                            mktime(entry[date_field])
                        )
                        break
                    except (ValueError, OverflowError):
                        pass

            # Extract event type from title if present
            event_type = "event"
            title_lower = title.lower()
            if "cfp" in title_lower or "call for" in title_lower:
                event_type = "cfp"
            elif "conference" in title_lower:
                event_type = "conference"
            elif "workshop" in title_lower:
                event_type = "workshop"
            elif "lecture" in title_lower or "talk" in title_lower:
                event_type = "lecture"
            elif "seminar" in title_lower:
                event_type = "seminar"

            return self.create_item(
                source=source,
                external_id=external_id,
                title=title,
                url=url,
                summary=summary,
                content_type="text/html",
                published_at=published_at,
                metadata={
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "event_type": event_type,
                },
            )
        except Exception:
            return None

    def _clean_html(self, html: str) -> str:
        """Basic HTML tag stripping."""
        import re
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
