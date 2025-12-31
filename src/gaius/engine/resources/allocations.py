"""GPU allocation tracking dataclasses.

Tracks GPU assignments for models, supporting multi-GPU tensor-parallel
configurations and gang scheduling.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AllocationState(Enum):
    """State of a GPU allocation."""

    PENDING = "pending"  # Requested but not yet allocated
    ALLOCATED = "allocated"  # GPUs reserved, model loading
    ACTIVE = "active"  # Model loaded and serving
    RELEASING = "releasing"  # Model unloading
    FAILED = "failed"  # Allocation or startup failed


@dataclass
class GPUAllocation:
    """Tracks GPU assignment for a model.

    Attributes:
        agent_alias: Agent this allocation is for (e.g., "orchestrator")
        model: Model identifier (e.g., "nvidia/Orchestrator-8B")
        gpu_ids: List of GPU IDs allocated (e.g., [0, 1] for tensor-parallel)
        vram_reserved_gb: Amount of VRAM reserved per GPU
        state: Current allocation state
        started_at: When allocation was created
        activated_at: When model became ready to serve
        endpoint_port: Port where vLLM is serving (if active)
        process_pid: PID of the vLLM process (for orphan detection)
        error_message: Error details if state is FAILED
    """

    agent_alias: str
    model: str
    gpu_ids: list[int]
    vram_reserved_gb: float
    state: AllocationState = AllocationState.PENDING
    started_at: datetime = field(default_factory=datetime.now)
    activated_at: Optional[datetime] = None
    endpoint_port: Optional[int] = None
    process_pid: Optional[int] = None
    error_message: Optional[str] = None

    @property
    def num_gpus(self) -> int:
        """Number of GPUs allocated."""
        return len(self.gpu_ids)

    @property
    def is_active(self) -> bool:
        """Whether allocation is actively serving."""
        return self.state == AllocationState.ACTIVE

    @property
    def is_usable(self) -> bool:
        """Whether allocation can accept requests."""
        return self.state in (AllocationState.ALLOCATED, AllocationState.ACTIVE)

    def mark_active(self, port: int, pid: int | None = None) -> None:
        """Mark allocation as active with serving port and process PID.

        Args:
            port: Port where vLLM is serving
            pid: PID of the vLLM process (for orphan detection)
        """
        self.state = AllocationState.ACTIVE
        self.activated_at = datetime.now()
        self.endpoint_port = port
        self.process_pid = pid

    def mark_failed(self, error: str) -> None:
        """Mark allocation as failed with error."""
        self.state = AllocationState.FAILED
        self.error_message = error

    def mark_releasing(self) -> None:
        """Mark allocation as releasing."""
        self.state = AllocationState.RELEASING

    def is_process_alive(self) -> bool:
        """Check if the tracked vLLM process is still running.

        Returns:
            True if process is running, False if dead or no PID tracked.
            Used by reconciliation to detect orphaned allocations.
        """
        if self.process_pid is None:
            return False
        try:
            import os
            # os.kill with signal 0 doesn't kill but checks if process exists
            os.kill(self.process_pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we don't have permission (shouldn't happen)
            return True

    def is_orphaned(self) -> bool:
        """Check if allocation is orphaned (active but process dead).

        An orphaned allocation indicates the vLLM process crashed or was killed
        without going through proper cleanup. Reconciliation should restart these.

        Returns:
            True if allocation is active/allocated but process is dead.
        """
        if self.state not in (AllocationState.ACTIVE, AllocationState.ALLOCATED):
            return False
        # If no PID tracked, we can't determine orphan status
        if self.process_pid is None:
            return False
        return not self.is_process_alive()


@dataclass
class GPUStatus:
    """Current status of a single GPU.

    Attributes:
        gpu_id: GPU index (0-5)
        total_vram_gb: Total VRAM capacity
        used_vram_gb: Currently used VRAM
        temperature_c: GPU temperature in Celsius
        utilization_pct: GPU compute utilization percentage
        allocated_to: Agent alias if allocated, None if free
        is_reserved: True if GPU is in reserved list
    """

    gpu_id: int
    total_vram_gb: float
    used_vram_gb: float = 0.0
    temperature_c: int = 0
    utilization_pct: float = 0.0
    allocated_to: Optional[str] = None
    is_reserved: bool = False

    @property
    def free_vram_gb(self) -> float:
        """Available VRAM."""
        return self.total_vram_gb - self.used_vram_gb

    @property
    def is_free(self) -> bool:
        """Whether GPU is available for allocation."""
        return self.allocated_to is None and not self.is_reserved


@dataclass
class AllocationRequest:
    """Request to allocate GPUs for an agent.

    Attributes:
        agent_alias: Agent requesting allocation
        model: Model to load
        num_gpus: Number of GPUs required
        vram_per_gpu_gb: VRAM required per GPU
        prefer_contiguous: Prefer contiguous GPU IDs (better for NVLink)
        priority: Request priority (higher = more important)
        timeout_seconds: How long to wait for resources
    """

    agent_alias: str
    model: str
    num_gpus: int = 1
    vram_per_gpu_gb: float = 16.0
    prefer_contiguous: bool = True
    priority: int = 0
    timeout_seconds: int = 30


@dataclass
class AllocationResult:
    """Result of an allocation request.

    Attributes:
        success: Whether allocation succeeded
        allocation: The GPUAllocation if successful
        error: Error message if failed
        wait_time_ms: How long the request waited
    """

    success: bool
    allocation: Optional[GPUAllocation] = None
    error: Optional[str] = None
    wait_time_ms: int = 0


class ResourceUnavailable(Exception):
    """Raised when requested resources cannot be allocated."""

    def __init__(self, message: str, required_gpus: int = 0, available_gpus: int = 0):
        super().__init__(message)
        self.required_gpus = required_gpus
        self.available_gpus = available_gpus
