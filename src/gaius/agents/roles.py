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

    # Core swarm roles
    LEADER = "Leader"
    RISK = "Risk"
    OPTIMIZER = "Optimizer"
    PLANNER = "Planner"
    CRITIC = "Critic"
    EXECUTOR = "Executor"
    ADVERSARY = "Adversary"

    # Cognition/reflection roles
    SYNTHESIZER = "Synthesizer"
    QUESTIONER = "Questioner"
    METACOGNIZER = "Metacognizer"


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

    # Model affinity - preferred model characteristics
    preferred_model_id: str | None = None  # Explicit model preference
    model_capabilities: list[str] = field(default_factory=list)  # Required capabilities
    min_context_length: int = 4096  # Minimum context window needed

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
    preferred_model_id="Qwen/QwQ-32B",  # Needs strong reasoning
    model_capabilities=["reasoning", "long_context"],
    min_context_length=16384,
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
    preferred_model_id=None,  # Fast model OK - uses default
    model_capabilities=["reasoning"],
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
    preferred_model_id=None,  # Fast model OK
    model_capabilities=["reasoning"],
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
    preferred_model_id="Qwen/Qwen3-Coder-30B-A3B-Instruct",  # Good at structured output
    model_capabilities=["reasoning", "long_context"],
    min_context_length=8192,
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
    preferred_model_id="Qwen/QwQ-32B",  # Strong reasoning for finding flaws
    model_capabilities=["reasoning"],
    min_context_length=8192,
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
    preferred_model_id="Qwen/Qwen3-Coder-30B-A3B-Instruct",  # Good at implementation details
    model_capabilities=["coding", "reasoning"],
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
    preferred_model_id="grok-2-latest",  # Frontier model for adversarial thinking
    model_capabilities=["reasoning", "adversarial"],
    min_context_length=8192,
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
# Cognition/Reflection Roles
# ═══════════════════════════════════════════════════════════════════════════

SYNTHESIZER = RoleDefinition(
    role=AgentRole.SYNTHESIZER,
    name="Synthesizer",
    description="Cross-domain pattern synthesis and connection finding",
    color="dark_orange",
    temperature=0.7,
    preferred_model_id="Qwen/QwQ-32B",  # Strong reasoning for pattern recognition
    model_capabilities=["reasoning", "long_context"],
    min_context_length=16384,
    projection_behavior="center",
    cluster_affinity=0.8,
    responds_to=[],
    triggers=[AgentRole.QUESTIONER],
    system_prompt="""You are the Synthesizer agent in a knowledge reflection system.

DOMAIN: {domain}

Your role is finding non-obvious patterns and connections across knowledge. You:
1. Identify emergent themes across seemingly unrelated entries
2. Find structural similarities between different domains
3. Synthesize fragments into coherent understanding
4. Detect when separate ideas are actually the same concept

CONTEXT:
{context}

Synthesize the available knowledge. Look for:
- Patterns that span multiple entries or domains
- Surprising connections that aren't explicitly stated
- Themes that are emerging from recent activity
- Contradictions that need resolution

Be specific about what you're connecting and why. Don't force connections—
only report genuine insights.
""",
)

QUESTIONER = RoleDefinition(
    role=AgentRole.QUESTIONER,
    name="Questioner",
    description="Curiosity-driven question generation",
    color="medium_purple",
    temperature=0.8,
    preferred_model_id=None,  # Default model is fine
    model_capabilities=["reasoning"],
    projection_behavior="peripheral",
    cluster_affinity=0.3,
    responds_to=[AgentRole.SYNTHESIZER],
    triggers=[AgentRole.METACOGNIZER],
    system_prompt="""You are the Questioner agent in a knowledge reflection system.

DOMAIN: {domain}

Your role is generating curiosity-driven questions that advance understanding. You:
1. Identify gaps in current knowledge
2. Generate questions that connect multiple concepts
3. Find the interesting "edges" where understanding breaks down
4. Propose research directions worth pursuing

CONTEXT:
{context}

Generate questions that:
- Cannot be answered by simple lookup
- Would genuinely advance understanding if answered
- Connect ideas across the knowledge base
- Are tractable (not too vague or philosophical)

Focus on questions that feel alive—things you'd actually want to know.
Avoid generic or procedural questions.
""",
)

METACOGNIZER = RoleDefinition(
    role=AgentRole.METACOGNIZER,
    name="Metacognizer",
    description="Understanding quality assessment and confidence calibration",
    color="grey70",
    temperature=0.5,
    preferred_model_id="Qwen/QwQ-32B",  # Needs careful reasoning about reasoning
    model_capabilities=["reasoning"],
    min_context_length=8192,
    projection_behavior="center",
    cluster_affinity=0.5,
    responds_to=[AgentRole.QUESTIONER],
    triggers=[],
    system_prompt="""You are the Metacognizer agent in a knowledge reflection system.

DOMAIN: {domain}

Your role is assessing the quality of understanding and calibrating confidence. You:
1. Evaluate how well the knowledge base covers the domain
2. Identify areas of high vs low confidence
3. Detect where understanding is superficial vs deep
4. Track how understanding has evolved over time

CONTEXT:
{context}

Assess the state of understanding:
- Where do we have solid, well-supported knowledge?
- Where is understanding fragile or based on assumptions?
- What would increase confidence in uncertain areas?
- How has the picture changed recently?

Be honest about limitations. Distinguish between "we don't know" and
"we haven't looked." Flag overconfidence where it exists.
""",
)


# ═══════════════════════════════════════════════════════════════════════════
# Role Registry
# ═══════════════════════════════════════════════════════════════════════════

ROLES: dict[AgentRole, RoleDefinition] = {
    # Core swarm roles
    AgentRole.LEADER: LEADER,
    AgentRole.RISK: RISK,
    AgentRole.OPTIMIZER: OPTIMIZER,
    AgentRole.PLANNER: PLANNER,
    AgentRole.CRITIC: CRITIC,
    AgentRole.EXECUTOR: EXECUTOR,
    AgentRole.ADVERSARY: ADVERSARY,
    # Cognition/reflection roles
    AgentRole.SYNTHESIZER: SYNTHESIZER,
    AgentRole.QUESTIONER: QUESTIONER,
    AgentRole.METACOGNIZER: METACOGNIZER,
}

# Subset for swarm analysis (original 7)
SWARM_ROLES: dict[AgentRole, RoleDefinition] = {
    AgentRole.LEADER: LEADER,
    AgentRole.RISK: RISK,
    AgentRole.OPTIMIZER: OPTIMIZER,
    AgentRole.PLANNER: PLANNER,
    AgentRole.CRITIC: CRITIC,
    AgentRole.EXECUTOR: EXECUTOR,
    AgentRole.ADVERSARY: ADVERSARY,
}

# Subset for cognition/reflection
COGNITION_ROLES: dict[AgentRole, RoleDefinition] = {
    AgentRole.SYNTHESIZER: SYNTHESIZER,
    AgentRole.QUESTIONER: QUESTIONER,
    AgentRole.METACOGNIZER: METACOGNIZER,
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


def get_swarm_roles() -> list[RoleDefinition]:
    """Get role definitions for swarm analysis (original 7)."""
    return list(SWARM_ROLES.values())


def get_cognition_roles() -> list[RoleDefinition]:
    """Get role definitions for cognition/reflection."""
    return list(COGNITION_ROLES.values())


def get_role_colors() -> dict[str, str]:
    """Get mapping of role names to colors."""
    return {r.name: r.color for r in ROLES.values()}
