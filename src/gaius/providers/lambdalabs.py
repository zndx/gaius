"""Lambda Labs GPU Cloud client.

Provides access to Lambda Labs API for:
- Querying available instance types and specs
- Checking real-time availability
- Suggesting appropriate instances for model requirements

Usage:
    from gaius.providers.lambdalabs import LambdaLabsClient

    client = LambdaLabsClient()
    instances = await client.get_instance_types()
    suggestion = client.suggest_instance_for_model(vram_required_gb=430)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


@dataclass
class InstanceType:
    """Lambda Labs GPU instance specification."""

    name: str
    gpu_model: str
    gpu_count: int
    vram_per_gpu_gb: int
    total_vram_gb: int
    vcpus: int
    ram_gb: int
    storage_tb: float
    price_per_gpu_hr: float

    @property
    def total_price_hr(self) -> float:
        """Total hourly price for the instance."""
        return self.price_per_gpu_hr * self.gpu_count

    def can_run_model(self, vram_required_gb: float, min_tp: int = 1) -> bool:
        """Check if this instance can run a model with given requirements."""
        return self.total_vram_gb >= vram_required_gb and self.gpu_count >= min_tp


@dataclass
class InstanceAvailability:
    """Real-time availability for an instance type."""

    instance_type: str
    regions: list[str] = field(default_factory=list)
    available: bool = False


# Static instance data (fallback when API unavailable)
# Updated from https://lambda.ai/instances (2025-12-11)
STATIC_INSTANCES: list[InstanceType] = [
    # 8x GPU instances
    InstanceType("gpu_8x_b200_sxm6", "B200 SXM6", 8, 180, 1440, 208, 2900, 22, 4.99),
    InstanceType("gpu_8x_h100_sxm", "H100 SXM", 8, 80, 640, 208, 1800, 22, 2.99),
    InstanceType("gpu_8x_a100_80gb_sxm", "A100 SXM 80GB", 8, 80, 640, 240, 1800, 19.5, 1.79),
    InstanceType("gpu_8x_a100_40gb_sxm", "A100 SXM 40GB", 8, 40, 320, 124, 1800, 5.8, 1.29),
    InstanceType("gpu_8x_v100", "V100", 8, 16, 128, 88, 448, 5.8, 0.55),
    # 4x GPU instances
    InstanceType("gpu_4x_h100_sxm", "H100 SXM", 4, 80, 320, 104, 900, 11, 3.09),
    InstanceType("gpu_4x_a100_pcie", "A100 PCIe 40GB", 4, 40, 160, 120, 900, 1, 1.29),
    InstanceType("gpu_4x_a6000", "A6000", 4, 48, 192, 56, 400, 1, 0.80),
    # 2x GPU instances
    InstanceType("gpu_2x_h100_sxm", "H100 SXM", 2, 80, 160, 52, 450, 5.5, 3.19),
    InstanceType("gpu_2x_a100_pcie", "A100 PCIe 40GB", 2, 40, 80, 60, 450, 1, 1.29),
    InstanceType("gpu_2x_a6000", "A6000", 2, 48, 96, 28, 200, 1, 0.80),
    # 1x GPU instances
    InstanceType("gpu_1x_gh200", "GH200", 1, 96, 96, 64, 432, 4, 1.49),
    InstanceType("gpu_1x_h100_sxm", "H100 SXM", 1, 80, 80, 26, 225, 2.75, 3.29),
    InstanceType("gpu_1x_h100_pcie", "H100 PCIe", 1, 80, 80, 26, 225, 1, 2.49),
    InstanceType("gpu_1x_a100_sxm", "A100 SXM 40GB", 1, 40, 40, 30, 220, 0.5, 1.29),
    InstanceType("gpu_1x_a100_pcie", "A100 PCIe 40GB", 1, 40, 40, 30, 225, 0.5, 1.29),
    InstanceType("gpu_1x_a10", "A10", 1, 24, 24, 30, 226, 1.3, 0.75),
    InstanceType("gpu_1x_a6000", "A6000", 1, 48, 48, 14, 100, 0.5, 0.80),
    InstanceType("gpu_1x_rtx6000", "RTX 6000", 1, 24, 24, 14, 46, 0.5, 0.50),
]


class LambdaLabsClient:
    """Client for Lambda Labs GPU Cloud API."""

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        """Initialize Lambda Labs client.

        Args:
            api_key: Lambda Labs API key (uses config/env if not provided)
            api_base: API base URL (uses config/env if not provided)
        """
        self._api_key = api_key
        self._api_base = api_base

    @property
    def api_key(self) -> str:
        """Get API key from config or environment."""
        if self._api_key:
            return self._api_key

        try:
            from ..core.config import get_config
            config = get_config()
            if config.providers.lambdalabs.api_key:
                return config.providers.lambdalabs.api_key
        except Exception:
            pass

        import os
        return os.getenv("LAMBDA_API_KEY", "")

    @property
    def api_base(self) -> str:
        """Get API base URL from config or default."""
        if self._api_base:
            return self._api_base

        try:
            from ..core.config import get_config
            config = get_config()
            return config.providers.lambdalabs.api_base
        except Exception:
            return "https://cloud.lambdalabs.com/api/v1"

    @property
    def has_api_key(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    async def get_instance_types(self) -> list[InstanceType]:
        """Get available instance types with specs.

        Returns API data if authenticated, otherwise returns static data.
        """
        if not self.has_api_key:
            logger.debug("No Lambda API key - using static instance data")
            return STATIC_INSTANCES

        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.api_base}/instance-types",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()

                instances = []
                for name, info in data.get("data", {}).items():
                    inst_type = info.get("instance_type", {})
                    specs = inst_type.get("specs", {})

                    # Parse GPU count from specs
                    gpu_count = specs.get("gpus", 0)

                    # Parse GPU model and VRAM from description (e.g., "GH200 (96 GB)")
                    gpu_desc = inst_type.get("gpu_description", "")
                    gpu_model = gpu_desc.split("(")[0].strip() if gpu_desc else "unknown"

                    # Extract VRAM from description (e.g., "A100 (80 GB SXM4)")
                    import re
                    vram_match = re.search(r"\((\d+)\s*GB", gpu_desc)
                    vram_per_gpu = int(vram_match.group(1)) if vram_match else 0

                    # Price is in cents per hour for the whole instance
                    price_cents = inst_type.get("price_cents_per_hour", 0)
                    price_per_gpu = (price_cents / 100) / max(gpu_count, 1)

                    instances.append(InstanceType(
                        name=name,
                        gpu_model=gpu_model,
                        gpu_count=gpu_count,
                        vram_per_gpu_gb=vram_per_gpu,
                        total_vram_gb=vram_per_gpu * gpu_count,
                        vcpus=specs.get("vcpus", 0),
                        ram_gb=specs.get("memory_gib", 0),
                        storage_tb=specs.get("storage_gib", 0) / 1024,
                        price_per_gpu_hr=price_per_gpu,
                    ))
                return instances if instances else STATIC_INSTANCES

        except Exception as e:
            logger.warning(f"Lambda API error: {e} - using static data")
            return STATIC_INSTANCES

    async def get_availability(self) -> list[InstanceAvailability]:
        """Get real-time instance availability by region.

        Requires API key - returns empty list if not authenticated.
        """
        if not self.has_api_key:
            return []

        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.api_base}/instance-types",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()

                availability = []
                for name, info in data.get("data", {}).items():
                    regions = list(info.get("regions_with_capacity_available", []))
                    availability.append(InstanceAvailability(
                        instance_type=name,
                        regions=regions,
                        available=len(regions) > 0,
                    ))
                return availability

        except Exception as e:
            logger.warning(f"Lambda availability check failed: {e}")
            return []

    def suggest_instances_for_model(
        self,
        vram_required_gb: float,
        min_tensor_parallel: int = 1,
        max_suggestions: int = 3,
    ) -> list[tuple[InstanceType, float]]:
        """Suggest Lambda instances that can run a model.

        Args:
            vram_required_gb: Required VRAM in GB
            min_tensor_parallel: Minimum GPUs needed for tensor parallelism
            max_suggestions: Maximum number of suggestions to return

        Returns:
            List of (instance, hourly_cost) tuples, sorted by cost
        """
        candidates = []
        for instance in STATIC_INSTANCES:
            if instance.can_run_model(vram_required_gb, min_tensor_parallel):
                candidates.append((instance, instance.total_price_hr))

        # Sort by cost
        candidates.sort(key=lambda x: x[1])
        return candidates[:max_suggestions]

    async def find_best_available_instance(
        self,
        vram_required_gb: float,
        min_tensor_parallel: int = 1,
    ) -> tuple[InstanceType, list[str], float] | None:
        """Find the cheapest currently available instance that meets requirements.

        Args:
            vram_required_gb: Required VRAM in GB
            min_tensor_parallel: Minimum GPUs needed for tensor parallelism

        Returns:
            Tuple of (instance, regions, hourly_cost) or None if nothing available
        """
        # Get live availability
        availability = await self.get_availability()
        available_names = {
            a.instance_type: [
                r["description"] if isinstance(r, dict) else r
                for r in a.regions
            ]
            for a in availability if a.available
        }

        if not available_names:
            # No API access or nothing available - fall back to static suggestions
            suggestions = self.suggest_instances_for_model(vram_required_gb, min_tensor_parallel, 1)
            if suggestions:
                inst, cost = suggestions[0]
                return (inst, ["(check availability)"], cost)
            return None

        # Get instance specs (prefer live data)
        instances = await self.get_instance_types()
        instance_map = {i.name: i for i in instances}

        # Find candidates that are both capable and available
        candidates = []
        for name, regions in available_names.items():
            instance = instance_map.get(name)
            if instance and instance.can_run_model(vram_required_gb, min_tensor_parallel):
                candidates.append((instance, regions, instance.total_price_hr))

        if not candidates:
            return None

        # Sort by cost and return cheapest
        candidates.sort(key=lambda x: x[2])
        return candidates[0]

    def format_suggestions_markdown(
        self,
        vram_required_gb: float,
        min_tensor_parallel: int = 1,
    ) -> str:
        """Format instance suggestions as markdown.

        Args:
            vram_required_gb: Required VRAM in GB
            min_tensor_parallel: Minimum GPUs needed

        Returns:
            Markdown formatted suggestion text
        """
        suggestions = self.suggest_instances_for_model(
            vram_required_gb, min_tensor_parallel
        )

        if not suggestions:
            return "No Lambda Labs instances available for this model size."

        lines = ["## Cloud Options (Lambda Labs)", ""]
        lines.append("| Instance | GPUs | VRAM | Cost/hr |")
        lines.append("|----------|------|------|---------|")

        for instance, cost in suggestions:
            lines.append(
                f"| {instance.name} | {instance.gpu_count}x {instance.gpu_model} | "
                f"{instance.total_vram_gb}GB | ${cost:.2f} |"
            )

        lines.append("")
        lines.append(f"*Requires ~{vram_required_gb:.0f}GB VRAM, TP>={min_tensor_parallel}*")

        return "\n".join(lines)
