"""Agent definitions and swarm management."""

from .roles import (
    AgentRole,
    RoleDefinition,
    get_role,
    get_all_roles,
    get_role_colors,
    ROLES,
)
from .swarm import (
    SwarmManager,
    SwarmRoundResult,
    AgentResponse,
    get_swarm_manager,
    run_swarm_round,
)

__all__ = [
    # Roles
    "AgentRole",
    "RoleDefinition",
    "get_role",
    "get_all_roles",
    "get_role_colors",
    "ROLES",
    # Swarm
    "SwarmManager",
    "SwarmRoundResult",
    "AgentResponse",
    "get_swarm_manager",
    "run_swarm_round",
]
