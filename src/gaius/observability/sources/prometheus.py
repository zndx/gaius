"""Prometheus metric source implementation.

Queries Prometheus HTTP API for metrics:
- /api/v1/query for instant queries
- /api/v1/query_range for time series (sparklines)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import MetricSource, MetricValue, MetricSeries

logger = logging.getLogger(__name__)


class PrometheusSource(MetricSource):
    """Prometheus HTTP API client.

    Connects to Prometheus at the configured URL and executes PromQL queries.
    Handles connection pooling and graceful error handling.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:9090",
        timeout_seconds: float = 5.0,
    ):
        """Initialize Prometheus source.

        Args:
            base_url: Prometheus server URL
            timeout_seconds: Request timeout
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def query_instant(self, query: str) -> Optional[MetricValue]:
        """Execute instant query against Prometheus.

        Args:
            query: PromQL query string

        Returns:
            Current metric value, or None if query fails or returns no data
        """
        try:
            client = await self._get_client()
            response = await client.get(
                "/api/v1/query",
                params={"query": query},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "success":
                logger.warning(f"Prometheus query failed: {data.get('error', 'unknown')}")
                return None

            results = data.get("data", {}).get("result", [])
            if not results:
                return None

            # Get first result (instant queries return single value per series)
            result = results[0]
            timestamp, value = result.get("value", [0, "0"])

            return MetricValue(
                value=float(value),
                timestamp=datetime.fromtimestamp(float(timestamp), tz=timezone.utc),
                labels=result.get("metric", {}),
            )

        except httpx.HTTPError as e:
            logger.debug(f"Prometheus query error: {e}")
            return None
        except (ValueError, KeyError, IndexError) as e:
            logger.debug(f"Prometheus response parse error: {e}")
            return None

    async def query_range(
        self,
        query: str,
        duration_seconds: int = 300,
        step_seconds: int = 15,
    ) -> MetricSeries:
        """Execute range query for time series data.

        Args:
            query: PromQL query string
            duration_seconds: How far back to query (default 5 minutes)
            step_seconds: Resolution between points (default 15s)

        Returns:
            MetricSeries with values for sparkline rendering
        """
        try:
            client = await self._get_client()
            now = time.time()
            start = now - duration_seconds

            response = await client.get(
                "/api/v1/query_range",
                params={
                    "query": query,
                    "start": start,
                    "end": now,
                    "step": f"{step_seconds}s",
                },
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "success":
                logger.warning(f"Prometheus range query failed: {data.get('error', 'unknown')}")
                return MetricSeries(name=query, values=[])

            results = data.get("data", {}).get("result", [])
            if not results:
                return MetricSeries(name=query, values=[])

            # Get first series
            result = results[0]
            values = []
            for timestamp, value in result.get("values", []):
                try:
                    values.append(
                        MetricValue(
                            value=float(value),
                            timestamp=datetime.fromtimestamp(float(timestamp), tz=timezone.utc),
                            labels=result.get("metric", {}),
                        )
                    )
                except (ValueError, TypeError):
                    continue  # Skip invalid values

            return MetricSeries(
                name=query,
                values=values,
            )

        except httpx.HTTPError as e:
            logger.debug(f"Prometheus range query error: {e}")
            return MetricSeries(name=query, values=[])
        except (ValueError, KeyError) as e:
            logger.debug(f"Prometheus range response parse error: {e}")
            return MetricSeries(name=query, values=[])

    async def health_check(self) -> bool:
        """Check if Prometheus is reachable.

        Returns:
            True if Prometheus responds to /-/ready endpoint
        """
        try:
            client = await self._get_client()
            response = await client.get("/-/ready")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# Module-level singleton for convenience
_default_source: Optional[PrometheusSource] = None


def get_prometheus_source(base_url: str = "http://localhost:9090") -> PrometheusSource:
    """Get or create default Prometheus source.

    Args:
        base_url: Prometheus server URL

    Returns:
        PrometheusSource instance (singleton)
    """
    global _default_source
    if _default_source is None:
        _default_source = PrometheusSource(base_url=base_url)
    return _default_source
