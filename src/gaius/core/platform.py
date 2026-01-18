"""Platform detection and configuration for Gaius.

Provides utilities for detecting the current platform (CUDA/Tinybox vs MLX/Apple Silicon)
and loading appropriate configurations.

Platform is determined by:
1. GAIUS_PLATFORM environment variable (explicit override)
2. Auto-detection based on hardware availability

Supported platforms:
- cuda: NVIDIA GPU with CUDA (default for Linux)
- mlx: Apple Silicon with MLX (default for macOS)
"""

import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Platform(Enum):
    """Supported Gaius platforms."""

    CUDA = "cuda"  # NVIDIA GPU via vLLM
    MLX = "mlx"  # Apple Silicon via exo/MLX


@dataclass
class PlatformInfo:
    """Detected platform information."""

    platform: Platform
    is_darwin: bool
    is_linux: bool
    has_cuda: bool
    has_mlx: bool
    gpu_count: int
    unified_memory_gb: Optional[int]  # Apple Silicon unified memory
    chip_name: Optional[str]  # e.g., "Apple M3 Max"

    @property
    def is_mlx(self) -> bool:
        """Check if running on MLX platform."""
        return self.platform == Platform.MLX

    @property
    def is_cuda(self) -> bool:
        """Check if running on CUDA platform."""
        return self.platform == Platform.CUDA


def detect_platform() -> PlatformInfo:
    """Detect the current platform and hardware capabilities.

    Returns:
        PlatformInfo with detected platform and capabilities
    """
    is_darwin = platform.system() == "Darwin"
    is_linux = platform.system() == "Linux"

    # Check for explicit override
    env_platform = os.environ.get("GAIUS_PLATFORM", "").lower()

    # Detect CUDA
    has_cuda = _detect_cuda()
    gpu_count = _count_gpus() if has_cuda else 0

    # Detect MLX (Apple Silicon)
    has_mlx = _detect_mlx() if is_darwin else False
    unified_memory_gb = _detect_unified_memory() if is_darwin else None
    chip_name = _detect_apple_chip() if is_darwin else None

    # Determine platform
    if env_platform == "mlx":
        detected_platform = Platform.MLX
    elif env_platform == "cuda":
        detected_platform = Platform.CUDA
    elif is_darwin and has_mlx:
        detected_platform = Platform.MLX
    elif has_cuda:
        detected_platform = Platform.CUDA
    else:
        # Default to CUDA for backwards compatibility
        detected_platform = Platform.CUDA
        logger.warning(
            "No GPU detected. Defaulting to CUDA platform. "
            "Set GAIUS_PLATFORM=mlx for Apple Silicon."
        )

    info = PlatformInfo(
        platform=detected_platform,
        is_darwin=is_darwin,
        is_linux=is_linux,
        has_cuda=has_cuda,
        has_mlx=has_mlx,
        gpu_count=gpu_count,
        unified_memory_gb=unified_memory_gb,
        chip_name=chip_name,
    )

    logger.info(f"Detected platform: {info.platform.value}")
    if info.is_cuda:
        logger.info(f"  CUDA GPUs: {info.gpu_count}")
    if info.is_mlx:
        logger.info(f"  Apple Silicon: {info.chip_name}")
        logger.info(f"  Unified Memory: {info.unified_memory_gb}GB")

    return info


def _detect_cuda() -> bool:
    """Check if CUDA is available."""
    # Check for nvidia-smi
    if shutil.which("nvidia-smi") is None:
        return False

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _count_gpus() -> int:
    """Count available NVIDIA GPUs."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return len(result.stdout.strip().split("\n"))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return 0


def _detect_mlx() -> bool:
    """Check if MLX is available on Apple Silicon."""
    # Check for Apple Silicon
    if platform.machine() not in ("arm64", "aarch64"):
        return False

    # Try to import mlx
    try:
        import mlx.core  # noqa: F401

        return True
    except ImportError:
        pass

    # Check if Metal is available (backup check)
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "Metal" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _detect_unified_memory() -> Optional[int]:
    """Detect Apple Silicon unified memory in GB."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            bytes_mem = int(result.stdout.strip())
            return bytes_mem // (1024 * 1024 * 1024)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        pass
    return None


def _detect_apple_chip() -> Optional[str]:
    """Detect Apple Silicon chip name."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def get_platform_config_path(platform_id: str) -> str:
    """Get the platform-specific config file path.

    Args:
        platform_id: Platform identifier ("cuda" or "mlx")

    Returns:
        Config file name (e.g., "agents-cuda.conf")
    """
    return f"agents-{platform_id}.conf"


def validate_platform_compatibility(info: PlatformInfo) -> list[str]:
    """Validate that the platform can run Gaius.

    Args:
        info: Detected platform info

    Returns:
        List of warning messages (empty if all checks pass)
    """
    warnings: list[str] = []

    if info.is_cuda and info.gpu_count == 0:
        warnings.append(
            "CUDA platform selected but no GPUs detected. "
            "Install NVIDIA drivers or set GAIUS_PLATFORM=mlx."
        )

    if info.is_mlx and not info.has_mlx:
        warnings.append(
            "MLX platform selected but MLX not available. "
            "Install MLX with: pip install mlx"
        )

    if info.is_mlx and info.unified_memory_gb and info.unified_memory_gb < 16:
        warnings.append(
            f"Only {info.unified_memory_gb}GB unified memory detected. "
            "16GB+ recommended for MLX inference."
        )

    if info.is_cuda and info.gpu_count < 2:
        warnings.append(
            f"Only {info.gpu_count} GPU(s) detected. "
            "Some agents (orchestrator, reasoning) require multiple GPUs."
        )

    return warnings


# Cached platform info
_platform_info: Optional[PlatformInfo] = None


def get_platform_info() -> PlatformInfo:
    """Get cached platform info, detecting if not already done."""
    global _platform_info
    if _platform_info is None:
        _platform_info = detect_platform()
    return _platform_info


def reset_platform_cache() -> None:
    """Reset platform cache (for testing)."""
    global _platform_info
    _platform_info = None
