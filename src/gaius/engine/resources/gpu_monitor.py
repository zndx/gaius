"""GPU monitoring utilities for resource management.

Provides simple async functions for querying GPU state
without requiring full health service initialization.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_gpu_memory_free() -> dict[int, float]:
    """Get free GPU memory for each GPU.

    Returns:
        Dict mapping GPU ID to free memory in GB
    """
    # Run in executor to avoid blocking
    return await asyncio.get_event_loop().run_in_executor(
        None, _get_gpu_memory_free_sync
    )


def _get_gpu_memory_free_sync() -> dict[int, float]:
    """Synchronous implementation of GPU memory query."""
    try:
        import pynvml

        pynvml.nvmlInit()
        result = {}

        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                # Convert bytes to GB
                free_gb = memory.free / (1024**3)
                result[i] = free_gb
        finally:
            pynvml.nvmlShutdown()

        return result

    except ImportError:
        logger.warning("pynvml not available, cannot query GPU memory")
        return {}
    except Exception as e:
        logger.warning(f"Failed to query GPU memory: {e}")
        return {}


async def get_gpu_utilization() -> dict[int, float]:
    """Get GPU utilization percentage for each GPU.

    Returns:
        Dict mapping GPU ID to utilization percentage (0-100)
    """
    return await asyncio.get_event_loop().run_in_executor(
        None, _get_gpu_utilization_sync
    )


def _get_gpu_utilization_sync() -> dict[int, float]:
    """Synchronous implementation of GPU utilization query."""
    try:
        import pynvml

        pynvml.nvmlInit()
        result = {}

        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                result[i] = float(util.gpu)
        finally:
            pynvml.nvmlShutdown()

        return result

    except ImportError:
        logger.warning("pynvml not available, cannot query GPU utilization")
        return {}
    except Exception as e:
        logger.warning(f"Failed to query GPU utilization: {e}")
        return {}


async def get_gpu_info() -> dict[int, dict[str, Any]]:
    """Get comprehensive GPU info.

    Returns:
        Dict mapping GPU ID to dict with memory_free_gb, memory_total_gb, utilization_pct
    """
    return await asyncio.get_event_loop().run_in_executor(
        None, _get_gpu_info_sync
    )


def _get_gpu_info_sync() -> dict[int, dict[str, Any]]:
    """Synchronous implementation of comprehensive GPU query."""
    try:
        import pynvml

        pynvml.nvmlInit()
        result = {}

        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)

                result[i] = {
                    "memory_free_gb": memory.free / (1024**3),
                    "memory_total_gb": memory.total / (1024**3),
                    "memory_used_gb": memory.used / (1024**3),
                    "utilization_pct": float(util.gpu),
                }
        finally:
            pynvml.nvmlShutdown()

        return result

    except ImportError:
        logger.warning("pynvml not available, cannot query GPU info")
        return {}
    except Exception as e:
        logger.warning(f"Failed to query GPU info: {e}")
        return {}
