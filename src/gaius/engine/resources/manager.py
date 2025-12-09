"""Resource manager for GPU allocation and tracking.

Manages GPU inventory, allocations, and scheduling for multi-GPU
tensor-parallel configurations.

Supports dynamic GPU swapping for transitioning between:
- Default state: orchestrator + fast + fast-2 + coding (6 GPUs)
- Reasoning state: orchestrator + reasoning (6 GPUs)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..config import AgentConfig, EngineConfig
from .allocations import (
    AllocationRequest,
    AllocationResult,
    AllocationState,
    GPUAllocation,
    GPUStatus,
    ResourceUnavailable,
)

logger = logging.getLogger(__name__)


@dataclass
class SwapPlan:
    """Plan for swapping GPU allocations between endpoints."""

    endpoints_to_stop: list[str] = field(default_factory=list)
    endpoints_to_start: list[str] = field(default_factory=list)
    gpus_to_free: list[int] = field(default_factory=list)
    gpus_to_allocate: dict[str, list[int]] = field(default_factory=dict)
    reason: str = ""
    estimated_duration_s: int = 120  # Default 2 minutes for model loading


class ResourceManager:
    """Manages GPU inventory and allocations.

    Tracks which GPUs are allocated to which agents, handles allocation
    requests with priority queuing, and supports gang scheduling for
    multi-GPU models.
    """

    def __init__(self, config: EngineConfig):
        """Initialize resource manager.

        Args:
            config: Engine configuration with GPU inventory
        """
        self.config = config
        self.total_gpus = config.gpus.total
        self.reserved_gpus = set(config.gpus.reserved)
        self.prefer_contiguous = config.scheduling.prefer_contiguous
        self.allocation_timeout = config.scheduling.allocation_timeout

        # Track allocations by agent alias
        self.allocations: dict[str, GPUAllocation] = {}

        # GPU status cache (updated by health service)
        self._gpu_status: dict[int, GPUStatus] = {}

        # Pending allocation requests (priority queue)
        self._pending_requests: list[AllocationRequest] = []
        self._request_events: dict[str, asyncio.Event] = {}

        # Initialize GPU status
        self._init_gpu_status()

        logger.info(
            f"ResourceManager initialized: {self.total_gpus} GPUs, "
            f"{len(self.reserved_gpus)} reserved"
        )

    def _init_gpu_status(self) -> None:
        """Initialize GPU status entries."""
        for gpu_id in range(self.total_gpus):
            self._gpu_status[gpu_id] = GPUStatus(
                gpu_id=gpu_id,
                total_vram_gb=24.0,  # Default, updated by health service
                is_reserved=gpu_id in self.reserved_gpus,
            )

    def get_free_gpus(self) -> list[int]:
        """Get list of unallocated, unreserved GPU IDs.

        Returns:
            Sorted list of available GPU IDs
        """
        allocated_gpus = set()
        for alloc in self.allocations.values():
            if alloc.state not in (AllocationState.FAILED, AllocationState.RELEASING):
                allocated_gpus.update(alloc.gpu_ids)

        free = []
        for gpu_id in range(self.total_gpus):
            if gpu_id not in allocated_gpus and gpu_id not in self.reserved_gpus:
                free.append(gpu_id)

        return sorted(free)

    def can_allocate(self, agent_config: AgentConfig) -> bool:
        """Check if resources available for agent.

        Args:
            agent_config: Agent configuration with resource requirements

        Returns:
            True if allocation is possible
        """
        required = agent_config.resources.gpus
        free = self.get_free_gpus()
        return len(free) >= required

    def _select_gpus(self, free_gpus: list[int], count: int) -> list[int]:
        """Select GPUs for allocation, preferring contiguous IDs.

        Args:
            free_gpus: Available GPU IDs
            count: Number of GPUs needed

        Returns:
            Selected GPU IDs
        """
        if not self.prefer_contiguous or count == 1:
            return free_gpus[:count]

        # Try to find contiguous sequence
        free_set = set(free_gpus)
        for start in free_gpus:
            contiguous = []
            for i in range(count):
                if (start + i) in free_set:
                    contiguous.append(start + i)
                else:
                    break
            if len(contiguous) == count:
                return contiguous

        # Fall back to first available
        return free_gpus[:count]

    def allocate(self, agent_alias: str, agent_config: AgentConfig) -> GPUAllocation:
        """Allocate GPUs for agent synchronously.

        Args:
            agent_alias: Agent identifier
            agent_config: Agent configuration with resource requirements

        Returns:
            GPUAllocation with assigned GPU IDs

        Raises:
            ResourceUnavailable: If not enough GPUs available
        """
        required = agent_config.resources.gpus
        free_gpus = self.get_free_gpus()

        if len(free_gpus) < required:
            raise ResourceUnavailable(
                f"Need {required} GPUs, only {len(free_gpus)} free",
                required_gpus=required,
                available_gpus=len(free_gpus),
            )

        # Select GPUs (prefer contiguous for NVLink)
        selected = self._select_gpus(free_gpus, required)

        # Create allocation
        allocation = GPUAllocation(
            agent_alias=agent_alias,
            model=agent_config.model,
            gpu_ids=selected,
            vram_reserved_gb=agent_config.resources.vram_gb,
            state=AllocationState.ALLOCATED,
        )

        self.allocations[agent_alias] = allocation

        # Update GPU status
        for gpu_id in selected:
            if gpu_id in self._gpu_status:
                self._gpu_status[gpu_id].allocated_to = agent_alias

        logger.info(
            f"Allocated GPUs {selected} for {agent_alias} "
            f"({agent_config.model}, {agent_config.resources.vram_gb}GB)"
        )

        return allocation

    async def allocate_async(
        self, request: AllocationRequest
    ) -> AllocationResult:
        """Allocate GPUs with async waiting if needed.

        Args:
            request: Allocation request with requirements

        Returns:
            AllocationResult with success status and allocation
        """
        start_time = datetime.now()

        # Check if agent config exists
        if request.agent_alias not in self.config.agents:
            return AllocationResult(
                success=False,
                error=f"Unknown agent: {request.agent_alias}",
            )

        agent_config = self.config.agents[request.agent_alias]

        # Try immediate allocation
        try:
            allocation = self.allocate(request.agent_alias, agent_config)
            wait_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return AllocationResult(
                success=True,
                allocation=allocation,
                wait_time_ms=wait_ms,
            )
        except ResourceUnavailable:
            pass

        # Queue request and wait
        self._pending_requests.append(request)
        self._pending_requests.sort(key=lambda r: -r.priority)

        event = asyncio.Event()
        self._request_events[request.agent_alias] = event

        try:
            await asyncio.wait_for(
                event.wait(),
                timeout=request.timeout_seconds,
            )

            # Check if allocation was made
            if request.agent_alias in self.allocations:
                allocation = self.allocations[request.agent_alias]
                wait_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                return AllocationResult(
                    success=True,
                    allocation=allocation,
                    wait_time_ms=wait_ms,
                )
            else:
                return AllocationResult(
                    success=False,
                    error="Allocation event fired but no allocation found",
                )

        except asyncio.TimeoutError:
            # Remove from pending
            self._pending_requests = [
                r for r in self._pending_requests
                if r.agent_alias != request.agent_alias
            ]
            return AllocationResult(
                success=False,
                error=f"Timeout waiting for {request.num_gpus} GPUs",
                wait_time_ms=request.timeout_seconds * 1000,
            )
        finally:
            self._request_events.pop(request.agent_alias, None)

    def release(self, agent_alias: str) -> bool:
        """Release GPUs when model unloaded.

        Args:
            agent_alias: Agent to release

        Returns:
            True if allocation was released
        """
        if agent_alias not in self.allocations:
            logger.warning(f"No allocation found for {agent_alias}")
            return False

        allocation = self.allocations[agent_alias]
        gpu_ids = allocation.gpu_ids

        # Update GPU status
        for gpu_id in gpu_ids:
            if gpu_id in self._gpu_status:
                self._gpu_status[gpu_id].allocated_to = None

        del self.allocations[agent_alias]

        logger.info(f"Released GPUs {gpu_ids} from {agent_alias}")

        # Try to satisfy pending requests
        self._process_pending_requests()

        return True

    def _process_pending_requests(self) -> None:
        """Try to satisfy pending allocation requests."""
        satisfied = []

        for request in self._pending_requests:
            if request.agent_alias in self.config.agents:
                agent_config = self.config.agents[request.agent_alias]
                try:
                    self.allocate(request.agent_alias, agent_config)
                    satisfied.append(request.agent_alias)

                    # Signal waiting coroutine
                    if request.agent_alias in self._request_events:
                        self._request_events[request.agent_alias].set()

                except ResourceUnavailable:
                    continue

        # Remove satisfied requests
        self._pending_requests = [
            r for r in self._pending_requests
            if r.agent_alias not in satisfied
        ]

    def get_allocation(self, agent_alias: str) -> Optional[GPUAllocation]:
        """Get allocation for agent.

        Args:
            agent_alias: Agent identifier

        Returns:
            GPUAllocation if exists, None otherwise
        """
        return self.allocations.get(agent_alias)

    def get_gpu_status(self, gpu_id: int) -> Optional[GPUStatus]:
        """Get status of a specific GPU.

        Args:
            gpu_id: GPU index

        Returns:
            GPUStatus if valid, None otherwise
        """
        return self._gpu_status.get(gpu_id)

    def update_gpu_status(
        self,
        gpu_id: int,
        vram_used_gb: float,
        temperature_c: int,
        utilization_pct: float,
    ) -> None:
        """Update GPU status from health service.

        Args:
            gpu_id: GPU index
            vram_used_gb: Current VRAM usage
            temperature_c: Current temperature
            utilization_pct: Current utilization
        """
        if gpu_id in self._gpu_status:
            status = self._gpu_status[gpu_id]
            status.used_vram_gb = vram_used_gb
            status.temperature_c = temperature_c
            status.utilization_pct = utilization_pct

    def get_summary(self) -> dict:
        """Get summary of resource state.

        Returns:
            Dict with allocation summary
        """
        free_gpus = self.get_free_gpus()
        active_allocations = [
            a for a in self.allocations.values()
            if a.state == AllocationState.ACTIVE
        ]

        return {
            "total_gpus": self.total_gpus,
            "reserved_gpus": list(self.reserved_gpus),
            "free_gpus": free_gpus,
            "active_allocations": len(active_allocations),
            "pending_requests": len(self._pending_requests),
            "allocations": {
                alias: {
                    "model": alloc.model,
                    "gpu_ids": alloc.gpu_ids,
                    "state": alloc.state.value,
                    "port": alloc.endpoint_port,
                }
                for alias, alloc in self.allocations.items()
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # GPU Swap Logic for Dynamic Model Transitions
    # ─────────────────────────────────────────────────────────────────────────

    def plan_swap_for_reasoning(self) -> SwapPlan:
        """Plan resource swap to enable 4-GPU reasoning model.

        Default state: orchestrator(2) + fast(1) + fast-2(1) + coding(2) = 6 GPUs
        Reasoning state: orchestrator(2) + reasoning(4) = 6 GPUs

        Returns:
            SwapPlan with endpoints to stop/start
        """
        # Reasoning needs 4 GPUs; we keep orchestrator (2 GPUs)
        # So we need to stop: coding (2) + fast (1) + fast-2 (1) = 4 GPUs

        endpoints_to_stop = []
        gpus_to_free = []

        # Check which endpoints are currently allocated
        for alias, alloc in self.allocations.items():
            if alias in ("coding", "fast", "fast-2"):
                endpoints_to_stop.append(alias)
                gpus_to_free.extend(alloc.gpu_ids)

        # If reasoning requires config, get the GPU count
        reasoning_config = self.config.agents.get("reasoning")
        reasoning_gpus = reasoning_config.resources.gpus if reasoning_config else 4

        return SwapPlan(
            endpoints_to_stop=endpoints_to_stop,
            endpoints_to_start=["reasoning"],
            gpus_to_free=gpus_to_free,
            gpus_to_allocate={"reasoning": gpus_to_free[:reasoning_gpus]},
            reason="Enable 4-GPU reasoning model",
            estimated_duration_s=180,  # 3 minutes for 32B model
        )

    def plan_restore_default(self) -> SwapPlan:
        """Plan restoration to default GPU state after reasoning completes.

        Reasoning state: orchestrator(2) + reasoning(4) = 6 GPUs
        Default state: orchestrator(2) + fast(1) + fast-2(1) + coding(2) = 6 GPUs

        Returns:
            SwapPlan to restore default endpoints
        """
        endpoints_to_stop = []
        gpus_to_free = []

        # Check if reasoning is allocated
        if "reasoning" in self.allocations:
            endpoints_to_stop.append("reasoning")
            gpus_to_free = list(self.allocations["reasoning"].gpu_ids)

        # Plan GPU allocation for default endpoints
        # coding: 2 GPUs, fast: 1 GPU, fast-2: 1 GPU
        gpus_to_allocate = {}
        if len(gpus_to_free) >= 4:
            gpus_to_allocate = {
                "coding": gpus_to_free[:2],
                "fast": [gpus_to_free[2]],
                "fast-2": [gpus_to_free[3]],
            }

        return SwapPlan(
            endpoints_to_stop=endpoints_to_stop,
            endpoints_to_start=["coding", "fast", "fast-2"],
            gpus_to_free=gpus_to_free,
            gpus_to_allocate=gpus_to_allocate,
            reason="Restore default endpoint configuration",
            estimated_duration_s=120,  # 2 minutes for smaller models
        )

    def can_execute_swap(self, plan: SwapPlan) -> tuple[bool, str]:
        """Check if a swap plan can be executed.

        Args:
            plan: SwapPlan to validate

        Returns:
            Tuple of (can_execute, reason)
        """
        # Check that endpoints to stop are actually allocated
        for endpoint in plan.endpoints_to_stop:
            if endpoint not in self.allocations:
                return (False, f"Endpoint {endpoint} not currently allocated")

        # Check that target GPUs will be available after stopping
        currently_used = set()
        for alias, alloc in self.allocations.items():
            if alias not in plan.endpoints_to_stop:
                currently_used.update(alloc.gpu_ids)

        gpus_after_stop = set(range(self.total_gpus)) - currently_used - self.reserved_gpus

        # Verify enough GPUs for new endpoints
        total_needed = sum(len(gpus) for gpus in plan.gpus_to_allocate.values())
        if len(gpus_after_stop) < total_needed:
            return (
                False,
                f"Need {total_needed} GPUs but only {len(gpus_after_stop)} available after stop",
            )

        return (True, "")

    def get_current_mode(self) -> str:
        """Determine current GPU allocation mode.

        Returns:
            "default" - fast/fast-2/coding endpoints active
            "reasoning" - reasoning endpoint active
            "mixed" - partial allocation
            "idle" - nothing allocated
        """
        active_endpoints = set(self.allocations.keys())

        if "reasoning" in active_endpoints:
            return "reasoning"
        elif {"fast", "fast-2", "coding"}.issubset(active_endpoints):
            return "default"
        elif active_endpoints:
            return "mixed"
        else:
            return "idle"
