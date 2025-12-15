"""Engine metric source implementation.

Fetches metrics from the Gaius engine via gRPC proxies:
- GPU memory utilization
- Endpoint health status
- Scheduler queue depth
- Evolution daemon status
"""

import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from .base import MetricSource, MetricValue, MetricSeries

if TYPE_CHECKING:
    from ...client.grpc_client import GrpcEngineClient

logger = logging.getLogger(__name__)


class EngineSource(MetricSource):
    """Fetch metrics from Gaius engine via gRPC.

    Maps metric query names to gRPC proxy method calls:
    - gpu_memory:N - GPU N memory percentage
    - gpu_memory_min - Minimum GPU memory percentage across all GPUs
    - gpu_memory_max - Maximum GPU memory percentage across all GPUs
    - gpu_utilization:N - GPU N compute utilization percentage
    - endpoint_count - Number of healthy endpoints
    - scheduler_queue - Queue depth
    - evolution_cycles - Completed evolution cycles
    """

    def __init__(self, grpc_client: Optional["GrpcEngineClient"] = None):
        """Initialize engine source.

        Args:
            grpc_client: Optional gRPC client instance. If not provided,
                         will attempt to create one on first use.
        """
        self._client = grpc_client
        self._connected = False

    async def _get_client(self) -> Optional["GrpcEngineClient"]:
        """Get or create gRPC client."""
        if self._client is None:
            try:
                from ...client.grpc_client import GrpcEngineClient
                self._client = GrpcEngineClient()
                await self._client.connect()
                self._connected = True
            except Exception as e:
                logger.debug(f"Failed to connect to engine: {e}")
                return None
        return self._client

    async def query_instant(self, query: str) -> Optional[MetricValue]:
        """Query current value based on metric name.

        Supported queries:
        - gpu_memory:N - GPU N memory percentage (0-100)
        - gpu_memory_min - Minimum GPU memory percentage across all GPUs
        - gpu_memory_max - Maximum GPU memory percentage across all GPUs
        - gpu_utilization:N - GPU N compute utilization (0-100)
        - endpoint_count - Number of healthy endpoints
        - scheduler_queue - Pending jobs in scheduler
        - evolution_cycles - Completed evolution cycles

        Args:
            query: Metric query in format "metric_name" or "metric_name:param"

        Returns:
            Current value, or None if unavailable
        """
        client = await self._get_client()
        if client is None:
            return None

        now = datetime.now(timezone.utc)

        try:
            # Parse query
            parts = query.split(":")
            metric_name = parts[0]
            param = parts[1] if len(parts) > 1 else None

            if metric_name == "gpu_memory":
                gpu_idx = int(param) if param else 0
                value = await self._get_gpu_memory(client, gpu_idx)
            elif metric_name == "gpu_memory_min":
                value = await self._get_gpu_memory_minmax(client, use_max=False)
            elif metric_name == "gpu_memory_max":
                value = await self._get_gpu_memory_minmax(client, use_max=True)
            elif metric_name == "gpu_utilization":
                gpu_idx = int(param) if param else 0
                value = await self._get_gpu_utilization(client, gpu_idx)
            elif metric_name == "endpoint_count":
                value = await self._get_endpoint_count(client)
            elif metric_name == "compute_capacity":
                value = await self._get_compute_capacity(client)
            elif metric_name == "scheduler_queue":
                value = await self._get_scheduler_queue(client)
            elif metric_name == "evolution_cycles":
                value = await self._get_evolution_cycles(client)
            else:
                logger.debug(f"Unknown engine metric: {metric_name}")
                return None

            if value is None:
                return None

            return MetricValue(
                value=value,
                timestamp=now,
                labels={"source": "engine", "metric": metric_name},
            )

        except Exception as e:
            logger.debug(f"Engine metric query failed: {e}")
            return None

    async def query_range(
        self,
        query: str,
        duration_seconds: int = 300,
        step_seconds: int = 15,
    ) -> MetricSeries:
        """Query range for engine metrics.

        Note: Engine metrics don't have historical data, so we return
        a single-point series with the current value.

        Args:
            query: Metric query
            duration_seconds: Ignored (no history)
            step_seconds: Ignored (no history)

        Returns:
            MetricSeries with single current value
        """
        value = await self.query_instant(query)
        if value is None:
            return MetricSeries(name=query, values=[])
        return MetricSeries(name=query, values=[value])

    async def health_check(self) -> bool:
        """Check if engine is reachable.

        Returns:
            True if engine gRPC connection is healthy
        """
        client = await self._get_client()
        if client is None:
            return False

        try:
            # Try to get scheduler status as health check
            status = await client.call("Scheduler", "status")
            return status is not None
        except Exception:
            return False

    async def close(self) -> None:
        """Close gRPC connection."""
        if self._client is not None and self._connected:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
            self._connected = False

    # --- Internal metric fetchers ---

    async def _get_gpu_memory(self, client: "GrpcEngineClient", gpu_idx: int) -> Optional[float]:
        """Get GPU memory utilization percentage."""
        try:
            # Use client.call() to call Health.check which includes GPU info
            health = await client.call("Health", "check")
            if health and "gpus" in health:
                gpus = health["gpus"]
                if gpu_idx < len(gpus):
                    gpu = gpus[gpu_idx]
                    used = gpu.get("memory_used_mb", 0)
                    total = gpu.get("memory_total_mb", 1)
                    return (used / total) * 100 if total > 0 else 0
        except Exception as e:
            logger.debug(f"GPU memory fetch failed: {e}")
        return None

    async def _get_gpu_memory_minmax(self, client: "GrpcEngineClient", use_max: bool) -> Optional[float]:
        """Get min or max GPU memory utilization across all GPUs."""
        try:
            health = await client.call("Health", "check")
            if health and "gpus" in health:
                gpus = health["gpus"]
                if not gpus:
                    return None
                percentages = []
                for gpu in gpus:
                    used = gpu.get("memory_used_mb", 0)
                    total = gpu.get("memory_total_mb", 1)
                    if total > 0:
                        percentages.append((used / total) * 100)
                if percentages:
                    return max(percentages) if use_max else min(percentages)
        except Exception as e:
            logger.debug(f"GPU memory min/max fetch failed: {e}")
        return None

    async def _get_gpu_utilization(self, client: "GrpcEngineClient", gpu_idx: int) -> Optional[float]:
        """Get GPU compute utilization percentage."""
        try:
            health = await client.call("Health", "check")
            if health and "gpus" in health:
                gpus = health["gpus"]
                if gpu_idx < len(gpus):
                    return gpus[gpu_idx].get("utilization_percent", 0)
        except Exception as e:
            logger.debug(f"GPU utilization fetch failed: {e}")
        return None

    async def _get_endpoint_count(self, client: "GrpcEngineClient") -> Optional[float]:
        """Get number of healthy endpoints."""
        try:
            # Use Orchestrator.status which has endpoint list with status
            status = await client.call("Orchestrator", "status")
            if status and "endpoints" in status:
                healthy = sum(
                    1 for ep in status["endpoints"]
                    if ep.get("status") == "healthy"
                )
                return float(healthy)
        except Exception as e:
            logger.debug(f"Endpoint count fetch failed: {e}")
        return None

    async def _get_compute_capacity(self, client: "GrpcEngineClient") -> Optional[float]:
        """Get percentage of GPU compute capacity that is functional.

        This metric weights endpoints by their GPU allocation. A 4-GPU endpoint
        crashing is a much bigger capacity loss than a 1-GPU endpoint.

        Capacity = (healthy GPUs / total allocated GPUs) * 100

        Returns:
            Percentage (0-100) of allocated GPU capacity that is functional
        """
        try:
            status = await client.call("Orchestrator", "status")
            if not status:
                return None

            endpoints = status.get("endpoints", [])
            if not endpoints:
                return 0.0

            total_gpus = 0
            healthy_gpus = 0

            for ep in endpoints:
                # Get GPU count for this endpoint (default to 1 if not specified)
                gpu_ids = ep.get("gpu_ids", [])
                gpu_count = len(gpu_ids) if gpu_ids else 1

                total_gpus += gpu_count

                if ep.get("status") == "healthy":
                    healthy_gpus += gpu_count

            # Return percentage of GPU capacity that is healthy
            return (healthy_gpus / total_gpus) * 100 if total_gpus > 0 else 0.0

        except Exception as e:
            logger.debug(f"Compute capacity fetch failed: {e}")
        return None

    async def _get_scheduler_queue(self, client: "GrpcEngineClient") -> Optional[float]:
        """Get scheduler queue depth."""
        try:
            status = await client.call("Scheduler", "status")
            if status:
                return float(status.get("queue_depth", 0))
        except Exception as e:
            logger.debug(f"Scheduler queue fetch failed: {e}")
        return None

    async def _get_evolution_cycles(self, client: "GrpcEngineClient") -> Optional[float]:
        """Get completed evolution cycles."""
        try:
            status = await client.call("Evolution", "status")
            if status:
                return float(status.get("cycles_completed", 0))
        except Exception as e:
            logger.debug(f"Evolution cycles fetch failed: {e}")
        return None
