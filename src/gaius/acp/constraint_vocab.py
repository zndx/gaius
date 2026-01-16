"""CP-SAT constraint vocabulary for RCA analysis.

This module maps failure modes to the specific OR-Tools CP-SAT constraints
in makespan_scheduler.py, enabling higher-order RCA observations to connect
symptoms to constraint violations.

The constraint vocabulary supports Order 3 (Invariant Violation) and
Order 4 (Design Principle) observations in the RCA abstraction ladder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EnforcementMode(Enum):
    """When a constraint is enforced.

    POINT_IN_TIME: Only at transition moments (current behavior)
    CONTINUOUS: Enforced throughout execution (ideal behavior)
    REACTIVE: Enforced when violation detected (current health monitoring)
    """
    POINT_IN_TIME = "point_in_time"
    CONTINUOUS = "continuous"
    REACTIVE = "reactive"


@dataclass
class CPSATConstraint:
    """A CP-SAT constraint definition from makespan_scheduler.py.

    Attributes:
        constraint_id: Unique identifier (e.g., GPU_MUTUAL_EXCLUSION)
        description: Human-readable description
        location: File path and line range in makespan_scheduler.py
        cpsat_form: OR-Tools syntax for the constraint
        failure_modes: FMEA failure modes this constraint prevents
        enforcement: Current enforcement mode
        enforcement_gap: Description of gap if not continuous
    """
    constraint_id: str
    description: str
    location: str
    cpsat_form: str
    failure_modes: list[str] = field(default_factory=list)
    enforcement: EnforcementMode = EnforcementMode.POINT_IN_TIME
    enforcement_gap: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "constraint_id": self.constraint_id,
            "description": self.description,
            "location": self.location,
            "cpsat_form": self.cpsat_form,
            "failure_modes": self.failure_modes,
            "enforcement": self.enforcement.value,
            "enforcement_gap": self.enforcement_gap,
        }


# CP-SAT Constraint Vocabulary
# Line numbers reference makespan_scheduler.py
CPSAT_CONSTRAINTS: dict[str, CPSATConstraint] = {
    "GPU_REQUIRED_COUNT": CPSATConstraint(
        constraint_id="GPU_REQUIRED_COUNT",
        description="Each task gets exactly required_gpus GPUs",
        location="engine/scheduling/makespan_scheduler.py:204-208",
        cpsat_form="model.Add(sum(x[task.task_id, g] for g in available_gpus) == task.required_gpus)",
        failure_modes=["GPU_002"],  # Under-provisioned endpoint
        enforcement=EnforcementMode.POINT_IN_TIME,
    ),
    "GPU_MUTUAL_EXCLUSION": CPSATConstraint(
        constraint_id="GPU_MUTUAL_EXCLUSION",
        description="Each GPU assigned to at most one task",
        location="engine/scheduling/makespan_scheduler.py:210-212",
        cpsat_form="model.Add(sum(x[task.task_id, gpu] for task in to_start) <= 1)",
        failure_modes=["GPU_001"],  # GPU memory exhaustion from overlap
        enforcement=EnforcementMode.POINT_IN_TIME,
        enforcement_gap="Only enforced at scheduler invocation, not continuously during execution. "
                        "Runtime GPU allocations outside scheduler bypass this constraint.",
    ),
    "CONTIGUITY_REQUIREMENT": CPSATConstraint(
        constraint_id="CONTIGUITY_REQUIREMENT",
        description="Tasks requiring tensor parallelism get contiguous GPUs",
        location="engine/scheduling/makespan_scheduler.py:283-324",
        cpsat_form="model.AddExactlyOne(y[valid_starts])",
        failure_modes=["GPU_002", "SCHED_002"],
        enforcement=EnforcementMode.POINT_IN_TIME,
        enforcement_gap="Contiguity checked at planning time but NVLink topology not re-verified at runtime.",
    ),
    "PRECEDENCE": CPSATConstraint(
        constraint_id="PRECEDENCE",
        description="Cannot start until GPUs freed by stopped tasks",
        location="engine/scheduling/makespan_scheduler.py:245-253",
        cpsat_form="model.Add(start_begin[task] >= stop_end[stopped]).OnlyEnforceIf(x[task, gpu])",
        failure_modes=["SCHED_001", "GPU_001"],
        enforcement=EnforcementMode.POINT_IN_TIME,
        enforcement_gap="Precedence relies on accurate stop timing estimates. "
                        "Actual stop times may vary, causing race conditions.",
    ),
    "RESOURCE_FEASIBILITY": CPSATConstraint(
        constraint_id="RESOURCE_FEASIBILITY",
        description="Total required GPUs must not exceed available",
        location="engine/scheduling/makespan_scheduler.py:181-191",
        cpsat_form="total_required <= len(available_gpus)",
        failure_modes=["SCHED_002"],
        enforcement=EnforcementMode.POINT_IN_TIME,
        enforcement_gap="Pre-check before solver runs. Does not account for concurrent requests.",
    ),
}


# Failure Mode to Constraint Mapping
FAILURE_MODE_CONSTRAINTS: dict[str, list[str]] = {
    "GPU_001": ["GPU_MUTUAL_EXCLUSION", "PRECEDENCE"],  # Memory exhaustion
    "GPU_002": ["GPU_REQUIRED_COUNT", "CONTIGUITY_REQUIREMENT"],  # Under-provisioned
    "SCHED_001": ["PRECEDENCE"],  # Scheduling race condition
    "SCHED_002": ["RESOURCE_FEASIBILITY", "CONTIGUITY_REQUIREMENT"],  # No feasible schedule
    "VLLM_001": ["GPU_MUTUAL_EXCLUSION"],  # Endpoint crash often from GPU conflict
}


def get_constraints_for_failure_mode(failure_mode_id: str) -> list[CPSATConstraint]:
    """Get all constraints relevant to a failure mode.

    Args:
        failure_mode_id: FMEA failure mode ID (e.g., GPU_001)

    Returns:
        List of CPSATConstraint objects
    """
    constraint_ids = FAILURE_MODE_CONSTRAINTS.get(failure_mode_id, [])
    return [
        CPSAT_CONSTRAINTS[cid]
        for cid in constraint_ids
        if cid in CPSAT_CONSTRAINTS
    ]


def format_constraints_table(constraints: list[CPSATConstraint]) -> str:
    """Format constraints as markdown table for RCA prompts.

    Args:
        constraints: List of constraints to format

    Returns:
        Markdown table string
    """
    if not constraints:
        return "_No constraints mapped to this failure mode._"

    lines = [
        "| Constraint | Location | Gap |",
        "|------------|----------|-----|",
    ]

    for c in constraints:
        gap = c.enforcement_gap or "None"
        # Truncate gap for table
        if len(gap) > 60:
            gap = gap[:57] + "..."
        lines.append(f"| `{c.constraint_id}` | `{c.location}` | {gap} |")

    return "\n".join(lines)


def get_constraint_by_id(constraint_id: str) -> CPSATConstraint | None:
    """Get a constraint by its ID.

    Args:
        constraint_id: Constraint identifier

    Returns:
        CPSATConstraint or None if not found
    """
    return CPSAT_CONSTRAINTS.get(constraint_id)


def get_design_principles() -> dict[str, str]:
    """Get Order 4 design principles derived from constraint gaps.

    Returns:
        Dict mapping principle ID to description
    """
    return {
        "CONTINUOUS_RESOURCE_ALLOCATION": (
            "GPU allocation should be a continuous constraint, not point-in-time. "
            "The scheduler should monitor GPU assignments throughout execution and "
            "detect violations before they cause OOM errors."
        ),
        "RUNTIME_CONSTRAINT_MONITORING": (
            "CP-SAT constraints enforced at transition time should have corresponding "
            "runtime monitors. The health stream should detect constraint violations "
            "and trigger preventive remediation."
        ),
        "TOPOLOGY_AWARE_VALIDATION": (
            "NVLink topology constraints should be validated both at planning time "
            "and at endpoint startup. Hardware topology changes should trigger re-planning."
        ),
        "CONCURRENT_REQUEST_SERIALIZATION": (
            "Scheduling requests should be serialized or use optimistic concurrency control "
            "to prevent race conditions between concurrent start operations."
        ),
    }
