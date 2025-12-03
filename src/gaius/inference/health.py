"""GPU Health Monitoring via NVIDIA Management Library.

Uses nvidia-ml-py (which provides the pynvml module) for GPU metrics:
- VRAM usage
- Temperature
- Power draw
- Utilization
- Health threshold checks

Usage:
    from gaius.inference.health import GPUHealthMonitor, get_health_monitor

    monitor = get_health_monitor()
    health = monitor.get_gpu_health(0)
    print(f"GPU 0: {health.vram_percent:.1f}% VRAM, {health.temperature_c}°C")
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import logging

logger = logging.getLogger(__name__)

# Try to import pynvml (provided by nvidia-ml-py package)
try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False
    logger.warning("nvidia-ml-py not available - GPU monitoring disabled")


# ═══════════════════════════════════════════════════════════════════════════════
# Health Thresholds
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class HealthThresholds:
    """Configurable thresholds for health assessment."""

    # VRAM thresholds
    vram_warning_percent: float = 85.0
    vram_critical_percent: float = 95.0

    # Temperature thresholds (RTX 4090 safe range)
    temp_warning_c: int = 75
    temp_critical_c: int = 85

    # Power thresholds (percentage of limit)
    power_warning_percent: float = 90.0
    power_critical_percent: float = 98.0

    # Utilization (low utilization might indicate issues)
    utilization_idle_threshold: int = 5

    @classmethod
    def from_config(cls) -> "HealthThresholds":
        """Load thresholds from HOCON config."""
        try:
            from ..core.config import get_config
            config = get_config()
            thresholds = config._raw.get("gaius", {}).get("inference", {}).get(
                "orchestrator", {}
            ).get("thresholds", {})

            return cls(
                vram_warning_percent=thresholds.get("vram_warning_percent", 85.0),
                vram_critical_percent=thresholds.get("vram_critical_percent", 95.0),
                temp_warning_c=thresholds.get("temp_warning_c", 75),
                temp_critical_c=thresholds.get("temp_critical_c", 85),
            )
        except Exception:
            return cls()


# ═══════════════════════════════════════════════════════════════════════════════
# GPU Health Data
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GPUHealth:
    """Health metrics for a single GPU."""

    gpu_id: int
    name: str = ""

    # Memory
    vram_used_gb: float = 0.0
    vram_total_gb: float = 0.0
    vram_free_gb: float = 0.0
    vram_percent: float = 0.0

    # Temperature
    temperature_c: int = 0

    # Power
    power_draw_w: float = 0.0
    power_limit_w: float = 0.0
    power_percent: float = 0.0

    # Utilization
    gpu_utilization_percent: int = 0
    memory_utilization_percent: int = 0

    # Errors
    ecc_errors: int = 0

    # Status
    healthy: bool = True
    warnings: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "gpu_id": self.gpu_id,
            "name": self.name,
            "vram": {
                "used_gb": round(self.vram_used_gb, 2),
                "total_gb": round(self.vram_total_gb, 2),
                "free_gb": round(self.vram_free_gb, 2),
                "percent": round(self.vram_percent, 1),
            },
            "temperature_c": self.temperature_c,
            "power": {
                "draw_w": round(self.power_draw_w, 1),
                "limit_w": round(self.power_limit_w, 1),
                "percent": round(self.power_percent, 1),
            },
            "utilization": {
                "gpu_percent": self.gpu_utilization_percent,
                "memory_percent": self.memory_utilization_percent,
            },
            "healthy": self.healthy,
            "warnings": self.warnings,
            "timestamp": self.timestamp.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# GPU Health Monitor
# ═══════════════════════════════════════════════════════════════════════════════

class GPUHealthMonitor:
    """Monitors GPU health via NVIDIA Management Library (pynvml)."""

    def __init__(self, thresholds: HealthThresholds | None = None):
        self._initialized = False
        self._device_count = 0
        self.thresholds = thresholds or HealthThresholds.from_config()

        if PYNVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self._device_count = pynvml.nvmlDeviceGetCount()
                self._initialized = True
                logger.info(f"GPU monitor initialized: {self._device_count} GPUs found")
            except Exception as e:
                logger.warning(f"Failed to initialize pynvml: {e}")
        else:
            logger.warning("pynvml not available - using mock GPU data")

    def __del__(self):
        """Cleanup pynvml on destruction."""
        if self._initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    @property
    def available(self) -> bool:
        """Check if GPU monitoring is available."""
        return self._initialized

    @property
    def device_count(self) -> int:
        """Get number of GPUs."""
        return self._device_count

    def reinitialize(self) -> bool:
        """Attempt to reinitialize pynvml (useful after installing the package).

        Returns:
            True if initialization succeeded
        """
        global PYNVML_AVAILABLE

        # Shutdown existing if needed
        if self._initialized:
            try:
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._initialized = False
            self._device_count = 0

        # Try to import/reimport pynvml
        try:
            import importlib
            import sys

            # Force reimport if module exists but wasn't available
            if 'pynvml' in sys.modules:
                importlib.reload(sys.modules['pynvml'])
            else:
                import pynvml

            import pynvml
            pynvml.nvmlInit()
            self._device_count = pynvml.nvmlDeviceGetCount()
            self._initialized = True
            PYNVML_AVAILABLE = True
            logger.info(f"GPU monitor reinitialized: {self._device_count} GPUs found")
            return True
        except ImportError:
            logger.warning("pynvml still not available after reimport attempt")
            return False
        except Exception as e:
            logger.warning(f"Failed to reinitialize pynvml: {e}")
            return False

    def get_gpu_health(self, gpu_id: int) -> GPUHealth:
        """Get health metrics for a specific GPU.

        Args:
            gpu_id: GPU index (0-based)

        Returns:
            GPUHealth with current metrics
        """
        if not self._initialized:
            return self._mock_gpu_health(gpu_id)

        if gpu_id >= self._device_count:
            raise ValueError(f"GPU {gpu_id} not found (have {self._device_count})")

        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_id)

            # Get device name
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")

            # Memory info
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            vram_used = memory.used / (1024**3)
            vram_total = memory.total / (1024**3)
            vram_free = memory.free / (1024**3)
            vram_percent = (memory.used / memory.total) * 100

            # Temperature
            try:
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
            except Exception:
                temp = 0

            # Power
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000  # mW to W
                power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000
                power_percent = (power / power_limit) * 100 if power_limit > 0 else 0
            except Exception:
                power = 0
                power_limit = 0
                power_percent = 0

            # Utilization
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_util = util.gpu
                mem_util = util.memory
            except Exception:
                gpu_util = 0
                mem_util = 0

            # ECC errors (if supported)
            try:
                ecc = pynvml.nvmlDeviceGetTotalEccErrors(
                    handle,
                    pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED,
                    pynvml.NVML_VOLATILE_ECC,
                )
            except Exception:
                ecc = 0

            # Build health object
            health = GPUHealth(
                gpu_id=gpu_id,
                name=name,
                vram_used_gb=vram_used,
                vram_total_gb=vram_total,
                vram_free_gb=vram_free,
                vram_percent=vram_percent,
                temperature_c=temp,
                power_draw_w=power,
                power_limit_w=power_limit,
                power_percent=power_percent,
                gpu_utilization_percent=gpu_util,
                memory_utilization_percent=mem_util,
                ecc_errors=ecc,
            )

            # Check thresholds and add warnings
            health.warnings = self.check_thresholds(health)
            health.healthy = len([w for w in health.warnings if "CRITICAL" in w]) == 0

            return health

        except Exception as e:
            logger.error(f"Failed to get GPU {gpu_id} health: {e}")
            return GPUHealth(
                gpu_id=gpu_id,
                healthy=False,
                warnings=[f"Error reading GPU: {e}"],
            )

    def get_all_gpu_health(self) -> list[GPUHealth]:
        """Get health metrics for all GPUs.

        Returns:
            List of GPUHealth objects
        """
        return [self.get_gpu_health(i) for i in range(self._device_count)]

    def check_thresholds(self, health: GPUHealth) -> list[str]:
        """Check health metrics against thresholds.

        Args:
            health: GPU health metrics

        Returns:
            List of warning messages
        """
        warnings = []
        t = self.thresholds

        # VRAM checks
        if health.vram_percent >= t.vram_critical_percent:
            warnings.append(
                f"CRITICAL: VRAM usage {health.vram_percent:.1f}% "
                f"(threshold: {t.vram_critical_percent}%)"
            )
        elif health.vram_percent >= t.vram_warning_percent:
            warnings.append(
                f"WARNING: VRAM usage {health.vram_percent:.1f}% "
                f"(threshold: {t.vram_warning_percent}%)"
            )

        # Temperature checks
        if health.temperature_c >= t.temp_critical_c:
            warnings.append(
                f"CRITICAL: Temperature {health.temperature_c}°C "
                f"(threshold: {t.temp_critical_c}°C)"
            )
        elif health.temperature_c >= t.temp_warning_c:
            warnings.append(
                f"WARNING: Temperature {health.temperature_c}°C "
                f"(threshold: {t.temp_warning_c}°C)"
            )

        # Power checks
        if health.power_percent >= t.power_critical_percent:
            warnings.append(
                f"CRITICAL: Power usage {health.power_percent:.1f}% of limit"
            )
        elif health.power_percent >= t.power_warning_percent:
            warnings.append(
                f"WARNING: Power usage {health.power_percent:.1f}% of limit"
            )

        # ECC errors
        if health.ecc_errors > 0:
            warnings.append(f"WARNING: {health.ecc_errors} ECC errors detected")

        return warnings

    def _mock_gpu_health(self, gpu_id: int) -> GPUHealth:
        """Return mock GPU health when pynvml unavailable."""
        return GPUHealth(
            gpu_id=gpu_id,
            name=f"Mock GPU {gpu_id}",
            vram_used_gb=8.0,
            vram_total_gb=24.0,
            vram_free_gb=16.0,
            vram_percent=33.3,
            temperature_c=45,
            power_draw_w=150,
            power_limit_w=450,
            power_percent=33.3,
            gpu_utilization_percent=25,
            memory_utilization_percent=30,
            healthy=True,
            warnings=["Mock data - pynvml not available"],
        )

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all GPU health.

        Returns:
            Summary dict with aggregated metrics
        """
        if not self._initialized:
            return {
                "available": False,
                "device_count": 0,
                "message": "GPU monitoring not available",
            }

        gpus = self.get_all_gpu_health()

        total_vram = sum(g.vram_total_gb for g in gpus)
        used_vram = sum(g.vram_used_gb for g in gpus)
        avg_temp = sum(g.temperature_c for g in gpus) / len(gpus) if gpus else 0
        total_power = sum(g.power_draw_w for g in gpus)
        all_warnings = []
        for g in gpus:
            all_warnings.extend(g.warnings)

        return {
            "available": True,
            "device_count": self._device_count,
            "vram": {
                "total_gb": round(total_vram, 2),
                "used_gb": round(used_vram, 2),
                "free_gb": round(total_vram - used_vram, 2),
                "percent": round((used_vram / total_vram) * 100, 1) if total_vram > 0 else 0,
            },
            "avg_temperature_c": round(avg_temp, 1),
            "total_power_w": round(total_power, 1),
            "healthy_gpus": sum(1 for g in gpus if g.healthy),
            "warnings": all_warnings,
            "gpus": [g.to_dict() for g in gpus],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_monitor: GPUHealthMonitor | None = None


def get_health_monitor() -> GPUHealthMonitor:
    """Get or create the GPU health monitor singleton."""
    global _monitor
    if _monitor is None:
        _monitor = GPUHealthMonitor()
    return _monitor
