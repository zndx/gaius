"""Health service for system monitoring and health broadcasts.

Monitors GPU health, endpoint status, and broadcasts health metrics
to subscribers via Aeron pub/sub.

BDD Alignment:
- GPU health monitoring (temperature, VRAM, utilization)
- Endpoint health checks
- Health broadcasts to clients
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class GPUHealth:
    """GPU health metrics.

    Attributes:
        gpu_id: GPU device ID
        utilization_pct: GPU utilization percentage
        memory_used_gb: VRAM used in GB
        memory_total_gb: Total VRAM in GB
        temperature_c: Temperature in Celsius
        power_draw_w: Power draw in watts
        fan_speed_pct: Fan speed percentage
    """

    gpu_id: int
    utilization_pct: float = 0.0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    temperature_c: int = 0
    power_draw_w: float = 0.0
    fan_speed_pct: int = 0

    @property
    def memory_used_pct(self) -> float:
        """Memory utilization percentage."""
        if self.memory_total_gb == 0:
            return 0.0
        return (self.memory_used_gb / self.memory_total_gb) * 100

    @property
    def is_healthy(self) -> bool:
        """Check if GPU is in healthy state."""
        return self.temperature_c < 85 and self.memory_used_pct < 98

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "gpu_id": self.gpu_id,
            "utilization_pct": self.utilization_pct,
            "memory_used_gb": round(self.memory_used_gb, 2),
            "memory_total_gb": round(self.memory_total_gb, 2),
            "memory_used_pct": round(self.memory_used_pct, 1),
            "temperature_c": self.temperature_c,
            "power_draw_w": round(self.power_draw_w, 1),
            "fan_speed_pct": self.fan_speed_pct,
            "is_healthy": self.is_healthy,
        }


@dataclass
class EndpointHealth:
    """Health status of an inference endpoint.

    Attributes:
        agent_alias: Agent this endpoint serves
        status: Current status (healthy, unhealthy, starting, stopped)
        last_check: Time of last health check
        consecutive_failures: Number of consecutive health check failures
        latency_ms: Average response latency
        requests_per_minute: Request throughput
    """

    agent_alias: str
    status: str = "unknown"
    last_check: Optional[datetime] = None
    consecutive_failures: int = 0
    latency_ms: float = 0.0
    requests_per_minute: float = 0.0

    @property
    def is_healthy(self) -> bool:
        """Check if endpoint is healthy."""
        return self.status == "healthy" and self.consecutive_failures == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "agent_alias": self.agent_alias,
            "status": self.status,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "consecutive_failures": self.consecutive_failures,
            "latency_ms": round(self.latency_ms, 1),
            "requests_per_minute": round(self.requests_per_minute, 2),
            "is_healthy": self.is_healthy,
        }


@dataclass
class SystemHealth:
    """Overall system health snapshot.

    Attributes:
        timestamp: When snapshot was taken
        gpus: GPU health metrics
        endpoints: Endpoint health status
        scheduler_queue_depth: Number of pending jobs
        evolution_running: Whether evolution daemon is active
    """

    timestamp: datetime = field(default_factory=datetime.now)
    gpus: list[GPUHealth] = field(default_factory=list)
    endpoints: list[EndpointHealth] = field(default_factory=list)
    scheduler_queue_depth: int = 0
    evolution_running: bool = False

    @property
    def all_gpus_healthy(self) -> bool:
        """Check if all GPUs are healthy."""
        return all(gpu.is_healthy for gpu in self.gpus) if self.gpus else True

    @property
    def all_endpoints_healthy(self) -> bool:
        """Check if all endpoints are healthy."""
        return all(ep.is_healthy for ep in self.endpoints) if self.endpoints else True

    @property
    def overall_healthy(self) -> bool:
        """Overall system health."""
        return self.all_gpus_healthy and self.all_endpoints_healthy

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization/broadcast."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_healthy": self.overall_healthy,
            "gpus": [gpu.to_dict() for gpu in self.gpus],
            "endpoints": [ep.to_dict() for ep in self.endpoints],
            "scheduler_queue_depth": self.scheduler_queue_depth,
            "evolution_running": self.evolution_running,
            "all_gpus_healthy": self.all_gpus_healthy,
            "all_endpoints_healthy": self.all_endpoints_healthy,
        }


class HealthService:
    """Health monitoring and broadcast service.

    Collects health metrics from GPUs, endpoints, and other services,
    and broadcasts updates to subscribers.

    Features:
    - GPU health monitoring via pynvml
    - Endpoint health checks
    - Health metric broadcasting
    - Alert thresholds
    """

    def __init__(
        self,
        broadcast_interval_ms: int = 5000,
        check_interval_ms: int = 2000,
    ):
        """Initialize health service.

        Args:
            broadcast_interval_ms: How often to broadcast health (default 5s)
            check_interval_ms: How often to check health (default 2s)
        """
        self._broadcast_interval = broadcast_interval_ms / 1000
        self._check_interval = check_interval_ms / 1000

        # Current state
        self._gpu_health: dict[int, GPUHealth] = {}
        self._endpoint_health: dict[str, EndpointHealth] = {}
        self._last_snapshot: Optional[SystemHealth] = None

        # Callbacks for health updates
        self._health_callbacks: list[Callable[[SystemHealth], None]] = []

        # Service references (set after initialization)
        self._orchestrator_service = None
        self._scheduler_service = None
        self._evolution_service = None

        # Background tasks
        self._running = False
        self._check_task: Optional[asyncio.Task] = None
        self._broadcast_task: Optional[asyncio.Task] = None

        logger.info("HealthService initialized")

    def set_services(
        self,
        orchestrator=None,
        scheduler=None,
        evolution=None,
    ) -> None:
        """Set service references for health checking.

        Args:
            orchestrator: OrchestratorService instance
            scheduler: SchedulerService instance
            evolution: EvolutionService instance
        """
        self._orchestrator_service = orchestrator
        self._scheduler_service = scheduler
        self._evolution_service = evolution

    async def start(self) -> None:
        """Start health monitoring."""
        if self._running:
            return

        self._running = True

        # Start health check loop
        self._check_task = asyncio.create_task(self._check_loop())

        # Start broadcast loop
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())

        logger.info("HealthService started")

    async def stop(self) -> None:
        """Stop health monitoring."""
        if not self._running:
            return

        self._running = False

        # Cancel tasks
        for task in [self._check_task, self._broadcast_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        logger.info("HealthService stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Health Check Loop
    # ─────────────────────────────────────────────────────────────────────────

    async def _check_loop(self) -> None:
        """Background health check loop."""
        while self._running:
            try:
                await self._update_gpu_health()
                await self._update_endpoint_health()
                self._create_snapshot()
            except Exception as e:
                logger.error(f"Health check error: {e}")

            await asyncio.sleep(self._check_interval)

    async def _update_gpu_health(self) -> None:
        """Update GPU health metrics."""
        try:
            import pynvml

            pynvml.nvmlInit()

            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                # Get utilization
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)

                # Get memory
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)

                # Get temperature
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )

                # Get power (may fail on some GPUs)
                try:
                    power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000  # mW to W
                except Exception:
                    power = 0.0

                # Get fan speed (may fail on some GPUs)
                try:
                    fan = pynvml.nvmlDeviceGetFanSpeed(handle)
                except Exception:
                    fan = 0

                self._gpu_health[i] = GPUHealth(
                    gpu_id=i,
                    utilization_pct=util.gpu,
                    memory_used_gb=memory.used / (1024**3),
                    memory_total_gb=memory.total / (1024**3),
                    temperature_c=temp,
                    power_draw_w=power,
                    fan_speed_pct=fan,
                )

            pynvml.nvmlShutdown()

        except ImportError:
            # pynvml not available
            logger.debug("pynvml not available for GPU health monitoring")
        except Exception as e:
            logger.debug(f"GPU health update failed: {e}")

    async def _update_endpoint_health(self) -> None:
        """Update endpoint health from orchestrator."""
        if not self._orchestrator_service:
            return

        try:
            status = self._orchestrator_service.get_status()
            endpoints = status.get("endpoints", {})

            for alias, ep_info in endpoints.items():
                self._endpoint_health[alias] = EndpointHealth(
                    agent_alias=alias,
                    status=ep_info.get("status", "unknown"),
                    last_check=datetime.now(),
                    latency_ms=ep_info.get("avg_latency_ms", 0.0),
                )

        except Exception as e:
            logger.debug(f"Endpoint health update failed: {e}")

    def _create_snapshot(self) -> None:
        """Create a health snapshot."""
        queue_depth = 0
        if self._scheduler_service:
            try:
                status = self._scheduler_service.get_status()
                queue_depth = status.get("queue_depth", 0)
            except Exception:
                pass

        evolution_running = False
        if self._evolution_service:
            try:
                evolution_running = self._evolution_service.is_running
            except Exception:
                pass

        self._last_snapshot = SystemHealth(
            timestamp=datetime.now(),
            gpus=list(self._gpu_health.values()),
            endpoints=list(self._endpoint_health.values()),
            scheduler_queue_depth=queue_depth,
            evolution_running=evolution_running,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Broadcast Loop
    # ─────────────────────────────────────────────────────────────────────────

    async def _broadcast_loop(self) -> None:
        """Background broadcast loop."""
        while self._running:
            try:
                if self._last_snapshot:
                    self._broadcast_health(self._last_snapshot)
            except Exception as e:
                logger.error(f"Health broadcast error: {e}")

            await asyncio.sleep(self._broadcast_interval)

    def _broadcast_health(self, snapshot: SystemHealth) -> None:
        """Broadcast health to all subscribers."""
        for callback in self._health_callbacks:
            try:
                callback(snapshot)
            except Exception as e:
                logger.error(f"Health callback error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Subscriptions
    # ─────────────────────────────────────────────────────────────────────────

    def subscribe(self, callback: Callable[[SystemHealth], None]) -> None:
        """Subscribe to health updates.

        Args:
            callback: Function called with each health snapshot
        """
        self._health_callbacks.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        """Unsubscribe from health updates."""
        if callback in self._health_callbacks:
            self._health_callbacks.remove(callback)

    # ─────────────────────────────────────────────────────────────────────────
    # Direct Queries
    # ─────────────────────────────────────────────────────────────────────────

    def get_health(self) -> dict[str, Any]:
        """Get current health snapshot.

        Returns:
            Health snapshot dict
        """
        if self._last_snapshot:
            return self._last_snapshot.to_dict()

        # Return minimal health if no snapshot yet
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_healthy": True,
            "gpus": [],
            "endpoints": [],
            "scheduler_queue_depth": 0,
            "evolution_running": False,
        }

    def get_gpu_health(self) -> dict[int, dict[str, Any]]:
        """Get GPU health metrics.

        Returns:
            Dict mapping GPU ID to health metrics
        """
        return {gpu_id: health.to_dict() for gpu_id, health in self._gpu_health.items()}

    def get_endpoint_health(self) -> dict[str, dict[str, Any]]:
        """Get endpoint health metrics.

        Returns:
            Dict mapping agent alias to health status
        """
        return {
            alias: health.to_dict() for alias, health in self._endpoint_health.items()
        }

    def get_gpu_utilization(self) -> dict[int, float]:
        """Get GPU utilization percentages.

        Returns:
            Dict mapping GPU ID to utilization (0-100)
        """
        return {
            gpu_id: health.utilization_pct
            for gpu_id, health in self._gpu_health.items()
        }

    def is_gpu_idle(self, threshold: float = 20.0) -> bool:
        """Check if GPUs are idle.

        Args:
            threshold: Utilization threshold percentage

        Returns:
            True if average utilization below threshold
        """
        if not self._gpu_health:
            return True

        avg_util = sum(h.utilization_pct for h in self._gpu_health.values())
        avg_util /= len(self._gpu_health)
        return avg_util < threshold

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get health service status.

        Returns:
            Status dict
        """
        return {
            "running": self._running,
            "gpu_count": len(self._gpu_health),
            "endpoint_count": len(self._endpoint_health),
            "subscriber_count": len(self._health_callbacks),
            "check_interval_ms": int(self._check_interval * 1000),
            "broadcast_interval_ms": int(self._broadcast_interval * 1000),
            "last_check": (
                self._last_snapshot.timestamp.isoformat()
                if self._last_snapshot
                else None
            ),
            "overall_healthy": (
                self._last_snapshot.overall_healthy if self._last_snapshot else True
            ),
        }

    @property
    def is_running(self) -> bool:
        """Whether service is running."""
        return self._running
