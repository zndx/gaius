"""GPU-aware flow runner with orchestrator integration.

Manages GPU resources for flow execution by:
1. Requesting resources from the orchestrator before flow steps
2. Evicting idle vLLM endpoints to free GPU memory
3. Restoring evicted endpoints after flow completion

This enables docling (and other GPU-intensive flows) to run even when
vLLM endpoints are using all available GPU memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gaius.flows import GaiusFlow

logger = logging.getLogger(__name__)


@dataclass
class FlowRunResult:
    """Result of a flow run."""

    success: bool
    flow_name: str
    workload_id: str | None = None
    evicted_endpoints: list[str] | None = None
    restored_endpoints: list[str] | None = None
    output_path: str | None = None
    error: str | None = None
    duration_s: float = 0.0


async def request_gpu_resources(
    workload_id: str,
    estimated_memory_mb: int = 16000,
    estimated_duration_s: int = 300,
    priority: str = "high",
) -> tuple[bool, list[str]]:
    """Request GPU resources from the orchestrator.

    Attempts to allocate GPU resources for flow execution, evicting
    idle endpoints if necessary.

    Args:
        workload_id: Unique identifier for this flow run
        estimated_memory_mb: GPU memory required (default 16GB for docling)
        estimated_duration_s: Estimated run time in seconds
        priority: Job priority (critical, high, normal, low)

    Returns:
        Tuple of (success, list of evicted endpoint names)
    """
    try:
        from gaius.engine.workloads import WorkloadRequest, WorkloadType
        from gaius.engine.services.scheduler_service import JobPriority

        # Map priority string to enum
        priority_map = {
            "critical": JobPriority.CRITICAL,
            "high": JobPriority.HIGH,
            "normal": JobPriority.NORMAL,
            "low": JobPriority.LOW,
        }
        job_priority = priority_map.get(priority.lower(), JobPriority.HIGH)

        # Create workload request
        request = WorkloadRequest(
            workload_id=workload_id,
            workload_type=WorkloadType.FLOW,
            required_capabilities=[],  # No specific capabilities needed
            priority=job_priority,
            estimated_duration_s=estimated_duration_s,
            estimated_memory_mb=estimated_memory_mb,
            preemptible=False,  # Don't preempt flows
            metadata={"flow_type": "docling"},
        )

        # Try to connect to engine and request resources
        try:
            import grpc
            from gaius.engine.generated import gaius_service_pb2 as pb
            from gaius.engine.generated import gaius_service_pb2_grpc as grpc_stubs

            engine_addr = os.environ.get("GAIUS_ENGINE_ADDR", "localhost:50051")
            channel = grpc.aio.insecure_channel(engine_addr)
            stub = grpc_stubs.GaiusServiceStub(channel)

            # Request workload allocation
            req = pb.BeginWorkloadRequest(
                workload_id=workload_id,
                workload_type="FLOW",
                priority=priority.upper(),
                estimated_duration_s=estimated_duration_s,
                estimated_memory_mb=estimated_memory_mb,
            )

            # type: ignore[invalid-await] - grpc.aio stubs are awaitable at runtime
            # despite Union type hint in generated stubs
            response = await stub.BeginWorkload(req)  # type: ignore[misc] - grpc.aio stubs are awaitable at runtime despite Union type hint
            await channel.close(grace=None)

            if response.success:
                evicted = list(response.evicted_endpoints)
                logger.info(
                    f"Workload {workload_id} allocated, evicted: {evicted}"
                )
                return True, evicted
            else:
                logger.warning(f"Workload allocation failed: {response.error}")
                return False, []

        except Exception as e:
            logger.warning(f"Engine not available, using fallback: {e}")
            # Fallback: try to stop endpoints directly via CLI
            return await _fallback_evict_endpoints(estimated_memory_mb)

    except ImportError as e:
        logger.warning(f"Missing imports for GPU management: {e}")
        return False, []


def find_free_gpus(required_memory_mb: int) -> list[int]:
    """Find GPU indices with sufficient free memory.

    Args:
        required_memory_mb: Memory required in MB

    Returns:
        List of GPU indices with enough free memory
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        free_gpus = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split(",")
            if len(parts) == 2:
                gpu_idx = int(parts[0].strip())
                free_mb = int(parts[1].strip())
                if free_mb >= required_memory_mb:
                    free_gpus.append(gpu_idx)

        return free_gpus
    except Exception:
        return []


async def _fallback_evict_endpoints(required_memory_mb: int) -> tuple[bool, list[str]]:
    """Fallback: Stop low-priority endpoints to free GPU memory.

    Used when the gRPC engine is not available.

    Args:
        required_memory_mb: Memory required in MB

    Returns:
        Tuple of (success, list of stopped endpoint names)
    """
    evicted = []

    try:
        # Check current GPU memory usage
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, []

        # Check per-GPU free memory - we need enough on any single GPU
        free_per_gpu = [int(x.strip()) for x in result.stdout.strip().split("\n")]
        max_free = max(free_per_gpu) if free_per_gpu else 0
        total_free = sum(free_per_gpu)

        logger.info(
            f"GPU memory: max_free={max_free}MB, total_free={total_free}MB, "
            f"need={required_memory_mb}MB"
        )

        # If any single GPU has enough memory, we're good
        if max_free >= required_memory_mb:
            logger.info("Sufficient GPU memory available on single GPU, no eviction needed")
            return True, []

        # Try to stop endpoints to free memory
        logger.info("Attempting to evict endpoints to free GPU memory...")

        # Stop endpoints in priority order (lowest priority first)
        # Priority: reasoning > orchestrator > instruct
        stop_order = ["thinking"]

        for endpoint_name in stop_order:
            try:
                # Use subprocess to call CLI for stopping
                logger.info(f"Stopping endpoint: {endpoint_name}")
                stop_result = subprocess.run(
                    ["pkill", "-f", f"vllm.*--port.*{endpoint_name}"],
                    capture_output=True,
                    text=True,
                )

                # Also try via gaius-cli
                stop_result = subprocess.run(
                    [
                        "uv", "run", "--no-sync", "gaius-cli",
                        "--cmd", f"/orch stop {endpoint_name}",
                        "--format", "json",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if stop_result.returncode == 0:
                    evicted.append(endpoint_name)
                    logger.info(f"Stopped endpoint: {endpoint_name}")

                    # Wait for GPU memory to be freed
                    await asyncio.sleep(3)

                    # Check if we have enough memory now
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        free_per_gpu = [int(x.strip()) for x in result.stdout.strip().split("\n")]
                        max_free = max(free_per_gpu) if free_per_gpu else 0
                        if max_free >= required_memory_mb:
                            logger.info(f"Freed enough memory ({max_free}MB on single GPU)")
                            return True, evicted

            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout stopping {endpoint_name}")
            except Exception as e:
                logger.warning(f"Failed to stop {endpoint_name}: {e}")

        # Final check
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            free_per_gpu = [int(x.strip()) for x in result.stdout.strip().split("\n")]
            max_free = max(free_per_gpu) if free_per_gpu else 0
            if max_free >= required_memory_mb:
                return True, evicted

        logger.warning(
            f"Could not free enough GPU memory (max_free={max_free}MB, need={required_memory_mb}MB)"
        )
        return False, evicted

    except Exception as e:
        logger.error(f"GPU memory check failed: {e}")
        return False, []


async def restore_endpoints(endpoint_names: list[str]) -> list[str]:
    """Restore previously evicted endpoints.

    Args:
        endpoint_names: List of endpoint names to restore

    Returns:
        List of successfully restored endpoint names
    """
    restored = []

    if not endpoint_names:
        return restored

    try:
        from gaius.mcp.operations import mcp_call

        for name in endpoint_names:
            logger.info(f"Restoring endpoint: {name}")
            result = await mcp_call("orchestrator_start", {"endpoint": name})
            if "error" not in result:
                restored.append(name)
            else:
                logger.warning(f"Failed to restore {name}: {result.get('error')}")

    except Exception as e:
        logger.error(f"Failed to restore endpoints: {e}")

    return restored


async def run_flow_with_gpu_management(
    flow_class: type,
    flow_args: list[str],
    require_gpu: bool = True,
    estimated_memory_mb: int = 16000,
) -> FlowRunResult:
    """Run a flow with GPU resource management.

    This function:
    1. Checks GPU memory availability
    2. Evicts idle vLLM endpoints if needed
    3. Runs the flow
    4. Restores evicted endpoints after completion

    Args:
        flow_class: The flow class to run
        flow_args: Arguments to pass to the flow
        require_gpu: Whether to require GPU (default True)
        estimated_memory_mb: GPU memory required (default 16GB)

    Returns:
        FlowRunResult with success status and details
    """
    start_time = datetime.now()
    workload_id = f"flow-{flow_class.__name__}-{start_time.strftime('%Y%m%d-%H%M%S')}"
    evicted_endpoints: list[str] = []

    try:
        # Step 1: Request GPU resources (evict if needed)
        if require_gpu:
            logger.info(f"Requesting GPU resources for {flow_class.__name__}")
            success, evicted_endpoints = await request_gpu_resources(
                workload_id=workload_id,
                estimated_memory_mb=estimated_memory_mb,
            )

            if not success and evicted_endpoints:
                # Partial eviction but not enough memory
                logger.warning("Partial eviction - may not have enough GPU memory")
            elif not success:
                return FlowRunResult(
                    success=False,
                    flow_name=flow_class.__name__,
                    workload_id=workload_id,
                    error="Could not allocate GPU resources",
                )

        # Step 2: Find free GPUs and set CUDA_VISIBLE_DEVICES
        free_gpus = find_free_gpus(estimated_memory_mb)
        if free_gpus:
            cuda_devices = ",".join(str(g) for g in free_gpus[:2])  # Use up to 2 GPUs
            logger.info(f"Using GPUs: {cuda_devices}")
        else:
            cuda_devices = None
            logger.warning("No GPUs with sufficient free memory found")

        # Step 3: Run the flow
        logger.info(f"Running flow {flow_class.__name__} with args: {flow_args}")

        # Apply Metaflow config
        from gaius.flows.config import metaflow_child_env

        # Set up environment with CUDA_VISIBLE_DEVICES + resolved Metaflow profile
        env = metaflow_child_env()
        if cuda_devices:
            env["CUDA_VISIBLE_DEVICES"] = cuda_devices

        # Run the flow as a subprocess to avoid module conflicts
        flow_module = flow_class.__module__
        flow_result = subprocess.run(
            [
                "python", "-m", flow_module,
                "run",
                *flow_args,
            ],
            capture_output=True,
            text=True,
            cwd=os.environ.get("GAIUS_PROJECT_ROOT", "."),
            env=env,
        )

        duration = (datetime.now() - start_time).total_seconds()

        if flow_result.returncode != 0:
            return FlowRunResult(
                success=False,
                flow_name=flow_class.__name__,
                workload_id=workload_id,
                evicted_endpoints=evicted_endpoints,
                error=flow_result.stderr or "Flow failed",
                duration_s=duration,
            )

        # Extract output path from stdout if available. Tokens cover both the
        # arXiv zettelkasten path and the generic output_dir path.
        output_path = None
        _output_tokens = ("KB Note:", "Created zettelkasten", "Created output:")
        for line in flow_result.stdout.split("\n"):
            if any(tok in line for tok in _output_tokens):
                parts = line.split(":")
                if len(parts) >= 2:
                    output_path = parts[-1].strip()
                    break

        return FlowRunResult(
            success=True,
            flow_name=flow_class.__name__,
            workload_id=workload_id,
            evicted_endpoints=evicted_endpoints,
            output_path=output_path,
            duration_s=duration,
        )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Flow execution failed: {e}")
        return FlowRunResult(
            success=False,
            flow_name=flow_class.__name__,
            workload_id=workload_id,
            evicted_endpoints=evicted_endpoints,
            error=str(e),
            duration_s=duration,
        )

    finally:
        # Step 4: Restore evicted endpoints
        if evicted_endpoints:
            logger.info(f"Restoring {len(evicted_endpoints)} evicted endpoints")
            restored = await restore_endpoints(evicted_endpoints)
            logger.info(f"Restored endpoints: {restored}")
