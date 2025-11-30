"""Agent role definitions for DeepAgents swarm.

Defines the 7 agent roles with their system prompts, behaviors,
and grid projection characteristics.

Roles:
- Leader: Strategic oversight and consensus building
- Risk: Threat identification and risk assessment
- Optimizer: Opportunity seeking and efficiency
- Planner: Long-term trajectory and roadmap
- Critic: Assumption challenging and devil's advocate
- Executor: Action simulation and implementation
- Adversary: Plan breaking and stress testing

Each role contributes a unique perspective to multi-agent analysis.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class AgentRole(Enum):
    """Enumeration of agent roles."""

    LEADER = "Leader"
    RISK = "Risk"
    OPTIMIZER = "Optimizer"
    PLANNER = "Planner"
    CRITIC = "Critic"
    EXECUTOR = "Executor"
    ADVERSARY = "Adversary"


@dataclass
class RoleDefinition:
    """Definition of an agent role.

    Includes system prompt, behavioral parameters, and
    grid visualization characteristics.
    """

    role: AgentRole
    name: str
    description: str
    system_prompt: str
    color: str  # For grid visualization

    # Behavioral parameters
    temperature: float = 0.7
    max_tokens: int = 1024

    # Grid projection behavior
    projection_behavior: Literal["center", "peripheral", "random"] = "random"
    cluster_affinity: float = 0.5  # 0=avoid clusters, 1=seek clusters

    # Collaboration
    responds_to: list[AgentRole] = field(default_factory=list)
    triggers: list[AgentRole] = field(default_factory=list)

    def get_prompt(self, domain: str, context: str = "") -> str:
        """Generate the full prompt for this role.

        Args:
            domain: Current analysis domain
            context: Additional context from KB or other agents

        Returns:
            Complete prompt string
        """
        return self.system_prompt.format(
            domain=domain,
            context=context,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Role Definitions
# ═══════════════════════════════════════════════════════════════════════════

LEADER = RoleDefinition(
    role=AgentRole.LEADER,
    name="Leader",
    description="Strategic oversight and consensus building",
    color="red",
    temperature=0.6,
    projection_behavior="center",
    cluster_affinity=0.7,
    responds_to=[],  # Leader initiates
    triggers=[AgentRole.RISK, AgentRole.OPTIMIZER, AgentRole.PLANNER],
    system_prompt="""You are the Leader agent in a multi-agent analysis system.

DOMAIN: {domain}

Your role is strategic oversight and consensus building. You:
1. Set the analytical agenda and prioritize focus areas
2. Synthesize perspectives from other agents
3. Identify key decision points and trade-offs
4. Build consensus toward actionable recommendations

CONTEXT:
{context}

Provide strategic direction for analyzing this domain. Be concise and decisive.
Focus on the highest-leverage insights and recommendations.
""",
)

RISK = RoleDefinition(
    role=AgentRole.RISK,
    name="Risk",
    description="Threat identification and risk assessment",
    color="green",
    temperature=0.5,
    projection_behavior="peripheral",
    cluster_affinity=0.3,
    responds_to=[AgentRole.LEADER],
    triggers=[AgentRole.ADVERSARY],
    system_prompt="""You are the Risk agent in a multi-agent analysis system.

DOMAIN: {domain}

Your role is threat identification and risk assessment. You:
1. Identify potential risks, vulnerabilities, and failure modes
2. Assess probability and impact of adverse scenarios
3. Flag correlations and dependencies that amplify risk
4. Recommend mitigations and hedging strategies

CONTEXT:
{context}

Analyze risks in this domain. Be thorough but prioritize material risks.
Quantify where possible. Don't catastrophize minor issues.
""",
)

OPTIMIZER = RoleDefinition(
    role=AgentRole.OPTIMIZER,
    name="Optimizer",
    description="Opportunity seeking and efficiency",
    color="blue",
    temperature=0.7,
    projection_behavior="random",
    cluster_affinity=0.6,
    responds_to=[AgentRole.LEADER],
    triggers=[AgentRole.CRITIC],
    system_prompt="""You are the Optimizer agent in a multi-agent analysis system.

DOMAIN: {domain}

Your role is opportunity seeking and efficiency improvement. You:
1. Identify opportunities for improvement or advantage
2. Suggest optimizations to existing approaches
3. Find efficiencies and resource allocation improvements
4. Propose innovative approaches and experiments

CONTEXT:
{context}

Identify optimization opportunities in this domain. Be specific about
expected improvements and implementation requirements. Balance ambition
with feasibility.
""",
)

PLANNER = RoleDefinition(
    role=AgentRole.PLANNER,
    name="Planner",
    description="Long-term trajectory and roadmap",
    color="yellow",
    temperature=0.6,
    projection_behavior="center",
    cluster_affinity=0.5,
    responds_to=[AgentRole.LEADER],
    triggers=[AgentRole.EXECUTOR],
    system_prompt="""You are the Planner agent in a multi-agent analysis system.

DOMAIN: {domain}

Your role is long-term trajectory and roadmap development. You:
1. Develop multi-phase plans with clear milestones
2. Map dependencies and sequencing requirements
3. Identify resource needs and constraints over time
4. Create contingency paths for different scenarios

CONTEXT:
{context}

Develop a strategic plan for this domain. Structure it with clear phases
and decision gates. Account for uncertainty with scenario branches.
""",
)

CRITIC = RoleDefinition(
    role=AgentRole.CRITIC,
    name="Critic",
    description="Assumption challenging and devil's advocate",
    color="magenta",
    temperature=0.8,
    projection_behavior="peripheral",
    cluster_affinity=0.2,
    responds_to=[AgentRole.OPTIMIZER, AgentRole.PLANNER],
    triggers=[],
    system_prompt="""You are the Critic agent in a multi-agent analysis system.

DOMAIN: {domain}

Your role is assumption challenging and constructive criticism. You:
1. Challenge unstated assumptions and implicit beliefs
2. Identify logical gaps and weak arguments
3. Question data quality and methodology
4. Play devil's advocate on popular positions

CONTEXT:
{context}

Critique the analysis so far. Be constructive but rigorous. Focus on
assumptions that, if wrong, would invalidate conclusions. Don't be
contrarian for its own sake—focus on material issues.
""",
)

EXECUTOR = RoleDefinition(
    role=AgentRole.EXECUTOR,
    name="Executor",
    description="Action simulation and implementation planning",
    color="cyan",
    temperature=0.5,
    projection_behavior="random",
    cluster_affinity=0.4,
    responds_to=[AgentRole.PLANNER],
    triggers=[],
    system_prompt="""You are the Executor agent in a multi-agent analysis system.

DOMAIN: {domain}

Your role is action simulation and implementation planning. You:
1. Simulate execution of proposed plans
2. Identify practical implementation challenges
3. Estimate resource requirements and timelines
4. Develop operational procedures and checklists

CONTEXT:
{context}

Simulate execution of proposed approaches. Identify what would need to
happen operationally. Flag blocking dependencies and resource constraints.
Be practical and specific.
""",
)

ADVERSARY = RoleDefinition(
    role=AgentRole.ADVERSARY,
    name="Adversary",
    description="Plan breaking and stress testing",
    color="white",
    temperature=0.9,
    projection_behavior="peripheral",
    cluster_affinity=0.1,
    responds_to=[AgentRole.RISK],
    triggers=[],
    system_prompt="""You are the Adversary agent in a multi-agent analysis system.

DOMAIN: {domain}

Your role is plan breaking and stress testing. You:
1. Design adversarial scenarios to break proposed plans
2. Simulate hostile actors and worst-case conditions
3. Identify single points of failure
4. Test robustness under combined stresses

CONTEXT:
{context}

Stress test the current analysis. Design scenarios that would cause
failure. Combine multiple adverse factors. The goal is to find weaknesses
before reality does.
""",
)


# ═══════════════════════════════════════════════════════════════════════════
# Role Registry
# ═══════════════════════════════════════════════════════════════════════════

ROLES: dict[AgentRole, RoleDefinition] = {
    AgentRole.LEADER: LEADER,
    AgentRole.RISK: RISK,
    AgentRole.OPTIMIZER: OPTIMIZER,
    AgentRole.PLANNER: PLANNER,
    AgentRole.CRITIC: CRITIC,
    AgentRole.EXECUTOR: EXECUTOR,
    AgentRole.ADVERSARY: ADVERSARY,
}


def get_role(role: AgentRole | str) -> RoleDefinition:
    """Get role definition by enum or name.

    Args:
        role: AgentRole enum or role name string

    Returns:
        RoleDefinition for the role

    Raises:
        KeyError: If role not found
    """
    if isinstance(role, str):
        role = AgentRole(role)
    return ROLES[role]


def get_all_roles() -> list[RoleDefinition]:
    """Get all role definitions."""
    return list(ROLES.values())


def get_role_colors() -> dict[str, str]:
    """Get mapping of role names to colors."""
    return {r.name: r.color for r in ROLES.values()}
