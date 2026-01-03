"""Hacker News fetcher.

Fetches stories and comments from Hacker News using:
- Front page RSS: https://news.ycombinator.com/rss
- Firebase API for new comments: https://hacker-news.firebaseio.com/v0/

The Firebase API provides real-time access to HN data including:
- /v0/updates.json - Recently updated items (stories, comments)
- /v0/item/{id}.json - Individual item details

Config options:
    newcomments: bool - Fetch recent comments via Firebase API (default: False)
    max_items: int - Maximum items to fetch (default: 30)
    buffer_only: bool - Skip persistence to Iceberg/KB, buffer only (default: False)
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime
from time import mktime
from typing import Any

import feedparser

from gaius.workers.base import BaseFetcher, register_fetcher
from gaius.workers.models import ContentItem, FeedSource, FetchResult, SourceType

logger = logging.getLogger(__name__)


@register_fetcher(SourceType.HACKERNEWS)
class HNFetcher(BaseFetcher):
    """Fetcher for Hacker News stories and comments.

    Uses RSS for front page stories and Firebase API for new comments.
    """

    # HN endpoints
    FRONT_PAGE_URL = "https://news.ycombinator.com/rss"
    FIREBASE_BASE = "https://hacker-news.firebaseio.com/v0"
    UPDATES_URL = f"{FIREBASE_BASE}/updates.json"

    # Rate limit: be polite to HN
    RATE_LIMIT_DELAY = 0.1  # 100ms between Firebase requests

    async def fetch(self, source: FeedSource) -> FetchResult:
        """Fetch items from Hacker News.

        Source config options:
            newcomments: bool - Fetch new comments via Firebase API (default: False)
            max_items: int - Maximum items to fetch (default: 30)
            buffer_only: bool - Skip persistence, buffer only (returned in metadata)

        Args:
            source: The feed source configuration

        Returns:
            FetchResult with list of ContentItem or error
        """
        config = source.config
        newcomments = config.get("newcomments", False)
        max_items = config.get("max_items", 30)
        buffer_only = config.get("buffer_only", False)

        try:
            if newcomments:
                # Use Firebase API for new comments
                items = await self._fetch_new_comments(max_items, source)
                feed_url = self.UPDATES_URL
            else:
                # Use RSS for front page stories
                items = await self._fetch_feed(self.FRONT_PAGE_URL, max_items, source, False)
                feed_url = self.FRONT_PAGE_URL

            return FetchResult(
                items=items,
                metadata={
                    "feed_url": feed_url,
                    "newcomments": newcomments,
                    "buffer_only": buffer_only,
                    "actual_count": len(items),
                },
            )
        except Exception as e:
            return FetchResult(
                error=str(e),
                metadata={
                    "feed_url": self.UPDATES_URL if newcomments else self.FRONT_PAGE_URL,
                    "newcomments": newcomments,
                    "buffer_only": buffer_only,
                },
            )

    async def _fetch_feed(
        self,
        feed_url: str,
        max_items: int,
        source: FeedSource,
        is_comments: bool,
    ) -> list[ContentItem]:
        """Fetch and parse HN RSS feed.

        Args:
            feed_url: The RSS feed URL to fetch
            max_items: Maximum items to return
            source: The feed source configuration
            is_comments: Whether this is the comments feed

        Returns:
            List of ContentItem objects
        """
        response = await self.fetch_url(feed_url)
        feed = feedparser.parse(response.text)

        items = []
        for entry in feed.entries[:max_items]:
            item = self._parse_entry(entry, source, is_comments)
            if item:
                items.append(item)

        return items

    async def _fetch_new_comments(
        self,
        max_items: int,
        source: FeedSource,
    ) -> list[ContentItem]:
        """Fetch new comments via Firebase API.

        Uses the /v0/updates.json endpoint to get recently updated items,
        then fetches individual items to filter for comments.

        Args:
            max_items: Maximum comments to return
            source: The feed source configuration

        Returns:
            List of ContentItem objects (comments only)
        """
        # Get recently updated item IDs
        response = await self.fetch_url(self.UPDATES_URL)
        updates = response.json()

        item_ids = updates.get("items", [])
        if not item_ids:
            return []

        # Cache for story lookups to avoid redundant fetches
        story_cache: dict[int, dict[str, Any]] = {}

        # Fetch items in parallel (with rate limiting)
        items = []
        batch_size = min(max_items * 2, 50)  # Fetch more since not all are comments

        for item_id in item_ids[:batch_size]:
            if len(items) >= max_items:
                break

            try:
                item_url = f"{self.FIREBASE_BASE}/item/{item_id}.json"
                item_response = await self.fetch_url(item_url)
                item_data = item_response.json()

                if item_data and item_data.get("type") == "comment":
                    # Fetch the root story to get its title
                    story_info = await self._get_root_story(
                        item_data.get("parent"), story_cache
                    )
                    content_item = self._parse_firebase_comment(
                        item_data, source, story_info
                    )
                    if content_item:
                        items.append(content_item)
                    else:
                        logger.debug(f"Skip item {item_id}: parse failed (empty text?)")
                elif item_data:
                    logger.debug(f"Skip item {item_id}: type={item_data.get('type')}")

                # Rate limit
                await asyncio.sleep(self.RATE_LIMIT_DELAY)

            except Exception as e:
                logger.debug(f"Skip item {item_id}: {e}")
                continue  # Skip failed items

        return items

    async def _get_root_story(
        self,
        parent_id: int | None,
        cache: dict[int, dict[str, Any]],
        max_depth: int = 10,
    ) -> dict[str, Any]:
        """Trace up through parent comments to find the root story.

        Args:
            parent_id: The parent ID to start from
            cache: Cache of already-fetched items
            max_depth: Maximum depth to traverse (prevent infinite loops)

        Returns:
            Dict with story_id, story_title, story_url (empty if not found)
        """
        if parent_id is None:
            return {}

        current_id = parent_id
        depth = 0

        while current_id and depth < max_depth:
            # Check cache first
            if current_id in cache:
                item = cache[current_id]
            else:
                try:
                    url = f"{self.FIREBASE_BASE}/item/{current_id}.json"
                    response = await self.fetch_url(url)
                    item = response.json()
                    cache[current_id] = item
                    await asyncio.sleep(self.RATE_LIMIT_DELAY)
                except Exception:
                    return {}

            if not item:
                return {}

            # Found the story!
            if item.get("type") == "story":
                return {
                    "story_id": str(item.get("id", "")),
                    "story_title": item.get("title", ""),
                    "story_url": item.get("url", ""),
                }

            # Keep tracing up
            current_id = item.get("parent")
            depth += 1

        return {}

    def _parse_firebase_comment(
        self,
        data: dict[str, Any],
        source: FeedSource,
        story_info: dict[str, Any] | None = None,
    ) -> ContentItem | None:
        """Parse a Firebase API comment into a ContentItem.

        Args:
            data: The Firebase item dict
            source: The feed source configuration
            story_info: Optional dict with story_id, story_title, story_url

        Returns:
            ContentItem or None if parsing failed
        """
        try:
            item_id = data.get("id")
            if not item_id:
                return None

            # Get comment text (may contain HTML)
            text = data.get("text", "")
            text = self._clean_html(text)

            if not text:
                return None

            author = data.get("by", "anonymous")
            parent_id = data.get("parent")
            timestamp = data.get("time")

            # Build URL to comment
            url = f"https://news.ycombinator.com/item?id={item_id}"

            # Parse timestamp
            published_at = None
            if timestamp:
                try:
                    published_at = datetime.fromtimestamp(timestamp)
                except (ValueError, OverflowError):
                    pass

            # Build metadata with story info
            story_info = story_info or {}
            metadata = {
                "hn_id": str(item_id),
                "is_comment": True,
                "parent_id": str(parent_id) if parent_id else None,
                "source_feed": "firebase_updates",
                "author": author,
            }
            # Add story info if available
            if story_info.get("story_title"):
                metadata["story_title"] = story_info["story_title"]
            if story_info.get("story_id"):
                metadata["story_id"] = story_info["story_id"]
            if story_info.get("story_url"):
                metadata["story_url"] = story_info["story_url"]

            # Build title including story reference
            story_title = story_info.get("story_title", "")
            if story_title:
                title = f"[{author}] on: {story_title}"
            else:
                title = f"[Comment by {author}]"

            return self.create_item(
                source=source,
                external_id=str(item_id),
                title=title,
                url=url,
                authors=[author],
                summary=text[:500] if len(text) > 500 else text,
                content=text,
                content_type="text/plain",
                published_at=published_at,
                metadata=metadata,
            )
        except Exception:
            return None

    def _parse_entry(
        self,
        entry: dict,
        source: FeedSource,
        is_comments: bool,
    ) -> ContentItem | None:
        """Parse a feedparser entry into a ContentItem.

        Args:
            entry: The feedparser entry dict
            source: The feed source configuration
            is_comments: Whether this is from the comments feed

        Returns:
            ContentItem or None if parsing failed
        """
        try:
            # Get the item URL (link to HN item)
            url = entry.get("link", "")
            if not url:
                return None

            # Generate a stable ID from the URL
            external_id = self._generate_id(url)

            # Extract HN item ID from URL if possible
            hn_id = self._extract_hn_id(url)

            # Get title
            title = entry.get("title", "Untitled")
            if is_comments:
                # Comments have author in title format: "Author: Comment preview"
                title = f"[Comment] {title}"

            # Get content/summary
            # HN RSS provides description which may be HTML
            summary = entry.get("description", "") or entry.get("summary", "")
            summary = self._clean_html(summary)

            # Parse published date
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published_at = datetime.fromtimestamp(mktime(entry.published_parsed))
                except (ValueError, OverflowError):
                    pass

            # Extract author if available
            authors = []
            author = entry.get("author", "")
            if author:
                authors.append(author)

            # Get comments URL if different from main URL
            comments_url = entry.get("comments", "")

            return self.create_item(
                source=source,
                external_id=external_id,
                title=title[:500],  # Limit title length
                url=url,
                authors=authors,
                summary=summary[:2000] if summary else None,  # Limit summary
                content=summary,  # Store full content for buffer use
                content_type="text/plain",
                published_at=published_at,
                metadata={
                    "hn_id": hn_id,
                    "is_comment": is_comments,
                    "comments_url": comments_url,
                    "source_feed": (
                        "newcomments" if is_comments else "frontpage"
                    ),
                },
            )
        except Exception:
            return None

    def _generate_id(self, url: str) -> str:
        """Generate a stable ID from URL.

        Args:
            url: The URL to hash

        Returns:
            First 16 characters of SHA-256 hash
        """
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _extract_hn_id(self, url: str) -> str | None:
        """Extract HN item ID from URL.

        HN URLs look like:
        - https://news.ycombinator.com/item?id=12345678

        Args:
            url: The HN URL

        Returns:
            The item ID or None if not found
        """
        match = re.search(r"item\?id=(\d+)", url)
        if match:
            return match.group(1)
        return None

    def _clean_html(self, html: str) -> str:
        """Strip HTML tags and normalize whitespace.

        Args:
            html: HTML content to clean

        Returns:
            Plain text with normalized whitespace
        """
        if not html:
            return ""

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)

        # Decode common HTML entities
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#x27;", "'")
        text = text.replace("&nbsp;", " ")

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)

        return text.strip()
