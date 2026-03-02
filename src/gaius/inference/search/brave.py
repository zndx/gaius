"""Brave Search API client.

Usage:
    search = BraveSearch(api_key="...")
    results = await search.search("query")

    # For KB population
    structured = await search.search_for_kb("topic", domain="pension")

Exchanges are captured to Iceberg for training data (when enabled).
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, asdict

import httpx

logger = logging.getLogger(__name__)


def _is_exchange_capture_enabled() -> bool:
    """Check if exchange capture is enabled."""
    env_val = os.environ.get("GAIUS_HX_CAPTURE_EXCHANGES", "true")
    return env_val.lower() in ("1", "true", "yes")


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    published: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class AnswerCitation:
    """A citation from Brave's Answers API."""

    url: str
    snippet: str = ""
    favicon: str = ""
    start_index: int | None = None
    end_index: int | None = None


@dataclass
class AnswerResult:
    """Result from Brave's Answers API (/res/v1/chat/completions).

    Uses streaming to extract summary text, citations, and usage metadata.
    """

    summary_text: str
    citations: list[AnswerCitation]
    input_tokens: int = 0
    output_tokens: int = 0
    query_cost: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "summary_text": self.summary_text,
            "citations": [asdict(c) for c in self.citations],
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "query_cost": self.query_cost,
        }


class BraveSearch:
    """Brave Search API client.

    API docs: https://api.search.brave.com/app/documentation
    """

    BASE_URL = "https://api.search.brave.com/res/v1"

    def __init__(self, api_key: str, capture_exchanges: bool | None = None):
        """Initialize Brave search client.

        Args:
            api_key: Brave API key.
            capture_exchanges: Whether to capture exchanges to Iceberg.
                               If None, reads from GAIUS_HX_CAPTURE_EXCHANGES env.
        """
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

        # Exchange capture (lazy initialization)
        if capture_exchanges is None:
            capture_exchanges = _is_exchange_capture_enabled()
        self._capture_enabled = capture_exchanges
        self._exchange_capture = None

    def _get_exchange_capture(self):
        """Get or create exchange capture instance (lazy initialization)."""
        if not self._capture_enabled:
            return None
        if self._exchange_capture is None:
            try:
                from gaius.hx.exchange import get_exchange_capture
                self._exchange_capture = get_exchange_capture()
            except Exception as e:
                logger.warning(f"Failed to initialize exchange capture: {e}")
                self._capture_enabled = False
                return None
        return self._exchange_capture

    async def search(
        self,
        query: str,
        count: int = 10,
        country: str = "us",
        freshness: str | None = None,
    ) -> list[SearchResult]:
        """Execute a web search.

        Args:
            query: Search query
            count: Number of results (max 20)
            country: Country code for localization
            freshness: Recency filter (pd=past day, pw=past week, pm=past month, py=past year)

        Returns:
            List of SearchResult objects
        """
        params = {
            "q": query,
            "count": min(count, 20),
            "country": country,
        }
        if freshness:
            params["freshness"] = freshness

        start_time = time.time()
        response = await self._client.get(
            f"{self.BASE_URL}/web/search",
            params=params,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    published=item.get("age"),
                )
            )

        # Capture exchange to Iceberg (fire-and-forget)
        if results:  # Only capture successful searches with results
            capture = self._get_exchange_capture()
            if capture:
                try:
                    from gaius.hx.exchange import ExchangeRecord
                    record = ExchangeRecord(
                        provider="brave",
                        request_messages=[{"role": "user", "content": query}],
                        request_model="brave-search-v1",
                        request_params={
                            "count": count,
                            "country": country,
                            "freshness": freshness,
                        },
                        response_content=json.dumps([r.to_dict() for r in results]),
                        response_model="brave-search-v1",
                        input_tokens=0,  # Not applicable for search
                        output_tokens=len(results),  # Use result count as proxy
                        latency_ms=latency_ms,
                        source_context={"provider": "brave", "result_count": len(results)},
                    )
                    asyncio.create_task(capture.capture(record))
                except Exception as e:
                    logger.debug(f"Failed to capture Brave search exchange: {e}")

        return results

    async def answer(
        self,
        query: str,
        answers_api_key: str | None = None,
    ) -> AnswerResult:
        """Call Brave's Answers API for a grounded AI summary.

        Uses streaming to extract the full response with inline citations.
        Requires a Brave Answers API key (BRAVE_ANSWERS_API_KEY).

        Args:
            query: Question or topic to summarize
            answers_api_key: Answers API key (if different from search key)

        Returns:
            AnswerResult with summary text and citations

        Raises:
            httpx.HTTPStatusError: If API returns an error
            RuntimeError: If BRAVE_ANSWERS_API_KEY is not available
        """
        if not answers_api_key:
            from gaius.core.config import get_config
            answers_api_key = get_config().providers.brave.answers_api_key
        api_key = answers_api_key
        if not api_key:
            raise RuntimeError(
                "Brave Answers API key not available.\n"
                "  Set: BRAVE_ANSWERS_API_KEY environment variable or providers.brave.answers_api_key in HOCON config\n"
                "  #COL.00000012.BRAVESUMFAIL"
            )

        start_time = time.time()
        full_content = ""

        async with httpx.AsyncClient(
            headers={
                "x-subscription-token": api_key,
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            timeout=60.0,
        ) as client:
            async with client.stream(
                "POST",
                f"{self.BASE_URL}/chat/completions",
                json={
                    "messages": [{"role": "user", "content": query}],
                    "model": "brave",
                    "stream": True,
                    "enable_citations": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        payload = line[6:]
                        if payload == "[DONE]":
                            break
                        chunk = json.loads(payload)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        if "content" in delta:
                            full_content += delta["content"]

        latency_ms = int((time.time() - start_time) * 1000)

        # Parse inline citations from streamed content
        citations: list[AnswerCitation] = []
        for match in re.finditer(r"<citation>(.*?)</citation>", full_content):
            try:
                parsed = json.loads(match.group(1))
                citations.append(AnswerCitation(
                    url=parsed.get("url", ""),
                    snippet=parsed.get("snippet", ""),
                    favicon=parsed.get("favicon", ""),
                    start_index=parsed.get("start_index"),
                    end_index=parsed.get("end_index"),
                ))
            except json.JSONDecodeError:
                pass

        # Parse usage metadata
        input_tokens = 0
        output_tokens = 0
        query_cost = 0.0
        for match in re.finditer(r"<usage>(.*?)</usage>", full_content):
            try:
                usage = json.loads(match.group(1))
                input_tokens = usage.get("X-Request-Tokens-In", 0)
                output_tokens = usage.get("X-Request-Tokens-Out", 0)
                query_cost = usage.get("X-Request-Queries-Cost", 0.0)
            except json.JSONDecodeError:
                pass

        # Strip inline tags from the text
        clean_text = re.sub(r"<citation>.*?</citation>", "", full_content)
        clean_text = re.sub(r"<enum_item>.*?</enum_item>", "", clean_text)
        clean_text = re.sub(r"<usage>.*?</usage>", "", clean_text).strip()

        result = AnswerResult(
            summary_text=clean_text,
            citations=citations,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            query_cost=query_cost,
        )

        # Capture exchange to Iceberg
        capture = self._get_exchange_capture()
        if capture:
            try:
                from gaius.hx.exchange import ExchangeRecord
                record = ExchangeRecord(
                    provider="brave-answers",
                    request_messages=[{"role": "user", "content": query}],
                    request_model="brave-answers-v1",
                    request_params={"enable_citations": True},
                    response_content=json.dumps(result.to_dict()),
                    response_model="brave-answers-v1",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    source_context={
                        "provider": "brave-answers",
                        "citation_count": len(citations),
                    },
                )
                asyncio.create_task(capture.capture(record))
            except Exception as e:
                logger.debug(f"Failed to capture Brave Answers exchange: {e}")

        logger.info(
            f"Brave Answers: {len(clean_text)} chars, "
            f"{len(citations)} citations, {latency_ms}ms"
        )

        return result

    async def summarize_topic(
        self,
        title: str,
        context: str = "",
        answers_api_key: str | None = None,
    ) -> AnswerResult:
        """Summarize a topic using Brave's Answers API.

        Builds a query from title + truncated context and calls the Answers API.

        Args:
            title: Topic title
            context: Additional context (truncated to 200 chars)
            answers_api_key: Answers API key (if different from search key)

        Returns:
            AnswerResult with summary text and citations

        Raises:
            RuntimeError: If BRAVE_ANSWERS_API_KEY is not available
        """
        query = title
        if context:
            query = f"{title} {context[:200]}"
        return await self.answer(query, answers_api_key=answers_api_key)

    async def search_for_kb(
        self,
        topic: str,
        domain: str,
        count: int = 5,
    ) -> list[dict]:
        """Search optimized for KB population.

        Returns structured data suitable for creating KB entries.

        Args:
            topic: Topic to research
            domain: Domain context (e.g., "Apache Kudu", "pension")
            count: Number of results

        Returns:
            List of dicts with source, title, summary, domain, query keys
        """
        # Build a domain-aware query
        full_query = f"{domain}: {topic}"
        results = await self.search(full_query, count=count)

        return [
            {
                "source": r.url,
                "title": r.title,
                "summary": r.snippet,
                "domain": domain,
                "query": topic,
                "published": r.published,
            }
            for r in results
        ]

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
