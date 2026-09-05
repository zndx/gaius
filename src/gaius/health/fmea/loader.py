"""FMEA failure mode loader and health check mapping.

This module provides:
- Mapping from existing health checks to FMEA failure modes
- Database loading of failure mode catalog
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import FailureMode

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)

# Map existing 18 health checks to FMEA failure modes
HEALTH_CHECK_TO_FMEA: dict[str, str] = {
    # Infrastructure
    "grpc_connection": "INFRA_001",
    "postgresql": "INFRA_002",
    "qdrant": "INFRA_003",
    "rustfs": "INFRA_004",
    "engine_serving": "INFRA_005",

    # GPU
    "gpu_memory": "GPU_001",
    "gpu_temperature": "GPU_002",

    # vLLM Endpoints
    "endpoints": "VLLM_003",
    "vllm_service": "VLLM_003",
    "optillm_service": "VLLM_003",
    "stuck_endpoints": "VLLM_001",
    "stale_processes": "VLLM_004",

    # Model Quality
    "model_routing": "MQ_005",

    # Evolution
    "evolution_daemon": "EV_002",

    # Emergent/Cognition
    "cognition_daemon": "EB_002",
    "recent_thoughts": "EB_004",

    # Resources
    "disk_space": "RC_004",
    "scheduler_queue": "RC_001",
    "xai_budget": "RC_003",

    # RASE (Intrinsic Verification)
    "kb_oracle_state": "RASE_001",
    "kb_objective_loading": "RASE_002",
    "kb_verification_gates": "RASE_003",
    "evidence_capture": "RASE_004",
    "evidence_lineage": "RASE_005",
    "calibration_drift": "RASE_006",
    "calibration_provider": "RASE_007",
    "daemon_oracle_scoring": "RASE_008",
    "objective_task_generation": "RASE_009",

    # Operations - Heartbeat/Progress Anomalies
    "heartbeat_anomaly": "OPS_001",
    "missing_heartbeat": "OPS_002",
    "progress_stall": "OPS_003",
}

# Reverse mapping for lookup
FMEA_TO_HEALTH_CHECK: dict[str, list[str]] = {}
for check, mode in HEALTH_CHECK_TO_FMEA.items():
    FMEA_TO_HEALTH_CHECK.setdefault(mode, []).append(check)


async def load_failure_mode(
    conn: Connection,
    failure_mode_id: str,
) -> FailureMode | None:
    """Load a failure mode from the database.

    Args:
        conn: Database connection
        failure_mode_id: Failure mode ID (e.g., GPU_001)

    Returns:
        FailureMode if found, None otherwise
    """
    row = await conn.fetchrow(
        """
        SELECT
            failure_mode_id, category, name, description,
            base_severity, base_occurrence, base_detection,
            detection_method, recommended_actions, escalation_tier,
            preventive_controls, detective_controls, mitigative_controls
        FROM fmea_catalog
        WHERE failure_mode_id = $1
        """,
        failure_mode_id,
    )

    if not row:
        return None

    return FailureMode(
        failure_mode_id=row["failure_mode_id"],
        category=row["category"],
        name=row["name"],
        description=row["description"],
        base_severity=row["base_severity"],
        base_occurrence=row["base_occurrence"],
        base_detection=row["base_detection"],
        detection_method=row["detection_method"],
        recommended_actions=row["recommended_actions"] or [],
        escalation_tier=row["escalation_tier"] or 0,
        preventive_controls=row["preventive_controls"] or [],
        detective_controls=row["detective_controls"] or [],
        mitigative_controls=row["mitigative_controls"] or [],
    )


async def load_all_failure_modes(conn: Connection) -> list[FailureMode]:
    """Load all failure modes from the database.

    Args:
        conn: Database connection

    Returns:
        List of all failure modes
    """
    rows = await conn.fetch(
        """
        SELECT
            failure_mode_id, category, name, description,
            base_severity, base_occurrence, base_detection,
            detection_method, recommended_actions, escalation_tier,
            preventive_controls, detective_controls, mitigative_controls
        FROM fmea_catalog
        ORDER BY category, failure_mode_id
        """
    )

    return [
        FailureMode(
            failure_mode_id=row["failure_mode_id"],
            category=row["category"],
            name=row["name"],
            description=row["description"],
            base_severity=row["base_severity"],
            base_occurrence=row["base_occurrence"],
            base_detection=row["base_detection"],
            detection_method=row["detection_method"],
            recommended_actions=row["recommended_actions"] or [],
            escalation_tier=row["escalation_tier"] or 0,
            preventive_controls=row["preventive_controls"] or [],
            detective_controls=row["detective_controls"] or [],
            mitigative_controls=row["mitigative_controls"] or [],
        )
        for row in rows
    ]


async def get_failure_modes_by_category(
    conn: Connection,
    category: str,
) -> list[FailureMode]:
    """Get all failure modes in a category.

    Args:
        conn: Database connection
        category: Category name (gpu, vllm, model_quality, etc.)

    Returns:
        List of failure modes in the category
    """
    rows = await conn.fetch(
        """
        SELECT
            failure_mode_id, category, name, description,
            base_severity, base_occurrence, base_detection,
            detection_method, recommended_actions, escalation_tier,
            preventive_controls, detective_controls, mitigative_controls
        FROM fmea_catalog
        WHERE category = $1
        ORDER BY failure_mode_id
        """,
        category,
    )

    return [
        FailureMode(
            failure_mode_id=row["failure_mode_id"],
            category=row["category"],
            name=row["name"],
            description=row["description"],
            base_severity=row["base_severity"],
            base_occurrence=row["base_occurrence"],
            base_detection=row["base_detection"],
            detection_method=row["detection_method"],
            recommended_actions=row["recommended_actions"] or [],
            escalation_tier=row["escalation_tier"] or 0,
            preventive_controls=row["preventive_controls"] or [],
            detective_controls=row["detective_controls"] or [],
            mitigative_controls=row["mitigative_controls"] or [],
        )
        for row in rows
    ]


def map_health_check_to_failure_mode(health_check_name: str) -> str | None:
    """Map a health check name to its corresponding failure mode.

    Args:
        health_check_name: Name of the health check

    Returns:
        Failure mode ID if mapped, None otherwise
    """
    return HEALTH_CHECK_TO_FMEA.get(health_check_name)


def get_health_checks_for_failure_mode(failure_mode_id: str) -> list[str]:
    """Get all health checks that detect a failure mode.

    Args:
        failure_mode_id: Failure mode ID

    Returns:
        List of health check names
    """
    return FMEA_TO_HEALTH_CHECK.get(failure_mode_id, [])
