"""Agent definitions and swarm management.

Includes:
- Role definitions and swarm orchestration
- LatentMAS-style latent collaboration (latent/)
- Agent0-style self-evolution (evolution/)
"""

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
    LatentSwarmManager,
    get_latent_swarm_manager,
    run_latent_swarm_round,
)
from .daily_summary import (
    DailySummaryAgent,
    DailySummaryNote,
    get_daily_summary_agent,
    generate_daily_summary,
)
from .metaagent_swarm import (
    MetaAgentManager,
    MetaAgentResult,
    MetaAgentEvent,
    MetaAgentEventType,
    AnalystInsight,
)

# Lazy imports for optional modules
def get_latent_memory():
    """Get latent working memory singleton."""
    from .latent import get_latent_memory as _get
    return _get()

def get_evolution_daemon():
    """Get evolution daemon singleton."""
    from .evolution import get_evolution_daemon as _get
    return _get()

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
    # Latent Swarm
    "LatentSwarmManager",
    "get_latent_swarm_manager",
    "run_latent_swarm_round",
    "get_latent_memory",
    # Evolution
    "get_evolution_daemon",
    # Daily Summary
    "DailySummaryAgent",
    "DailySummaryNote",
    "get_daily_summary_agent",
    "generate_daily_summary",
    # MetaAgent
    "MetaAgentManager",
    "MetaAgentResult",
    "MetaAgentEvent",
    "MetaAgentEventType",
    "AnalystInsight",
]
