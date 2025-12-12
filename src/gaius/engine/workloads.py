"""Workload request infrastructure for GPU resource management.

Implements Yunikorn-style workload declarations where applications (init, swarm)
request capabilities and resources, and the engine allocates/preempts endpoints
to satisfy makespan requirements.

Usage:
    from gaius.engine.workloads import WorkloadRequest, WorkloadType

    # Request embedding capability for init
    request = WorkloadRequest(
        workload_id="init-2024-12-11-001",
        workload_type=WorkloadType.INIT,
        required_capabilities=[TaskType.TEXT_EMBEDDING],
        priority=JobPriority.CRITICAL,
        estimated_duration_s=300,
        estimated_memory_mb=2000,
    )
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gaius.models.registry import TaskType

from .services.scheduler_service import JobPriority


class WorkloadType(Enum):
    """Types of workloads that request GPU resources.

    Maps to Yunikorn "applications" concept - each type has
    different resource patterns and priority behaviors.
    """

    INIT = auto()  # KB indexing, projection, TDA
    SWARM = auto()  # Multi-agent swarm analysis
    INFERENCE = auto()  # Single inference request
    EMBEDDING = auto()  # Embedding generation
    EVOLUTION = auto()  # Agent evolution/optimization


@dataclass
class ResourceRequirements:
    """Resource requirements for a model or workload.

    Attributes:
        num_gpus: Number of GPUs required
        memory_mb: GPU memory required in megabytes
        cpu_cores: CPU cores (for CPU-only workloads)
        qdrant_active: Whether Qdrant is actively being used
    """

    num_gpus: int = 1
    memory_mb: int = 0
    cpu_cores: int = 0
    qdrant_active: bool = False  # Future: Qdrant GPU acceleration


@dataclass
class WorkloadRequest:
    """A request for GPU resources to fulfill a workload.

    Yunikorn-style workload declaration that specifies what capabilities
    are needed rather than specific endpoints. The engine routes to
    appropriate models and manages preemption/restoration.

    Attributes:
        workload_id: Unique identifier (e.g., "init-2024-12-11-001")
        workload_type: Type of workload (INIT, SWARM, etc.)
        required_capabilities: List of TaskType capabilities needed
        priority: Job priority for preemption decisions
        estimated_duration_s: Estimated duration for makespan planning
        estimated_memory_mb: GPU memory required (0 for CPU-only)
        preemptible: Whether this workload can be preempted
        metadata: Additional workload-specific data
    """

    workload_id: str
    workload_type: WorkloadType
    required_capabilities: list["TaskType"]
    priority: JobPriority
    estimated_duration_s: int
    estimated_memory_mb: int
    preemptible: bool = True
    metadata: dict = field(default_factory=dict)

    # Timestamps for tracking
    submitted_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_gpu_workload(self) -> bool:
        """Check if this workload requires GPU resources."""
        return self.estimated_memory_mb > 0

    @property
    def duration_ms(self) -> int | None:
        """Get actual duration in milliseconds if completed."""
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return None


@dataclass
class EndpointAllocation:
    """Allocation of an endpoint to a capability.

    Attributes:
        endpoint_name: Name of the allocated endpoint
        capability: The TaskType capability it provides
        port: Port the endpoint is running on
        healthy: Whether the endpoint is healthy
        model_id: The model being served
    """

    endpoint_name: str
    capability: "TaskType"
    port: int
    healthy: bool
    model_id: str


@dataclass
class WorkloadResult:
    """Result of workload resource allocation.

    Returned by begin_workload() to indicate whether resources were
    successfully allocated and what endpoints/endpoints were affected.

    Attributes:
        success: Whether allocation succeeded
        workload_id: ID of the workload
        allocated_endpoints: Mapping of capability to endpoint allocation
        evicted_endpoints: Endpoints stopped to make room
        restore_plan: Endpoints to restart after workload completes
        error: Error message if allocation failed
        wait_time_ms: Time spent waiting for resources
    """

    success: bool
    workload_id: str
    allocated_endpoints: dict["TaskType", EndpointAllocation] = field(default_factory=dict)
    evicted_endpoints: list[str] = field(default_factory=list)
    restore_plan: list[str] = field(default_factory=list)
    error: str | None = None
    wait_time_ms: int = 0

    def get_endpoint_url(self, capability: "TaskType") -> str | None:
        """Get URL for an allocated endpoint by capability.

        Args:
            capability: The TaskType to get endpoint for

        Returns:
            URL string like "http://localhost:8001" or None
        """
        alloc = self.allocated_endpoints.get(capability)
        if alloc and alloc.healthy:
            return f"http://localhost:{alloc.port}"
        return None


@dataclass
class ActiveWorkload:
    """A currently active workload being tracked.

    Used by the orchestrator to track in-flight workloads for
    resource accounting and restore planning.

    Attributes:
        request: The original workload request
        result: The allocation result
        started_at: When the workload started executing
    """

    request: WorkloadRequest
    result: WorkloadResult
    started_at: datetime = field(default_factory=datetime.now)

    @property
    def elapsed_s(self) -> float:
        """Seconds since workload started."""
        return (datetime.now() - self.started_at).total_seconds()

    @property
    def is_overdue(self) -> bool:
        """Check if workload has exceeded estimated duration."""
        return self.elapsed_s > self.request.estimated_duration_s


# Default memory estimates for common models (MB)
DEFAULT_MEMORY_ESTIMATES = {
    # Embedding models
    "all-MiniLM-L6-v2": 500,
    "nomic-ai/nomic-embed-text-v1": 800,
    "nomic-ai/nomic-embed-vision-v1": 1200,
    # Vision-language models
    "TIGER-Lab/ColQwen2-7B": 7000,
    # Orchestration models
    "nvidia/Orchestrator-8B": 8000,
    # Reasoning models (TP=4)
    "Qwen/QwQ-32B": 80000,
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B": 80000,
    # Coding models
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": 20000,
    "mistralai/Devstral-Small-2-24B-Instruct-2512": 15000,
}


def estimate_memory_mb(model_id: str, parameters_b: float | None = None) -> int:
    """Estimate GPU memory requirements for a model.

    Args:
        model_id: HuggingFace model ID
        parameters_b: Model parameters in billions (optional)

    Returns:
        Estimated GPU memory in MB
    """
    # Check known models first
    if model_id in DEFAULT_MEMORY_ESTIMATES:
        return DEFAULT_MEMORY_ESTIMATES[model_id]

    # Estimate based on parameters (roughly 2 bytes/param for fp16)
    if parameters_b:
        # Add ~20% overhead for KV cache, activations
        return int(parameters_b * 2 * 1024 * 1.2)

    # Default conservative estimate
    return 8000
