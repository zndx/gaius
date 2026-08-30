"""Consolidated FMEA Registry for Health FSM.

This module provides a unified registry for mapping between:
- FMEA failure mode IDs (e.g., GPU_001, VLLM_001)
- KB heuristic paths (e.g., inference/gpu_memory_exhausted)
- Health check names (e.g., gpu_memory, stuck_endpoints)
- Endpoint patterns for matching

This is the critical bridge that allows:
1. Incidents (identified by FMEA codes) to match health checks (identified by heuristic paths)
2. Health checks to map to FMEA failure modes for incident creation
3. Unified lookup for FSM state transitions

Hardcoded in Python (per user decision) for simplicity and type safety.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FMEAMapping:
    """Complete mapping for a failure mode."""

    fmea_id: str
    """FMEA failure mode ID (e.g., GPU_001)"""

    heuristic_path: str
    """KB heuristic path (e.g., inference/gpu_memory_exhausted)"""

    check_names: tuple[str, ...]
    """Health check names that detect this failure mode"""

    endpoint_pattern: str | None = None
    """Optional endpoint pattern for matching (e.g., 'gpu_*' or None for any)"""


# Master registry - single source of truth for all mappings
FMEA_REGISTRY: tuple[FMEAMapping, ...] = (
    # GPU failures
    FMEAMapping(
        fmea_id="GPU_001",
        heuristic_path="inference/gpu_memory_exhausted",
        check_names=("gpu_memory",),
        endpoint_pattern="gpu_*",
    ),
    FMEAMapping(
        fmea_id="GPU_002",
        heuristic_path="inference/gpu_temperature",
        check_names=("gpu_temperature",),
        endpoint_pattern="gpu_*",
    ),
    # vLLM failures
    FMEAMapping(
        fmea_id="VLLM_001",
        heuristic_path="inference/endpoint_stuck",
        check_names=("stuck_endpoints",),
    ),
    FMEAMapping(
        fmea_id="VLLM_002",
        heuristic_path="inference/endpoint_stuck",
        check_names=("stuck_endpoints",),
    ),
    FMEAMapping(
        fmea_id="VLLM_003",
        heuristic_path="inference/endpoint_unhealthy",
        check_names=("endpoints", "vllm_service", "optillm_service"),
    ),
    FMEAMapping(
        fmea_id="VLLM_004",
        heuristic_path="inference/stale_vllm_processes",
        check_names=("stale_processes",),
    ),
    FMEAMapping(
        fmea_id="VLLM_005",
        heuristic_path="inference/gpu_memory_exhausted",
        check_names=("gpu_memory",),
    ),
    # Infrastructure
    FMEAMapping(
        fmea_id="INFRA_001",
        heuristic_path="engine/grpc_connection_stale",
        check_names=("grpc_connection",),
    ),
    FMEAMapping(
        fmea_id="INFRA_002",
        heuristic_path="data/database_connection_failed",
        check_names=("postgresql",),
    ),
    FMEAMapping(
        fmea_id="INFRA_003",
        heuristic_path="data/qdrant_connection",
        check_names=("qdrant",),
    ),
    FMEAMapping(
        fmea_id="INFRA_004",
        heuristic_path="data/minio_connection",
        check_names=("minio",),
    ),
    FMEAMapping(
        fmea_id="INFRA_005",
        heuristic_path="engine/serving_desync",
        check_names=("engine_serving",),
    ),
    FMEAMapping(
        fmea_id="MF_003",
        heuristic_path="infrastructure/metaflow_stack_down",
        check_names=("metaflow_stack",),
    ),
    FMEAMapping(
        fmea_id="MF_004",
        heuristic_path="infrastructure/k8s_dns_failure",
        check_names=("metaflow_stack", "coredns"),
    ),
    # Model Quality
    FMEAMapping(
        fmea_id="MQ_005",
        heuristic_path="model/routing_failure",
        check_names=("model_routing",),
    ),
    # Evolution
    FMEAMapping(
        fmea_id="EV_002",
        heuristic_path="evolution/daemon_not_running",
        check_names=("evolution_daemon",),
    ),
    # Cognition/Emergent Behavior
    FMEAMapping(
        fmea_id="EB_002",
        heuristic_path="cognition/daemon_not_running",
        check_names=("cognition_daemon",),
    ),
    FMEAMapping(
        fmea_id="EB_004",
        heuristic_path="cognition/thoughts_stale",
        check_names=("recent_thoughts",),
    ),
    # Resources
    FMEAMapping(
        fmea_id="RC_001",
        heuristic_path="resource/scheduler_queue_full",
        check_names=("scheduler_queue",),
    ),
    FMEAMapping(
        fmea_id="RC_003",
        heuristic_path="resource/xai_budget_exhausted",
        check_names=("xai_budget",),
    ),
    FMEAMapping(
        fmea_id="RC_004",
        heuristic_path="resource/disk_space_low",
        check_names=("disk_space",),
    ),
    # RASE (Intrinsic Verification)
    FMEAMapping(
        fmea_id="RASE_001",
        heuristic_path="rase/oracle_state_invalid",
        check_names=("kb_oracle_state",),
    ),
    FMEAMapping(
        fmea_id="RASE_002",
        heuristic_path="rase/objective_loading_failed",
        check_names=("kb_objective_loading",),
    ),
    FMEAMapping(
        fmea_id="RASE_003",
        heuristic_path="rase/verification_gates_failed",
        check_names=("kb_verification_gates",),
    ),
    FMEAMapping(
        fmea_id="RASE_004",
        heuristic_path="rase/evidence_capture_failed",
        check_names=("evidence_capture",),
    ),
    FMEAMapping(
        fmea_id="RASE_005",
        heuristic_path="rase/evidence_lineage_broken",
        check_names=("evidence_lineage",),
    ),
    FMEAMapping(
        fmea_id="RASE_006",
        heuristic_path="rase/calibration_drift",
        check_names=("calibration_drift",),
    ),
    FMEAMapping(
        fmea_id="RASE_007",
        heuristic_path="rase/calibration_provider_failed",
        check_names=("calibration_provider",),
    ),
    FMEAMapping(
        fmea_id="RASE_008",
        heuristic_path="rase/daemon_oracle_scoring_failed",
        check_names=("daemon_oracle_scoring",),
    ),
    FMEAMapping(
        fmea_id="RASE_009",
        heuristic_path="rase/task_generation_failed",
        check_names=("objective_task_generation",),
    ),
    # Operations - Heartbeat/Progress Anomalies
    FMEAMapping(
        fmea_id="OPS_001",
        heuristic_path="operations/heartbeat_anomaly",
        check_names=("heartbeat_anomaly",),
    ),
    FMEAMapping(
        fmea_id="OPS_002",
        heuristic_path="operations/missing_heartbeat",
        check_names=("missing_heartbeat",),
    ),
    FMEAMapping(
        fmea_id="OPS_003",
        heuristic_path="operations/progress_stall",
        check_names=("progress_stall",),
    ),
)

# Build index structures for fast lookup
_FMEA_BY_ID: dict[str, FMEAMapping] = {m.fmea_id: m for m in FMEA_REGISTRY}
_FMEA_BY_HEURISTIC: dict[str, FMEAMapping] = {m.heuristic_path: m for m in FMEA_REGISTRY}
_FMEA_BY_CHECK: dict[str, FMEAMapping] = {}
for mapping in FMEA_REGISTRY:
    for check_name in mapping.check_names:
        _FMEA_BY_CHECK[check_name] = mapping


def get_fmea_for_check(check_name: str) -> FMEAMapping | None:
    """Get FMEA mapping for a health check name.

    Args:
        check_name: Health check name (e.g., 'gpu_memory', 'stuck_endpoints')

    Returns:
        FMEAMapping if found, None otherwise
    """
    return _FMEA_BY_CHECK.get(check_name)


def get_fmea_for_heuristic(heuristic_path: str) -> FMEAMapping | None:
    """Get FMEA mapping for a heuristic path.

    Args:
        heuristic_path: KB heuristic path (e.g., 'inference/gpu_memory_exhausted')

    Returns:
        FMEAMapping if found, None otherwise
    """
    return _FMEA_BY_HEURISTIC.get(heuristic_path)


def get_fmea_by_id(fmea_id: str) -> FMEAMapping | None:
    """Get FMEA mapping by failure mode ID.

    Args:
        fmea_id: FMEA failure mode ID (e.g., 'GPU_001')

    Returns:
        FMEAMapping if found, None otherwise
    """
    return _FMEA_BY_ID.get(fmea_id)


def get_heuristics_for_fmea(fmea_id: str) -> str | None:
    """Get heuristic path for an FMEA failure mode ID.

    Args:
        fmea_id: FMEA failure mode ID (e.g., 'GPU_001')

    Returns:
        Heuristic path if found, None otherwise
    """
    mapping = _FMEA_BY_ID.get(fmea_id)
    return mapping.heuristic_path if mapping else None


def incident_matches_check(incident_fmea_id: str, check_heuristic_id: str) -> bool:
    """Check if an incident's FMEA ID matches a health check's heuristic ID.

    This is the key function for resolving incidents. It bridges the gap between:
    - Incidents identified by FMEA codes (e.g., GPU_001)
    - Health checks identified by heuristic paths (e.g., inference/gpu_memory_exhausted)

    Args:
        incident_fmea_id: FMEA ID from incident (e.g., 'GPU_001')
        check_heuristic_id: Heuristic path from check (e.g., 'inference/gpu_memory_exhausted')

    Returns:
        True if they map to the same failure mode
    """
    # Get the FMEA mapping for the incident
    incident_mapping = _FMEA_BY_ID.get(incident_fmea_id)
    if not incident_mapping:
        return False

    # Check if the check's heuristic path matches
    return incident_mapping.heuristic_path == check_heuristic_id
